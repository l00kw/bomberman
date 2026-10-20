#!/usr/bin/env python3
"""Terminal Bomberman.

Run:      python3 bomberman.py [--width W] [--height H] [--player EMOJI]
          e.g. python3 bomberman.py --width 31 --height 15 --player 🐱
Controls: arrows / WASD to move, SPACE to drop a bomb, P to pause, Q to quit.

Clear every enemy, then find the exit door hidden under a brick to reach the
next level. Power-ups also hide under bricks:
  B = +1 bomb    F = +1 flame range    S = speed up
"""

import argparse
import curses
import locale
import random
import time
import unicodedata

# ---------------------------------------------------------------- constants --
DEFAULT_W, DEFAULT_H = 15, 13 # board size in cells (odd looks best: pillars line up)
MIN_SIZE = 7
DEFAULT_PLAYER = "🐱"
EMPTY, WALL, BRICK = 0, 1, 2
FUSE = 2.5                    # seconds before a bomb explodes
FLAME_TIME = 0.5              # seconds fire stays on the board
BASE_MOVE_DELAY = 0.14        # seconds between player steps
ENEMY_DELAY = 0.55            # seconds between enemy steps
START_LIVES = 3
POWERUPS = ("bomb", "fire", "speed")
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]


class Bomb:
    def __init__(self, x, y, explode_at, rng):
        self.x, self.y = x, y
        self.explode_at = explode_at
        self.range = rng
        self.player_can_pass = True   # until the player steps off it


class Enemy:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.dir = random.choice(DIRS)
        self.alive = True


