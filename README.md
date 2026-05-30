# Gomoku (五子棋) — Terminal Curses Game

A feature-rich terminal-based Gomoku game with multiple game modes,
a strong AI engine, self-evolution capabilities, and network play.

**Python 3.12+ | curses | TCP networking | minimax + VCF AI**

---

## Quick Start

```bash
python3 run.py
# or
python3 -m gomoku
```

---

## Game Modes

| Key | Mode | Description |
|-----|------|-------------|
| `1` | Local Game | Two players, same screen |
| `2` | Host Game | TCP server, wait for opponent (port 9999) |
| `3` | Join Game | TCP client, connect to host IP |
| `4` | Shared Game | Two users, same machine, file-based turns (`/tmp/gomoku_shared.json`) |
| `5` | Player vs AI | Human vs computer, selectable color + difficulty |
| `6` | AI vs AI | Watch two AIs battle, selectable depths |
| `7` | Replay Kifu | Browse and step through saved game records |
| `L` | Load Game | Resume from `save.json` |

### Controls

| Input | Action |
|-------|--------|
| Mouse click / tap | Place piece on empty cell; move cursor on occupied cell |
| Arrow keys / WASD | Move cursor |
| Enter / Space | Place piece at cursor |
| `S` | Save game |
| `U` | Undo last move |
| `R` | Restart game |
| `Q` / Esc | Quit |

---

## Project Structure

```
gomoku/
  __init__.py         1 line   package marker
  __main__.py        72 lines  entry point, color init, menu dispatch
  constants.py       41 lines  shared constants (size, pieces, colors, paths)
  game.py            61 lines  board logic, win detection, coordinate mapping
  ui.py             251 lines  curses rendering, menus, win animation
  ai.py             374 lines  AI engine: minimax + VCF + pattern evaluation
  evolve.py         315 lines  self-evolution: opening book, self-play, tournaments
  kifu.py           180 lines  game record save/load + replay UI
  network.py        448 lines  TCP host/join with select()-based I/O
  modes.py          760 lines  local / PvE / EvE / shared game loops
  run.py             21 lines  thin entry wrapper
  data/                        persistent data directory
  kifu/                        auto-saved game records (JSON)
  tests/
    test_game.py     18 tests  board logic, win detection, coord mapping
    test_ai.py       18 tests  pattern scoring, blocking, VCF, variety
    test_kifu.py      5 tests  save/load/query kifu records
    test_evolve.py   13 tests  opening book, self-play, weight mutation
```

---

## AI Engine (`ai.py`)

### Architecture

```
get_move(board, time_limit)
  ├── Empty board fast-path → random near-center
  ├── Immediate win detection → play winning move
  ├── Block opponent win (five-in-row)
  ├── Block opponent live-4 / rush-4
  ├── VCF threat-space search → find forced win sequences
  ├── Block opponent VCF counter-play
  └── Iterative deepening minimax (depth 2→4→6→8)
       ├── Candidate generation (radius 3, top 60 by attack+1.25×defense)
       ├── Alpha-beta pruning with move ordering
       ├── Randomized selection (top-5 weighted in opening, top-3 near-ties)
       └── Evaluation noise ±40 to break symmetry
```

### Pattern Classification

| Pattern | Condition | Score | Meaning |
|---------|-----------|-------|---------|
| WIN | ≥5 consecutive | 100,000,000 | Game over |
| LIVE4 | 4 consecutive, both ends open | 10,000,000 | Unstoppable |
| RUSH4 | 4 consecutive, one end open | 2,500,000 | Must block |
| LIVE3 | 3 consecutive, both ends open | 100,000 | Threat |
| SLEEP3 | 3 consecutive, one end open | 20,000 | Potential |
| LIVE2 | 2 consecutive, both ends open | 1,000 | Building |
| SLEEP2 | 2 consecutive, one end open | 250 | Weak |

### VCF (Victory by Continuous Four)

Threat-space search that finds forced winning sequences:

1. Find all positions where AI can create a live-4 or live-3
2. Play each threat; opponent must defend
3. Check for double-threat (two live-4s, or live-4 + live-3) → win
4. Recurse up to depth 4, branching ≤8 opponent defenses × 5 follow-ups

### Search Parameters

