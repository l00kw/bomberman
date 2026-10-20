# Terminal Bomberman

A classic Bomberman game that runs in your terminal. Pure Python, no dependencies.

## Play

```
python3 bomberman.py
python3 bomberman.py --width 31 --height 15 --player 🐶
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--width` | 15 | Board width in cells (min 7) |
| `--height` | 13 | Board height in cells (min 7) |
| `--player` | 🐱 | Emoji or 1–2 characters for the player |

Odd board sizes look best (the pillars line up with the walls).

Requires Python 3 and a terminal at least 2×width columns and height+3 rows — 30×16 for the default board (macOS/Linux; on Windows install `windows-curses` first). Emoji need a UTF-8 locale and font.

## Controls

| Key | Action |
| --- | --- |
| Arrows / WASD | Move |
| Space | Drop bomb |
| P | Pause |
| R | Restart after game over |
| Q | Quit |

## Rules

- Blow up every enemy (`&&`), then find the exit door hidden under a brick (`[]`) to advance a level.
- Bombs explode after 2.5s; blasts stop at pillars (`##`), destroy the first brick they hit, and set off other bombs.
- Power-ups hide under bricks: `+B` extra bomb, `+F` longer blast, `+S` speed. Flames destroy exposed power-ups.
- You have 3 lives. Touching an enemy or a flame costs one.

## Contributing

See [ROADMAP.md](ROADMAP.md) for known issues and ideas for what to build next.