# ------------------------------------------------------------- game logic --
class Game:
    """Pure game state and rules; knows nothing about curses."""

    def __init__(self, seed=None, now=0.0, width=DEFAULT_W, height=DEFAULT_H):
        self.w, self.h = width, height
        self.rand = random.Random(seed)
        self.level = 1
        self.score = 0
        self.lives = START_LIVES
        self.max_bombs = 1
        self.fire_range = 1
        self.speed = 0
        self.game_over = False
        self.message = ""
        self.message_until = 0.0
        self.new_level(now)

    # ---- setup
    def new_level(self, now):
        W, H = self.w, self.h
        self.grid = [[EMPTY] * W for _ in range(H)]
        for y in range(H):
            for x in range(W):
                if x in (0, W - 1) or y in (0, H - 1) or (x % 2 == 0 and y % 2 == 0):
                    self.grid[y][x] = WALL
        safe = {(1, 1), (2, 1), (1, 2)}
        for y in range(1, H - 1):
            for x in range(1, W - 1):
                if self.grid[y][x] == EMPTY and (x, y) not in safe and self.rand.random() < 0.55:
                    self.grid[y][x] = BRICK

        bricks = [(x, y) for y in range(H) for x in range(W) if self.grid[y][x] == BRICK]
        if not bricks:                # tiny boards: make sure the door has a home
            x, y = max((x, y) for y in range(H) for x in range(W)
                       if self.grid[y][x] == EMPTY and (x, y) not in safe)
            self.grid[y][x] = BRICK
            bricks = [(x, y)]
        self.rand.shuffle(bricks)
        self.door = bricks.pop()
        self.door_revealed = False
        self.hidden_powerups = {}
        for _ in range(3):
            if bricks:
                self.hidden_powerups[bricks.pop()] = self.rand.choice(POWERUPS)
        self.powerups = {}            # revealed: (x, y) -> kind

        self.bombs = []
        self.fire = {}                # (x, y) -> expires_at
        self.px, self.py = 1, 1
        self.alive = True
        self.dead_until = 0.0
        self.won_level = False
        self.next_player_move = now
        self.next_enemy_move = now + 1.0

        self.enemies = []
        far = [(x, y) for y in range(H) for x in range(W)
               if self.grid[y][x] == EMPTY and x + y >= 8]
        self.rand.shuffle(far)
        for x, y in far[:min(len(far), 2 + self.level)]:
            e = Enemy(x, y)
            e.dir = self.rand.choice(DIRS)
            self.enemies.append(e)
        self.flash(f"Level {self.level}", now)

    def flash(self, text, now, secs=2.0):
        self.message, self.message_until = text, now + secs

    # ---- queries
    def bomb_at(self, x, y):
        for b in self.bombs:
            if b.x == x and b.y == y:
                return b
        return None

    def walkable(self, x, y, for_player=False):
        if self.grid[y][x] != EMPTY:
            return False
        b = self.bomb_at(x, y)
        if b and not (for_player and b.player_can_pass):
            return False
        return True

    # ---- player actions
    def move_player(self, dx, dy, now):
        if not self.alive or self.game_over or self.won_level or now < self.next_player_move:
            return
        nx, ny = self.px + dx, self.py + dy
        if not self.walkable(nx, ny, for_player=True):
            return
        self.px, self.py = nx, ny
        self.next_player_move = now + max(0.06, BASE_MOVE_DELAY - 0.025 * self.speed)
        for b in self.bombs:
            if (b.x, b.y) != (nx, ny):
                b.player_can_pass = False
        self.pickup(now)
        self.check_player_hazards(now)

    def drop_bomb(self, now):
        if not self.alive or self.game_over or self.won_level:
            return
        if len(self.bombs) >= self.max_bombs or self.bomb_at(self.px, self.py):
            return
        self.bombs.append(Bomb(self.px, self.py, now + FUSE, self.fire_range))

    def pickup(self, now):
        kind = self.powerups.pop((self.px, self.py), None)
        if kind == "bomb":
            self.max_bombs += 1
            self.flash("+1 Bomb!", now, 1.2)
        elif kind == "fire":
            self.fire_range += 1
            self.flash("+1 Flame range!", now, 1.2)
        elif kind == "speed":
            self.speed = min(self.speed + 1, 3)
            self.flash("Speed up!", now, 1.2)
        if kind:
            self.score += 50

    # ---- simulation
    def tick(self, now):
        if self.game_over:
            return
        if self.won_level:
            if now >= self.dead_until:
                self.level += 1
                self.new_level(now)
            return
        if not self.alive:
            if now >= self.dead_until:
                if self.lives > 0:
                    self.new_level(now)
                else:
                    self.game_over = True
            return

        # Explode due bombs (chain reactions handled inside explode()).
        for b in [b for b in self.bombs if now >= b.explode_at]:
            if b in self.bombs:
                self.explode(b, now)

        self.fire = {p: t for p, t in self.fire.items() if t > now}

        if now >= self.next_enemy_move:
            self.next_enemy_move = now + max(0.25, ENEMY_DELAY - 0.03 * (self.level - 1))
            self.move_enemies()

        self.check_enemy_fire()
        self.check_player_hazards(now)

        if self.alive and not self.enemies and (self.px, self.py) == self.door and self.door_revealed:
            self.won_level = True
            self.score += 500
            self.dead_until = now + 2.0
            self.flash("Level clear!", now)

    def explode(self, first, now):
        exposed = set(self.powerups)       # power-ups visible before this blast
        queue = [first]
        while queue:
            b = queue.pop()
            if b not in self.bombs:
                continue
            self.bombs.remove(b)
            cells = [(b.x, b.y)]
            for dx, dy in DIRS:
                for i in range(1, b.range + 1):
                    x, y = b.x + dx * i, b.y + dy * i
                    cell = self.grid[y][x]
                    if cell == WALL:
                        break
                    cells.append((x, y))
                    if cell == BRICK:
                        self.destroy_brick(x, y)
                        break
                    if self.bomb_at(x, y):
                        break   # that bomb will chain and continue the blast
            for p in cells:
                self.fire[p] = now + FLAME_TIME
                if p in exposed:            # fire burns already-visible power-ups
                    self.powerups.pop(p, None)
                other = self.bomb_at(*p)
                if other:
                    queue.append(other)

    def destroy_brick(self, x, y):
        self.grid[y][x] = EMPTY
        self.score += 10
        if (x, y) == self.door:
            self.door_revealed = True
        kind = self.hidden_powerups.pop((x, y), None)
        if kind:
            self.powerups[(x, y)] = kind

    def move_enemies(self):
        occupied = {(e.x, e.y) for e in self.enemies}
        for e in self.enemies:
            options = [d for d in DIRS if self.walkable(e.x + d[0], e.y + d[1])
                       and (e.x + d[0], e.y + d[1]) not in occupied]
            if not options:
                continue
            # Mostly keep going straight; sometimes turn at junctions.
            if e.dir not in options or self.rand.random() < 0.25:
                e.dir = self.rand.choice(options)
            occupied.discard((e.x, e.y))
            e.x += e.dir[0]
            e.y += e.dir[1]
            occupied.add((e.x, e.y))

    def check_enemy_fire(self):
        before = len(self.enemies)
        self.enemies = [e for e in self.enemies if (e.x, e.y) not in self.fire]
        killed = before - len(self.enemies)
        self.score += 100 * killed

    def check_player_hazards(self, now):
        if not self.alive:
            return
        hit = (self.px, self.py) in self.fire or any(
            (e.x, e.y) == (self.px, self.py) for e in self.enemies)
        if hit:
            self.alive = False
            self.lives -= 1
            self.dead_until = now + 2.0
            self.flash("Ouch! You died." if self.lives > 0 else "GAME OVER", now, 2.0)