| Difficulty | PvE Depth | EvE Depth | Candidates | Time Limit |
|------------|-----------|-----------|------------|------------|
| Easy | 4 | 2 | 60 | 15s / 12s |
| Medium | 6 | 4 | 60 | 15s / 12s |
| Hard | 8 | 6 | 60 | 15s / 12s |

Safety: 500K node limit, recursion depth ≤20, abort flag checked per 512 nodes.

---

## Self-Evolution (`evolve.py`)

### Opening Book

```
Board State → Move → (wins, total) → Win Rate
```

- Stores opening positions (≤8 moves) with move statistics
- Queries best move by win rate with `min_samples` threshold
- Persisted to JSON, accumulates across sessions
- Built from both human games (kifu) and self-play

### Weight Tuning

14 tunable parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `defense_mult` | 1.15 | Opponent pattern weight multiplier |
| `center_bonus` | 50 | Bonus for center control in opening |
| `noise_range` | 40 | Random noise in board evaluation |
| `candidate_noise` | 30 | Noise on move scores during search |
| `live4_score` | 10,000,000 | Live-four pattern value |
| `rush4_score` | 2,500,000 | Rush-four pattern value |
| `live3_score` | 100,000 | Live-three pattern value |
| `sleep3_score` | 20,000 | Sleep-three pattern value |
| `live2_score` | 1,000 | Live-two pattern value |
| `sleep2_score` | 250 | Sleep-two pattern value |
| `vcf_depth` | 4 | VCF search max depth |
| `vcf_opp_depth` | 3 | Opponent VCF search depth |
| `candidate_df_mult` | 1.25 | Defense weight in candidate scoring |

### Mutation

```python
mutate_weights(weights, rate=0.1, scale=0.2)
```

- Each weight has `rate` probability of mutation
- Mutation multiplies by random factor in [0.8, 1.2] (scale=0.2)
- Clamped within [0.5×, 2.0×] of original value

### Tournament

```
run_tournament(population, games_per_match=2, depth=2)
```

- Round-robin between weight configurations
- Colors alternated for fairness
- Returns winner name, all scores, total games

---

## Kifu (棋谱) System (`kifu.py`)

Game records auto-saved to `kifu/` directory as JSON:

```json
{
  "mode": "pve",
  "info": "Human(Black) vs AI(Hard, depth 8)",
  "moves": [[7, 7, 1, 0.5], [7, 8, 2, 1.2], ...],
  "result": "AI wins",
  "score": {"1": 0, "2": 3}
}
```

Replay mode (menu `7`): browse files, step through moves with ← → keys,
jump to start/end, highlight last move.

---

## Network Play (`network.py`)

```
Host:  python3 run.py → 2 → shows IP + port
Join:  python3 run.py → 3 → enter host IP
```

- TCP on port 9999
- `select()`-based non-blocking I/O
- Move protocol: `"row,col"` text messages
- Disconnect detection with `QUIT` signal
- Kifu auto-saved for network games

---

## Shared Mode (`modes.py` → `run_shared`)

Two users on the same machine:

1. Both run `python3 run.py → 4`
2. First user creates game (Black), second joins (White)
3. Moves saved atomically to `/tmp/gomoku_shared.json`
4. Each side polls file every 0.5s when waiting

File locking via atomic `rename()` of temp file.

---

## Running Tests

```bash
# Run all 54 tests
python3 -m unittest discover -s tests -v

# Run specific test file
python3 -m unittest tests.test_ai -v

# Run single test
python3 -m unittest tests.test_ai.TestAIBlocking.test_immediate_win -v
```

---

## Requirements

- Python 3.8+
- Unix-like OS (Linux, macOS, WSL, Termux)
- Terminal with color + mouse support (most modern terminals)
- Network mode: open port 9999

No external pip packages required — stdlib only.

---

## Git History

| Commit | Description |
|--------|-------------|
| `3e9117d` | TDD test suite (54 cases) + AI self-evolution (opening book, self-play, tournament) |
| `97230c3` | Refactor: 1475-line monolith → 10-module package |
| `1e3bcee` | Thread-based quit fix + kifu replay + AI v2 (VCF threat search + pattern DB) |
| `fb8b950` | Abort responsiveness + move randomization |
| `150d5a6` | AI opening variety (random center 3×3, weighted top-5) |
| `1b657c0` | Initial commit: complete terminal Gomoku game |