# --------------------------------------------------------------- rendering --
C_WALL, C_BRICK, C_PLAYER, C_ENEMY, C_BOMB, C_FIRE, C_POWER, C_DOOR, C_HUD, C_FLOOR = range(1, 11)


def init_colors():
    if not curses.has_colors():
        return False
    curses.start_color()
    # Always draw on black so sprites stay visible on light-themed terminals.
    bg = curses.COLOR_BLACK
    curses.init_pair(C_WALL, curses.COLOR_WHITE, curses.COLOR_WHITE)
    curses.init_pair(C_BRICK, curses.COLOR_RED, curses.COLOR_YELLOW)
    curses.init_pair(C_PLAYER, curses.COLOR_CYAN, bg)
    curses.init_pair(C_ENEMY, curses.COLOR_MAGENTA, bg)
    curses.init_pair(C_BOMB, curses.COLOR_WHITE, bg)
    curses.init_pair(C_FIRE, curses.COLOR_YELLOW, curses.COLOR_RED)
    curses.init_pair(C_POWER, curses.COLOR_GREEN, bg)
    curses.init_pair(C_DOOR, curses.COLOR_BLUE, bg)
    curses.init_pair(C_HUD, curses.COLOR_YELLOW, bg)
    curses.init_pair(C_FLOOR, curses.COLOR_WHITE, bg)
    return True


def put(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass   # writing to the bottom-right cell raises; ignore


def text_width(s):
    """Terminal columns taken by s (wide emoji count as 2, joiners/selectors as 0)."""
    w, joined = 0, False
    for ch in s:
        if ch == "\ufe0f":            # emoji presentation: previous char renders wide
            w += 1 if w % 2 else 0
        elif ch == "\u200d":          # zero-width joiner: next glyph merges into this one
            joined = True
        elif unicodedata.combining(ch) or ch == "\ufe0e" or joined:
            joined = False
        else:
            w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def player_sprite(text):
    """Pad the player's symbol to exactly one 2-column cell."""
    w = text_width(text)
    if not 1 <= w <= 2:
        raise ValueError(f"player symbol {text!r} must be 1 or 2 columns wide (got {w})")
    return text + " " * (2 - w)


def draw(stdscr, g, now, color, paused, player):
    stdscr.erase()
    W, H = g.w, g.h
    rows, cols = stdscr.getmaxyx()
    need_w, need_h = W * 2, H + 3
    if cols < need_w or rows < need_h:
        put(stdscr, 0, 0, f"Terminal too small: need {need_w}x{need_h}, have {cols}x{rows}.")
        put(stdscr, 1, 0, "Please resize (Q to quit).")
        stdscr.refresh()
        return

    cp = (lambda n: curses.color_pair(n)) if color else (lambda n: 0)
    B = curses.A_BOLD
    ox = (cols - need_w) // 2
    put(stdscr, 0, ox, f"LV {g.level}  LIVES {g.lives}  BOMBS {g.max_bombs}  "
                      f"FIRE {g.fire_range}  SCORE {g.score}", cp(C_HUD) | B)

    enemies = {(e.x, e.y) for e in g.enemies}
    for y in range(H):
        for x in range(W):
            p = (x, y)
            cell = g.grid[y][x]
            if cell == WALL:
                s, a = "##", cp(C_WALL)
            elif cell == BRICK:
                s, a = "[]", cp(C_BRICK)
            elif p in g.fire:
                s, a = "**", cp(C_FIRE) | B
            elif p == (g.px, g.py) and (g.alive or int(now * 8) % 2):
                s, a = (player if g.alive else "xx"), cp(C_PLAYER) | B
            elif p in enemies:
                s, a = "&&", cp(C_ENEMY) | B
            elif g.bomb_at(x, y):
                b = g.bomb_at(x, y)
                s = "()" if (b.explode_at - now) > 0.8 or int(now * 10) % 2 else "OO"
                a = cp(C_BOMB) | B
            elif p in g.powerups:
                s, a = {"bomb": "+B", "fire": "+F", "speed": "+S"}[g.powerups[p]], cp(C_POWER) | B
            elif g.door_revealed and p == g.door:
                s, a = ("||" if g.enemies else "<>"), cp(C_DOOR) | B
            else:
                s, a = "  ", cp(C_FLOOR)
            put(stdscr, y + 1, ox + x * 2, s, a)

    status = ""
    if g.game_over:
        status = f"GAME OVER  -  score {g.score}  -  R to restart, Q to quit"
    elif paused:
        status = "PAUSED - press P to resume"
    elif now < g.message_until:
        status = g.message
    elif not g.enemies and g.door_revealed:
        status = "All enemies down - reach the exit <>!"
    elif not g.enemies:
        status = "All enemies down - find the hidden exit!"
    else:
        status = f"Enemies left: {len(g.enemies)}    arrows/WASD move  SPACE bomb  P pause  Q quit"
    put(stdscr, H + 1, max(0, (cols - len(status)) // 2), status[:cols - 1], cp(C_HUD) | B)
    stdscr.refresh()


KEYMAP = {
    curses.KEY_UP: (0, -1), curses.KEY_DOWN: (0, 1),
    curses.KEY_LEFT: (-1, 0), curses.KEY_RIGHT: (1, 0),
    ord("w"): (0, -1), ord("s"): (0, 1), ord("a"): (-1, 0), ord("d"): (1, 0),
    ord("W"): (0, -1), ord("S"): (0, 1), ord("A"): (-1, 0), ord("D"): (1, 0),
}


def main(stdscr, width, height, player):
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(True)
    color = init_colors()
    g = Game(now=time.monotonic(), width=width, height=height)
    paused = False
    pause_start = 0.0
    pending, pending_at = None, 0.0   # buffered direction so quick taps aren't lost

    while True:
        now = time.monotonic()
        bomb = False
        # Drain every queued key so held keys don't keep sliding after release.
        while True:
            k = stdscr.getch()
            if k == -1:
                break
            if k in (ord("q"), ord("Q")):
                return
            if k in (ord("p"), ord("P")) and not g.game_over:
                paused = not paused
                if paused:
                    pause_start = now
                else:
                    shift_time(g, now - pause_start)
            elif k in (ord("r"), ord("R")) and g.game_over:
                g = Game(now=now, width=width, height=height)
            elif k == ord(" "):
                bomb = True
            elif k in KEYMAP:
                pending, pending_at = KEYMAP[k], now

        if not paused:
            if bomb:
                g.drop_bomb(now)
            if pending and now - pending_at > 0.2:
                pending = None
            if pending and now >= g.next_player_move:
                g.move_player(*pending, now)
                pending = None
            g.tick(now)
        draw(stdscr, g, now, color, paused, player)
        curses.napms(30)


def shift_time(g, dt):
    """Push all timers forward so pausing doesn't advance the game."""
    for b in g.bombs:
        b.explode_at += dt
    g.fire = {p: t + dt for p, t in g.fire.items()}
    g.next_enemy_move += dt
    g.next_player_move += dt
    g.dead_until += dt
    g.message_until += dt


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Terminal Bomberman.")
    ap.add_argument("--width", type=int, default=DEFAULT_W,
                    help=f"board width in cells (min {MIN_SIZE}, default {DEFAULT_W})")
    ap.add_argument("--height", type=int, default=DEFAULT_H,
                    help=f"board height in cells (min {MIN_SIZE}, default {DEFAULT_H})")
    ap.add_argument("--player", default=DEFAULT_PLAYER,
                    help=f"emoji or 1-2 characters for the player (default {DEFAULT_PLAYER!r})")
    args = ap.parse_args(argv)
    for name in ("width", "height"):
        if getattr(args, name) < MIN_SIZE:
            ap.error(f"--{name} must be at least {MIN_SIZE}")
    try:
        args.player = player_sprite(args.player)
    except ValueError as e:
        ap.error(str(e))
    return args


if __name__ == "__main__":
    args = parse_args()
    locale.setlocale(locale.LC_ALL, "")   # needed for curses to draw emoji
    try:
        curses.wrapper(main, args.width, args.height, args.player)
    except KeyboardInterrupt:
        pass
