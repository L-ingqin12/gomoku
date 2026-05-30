"""Kifu (棋谱) — game record, save/load, and replay."""

import curses
import json
import os
import time

from .constants import SIZE, EMPTY, BLACK, WHITE, KIFU_DIR
from .constants import PIECE_CH, HLINE, CELL_W, LABEL_W
from .constants import CP_BOARD, CP_BLACK, CP_WHITE, CP_CURSOR, CP_BUTTON
from .game import new_board

os.makedirs(KIFU_DIR, exist_ok=True)


class Kifu:
    """Game record with auto-save."""

    def __init__(self, mode='local', info=''):
        self.mode = mode
        self.info = info
        self.moves = []          # list of (r, c, player, seconds)
        self.result = ''
        self.score = {BLACK: 0, WHITE: 0}
        self.started = time.time()

    def record(self, r, c, player):
        self.moves.append((r, c, player, time.time() - self.started))

    def save(self):
        ts = time.strftime('%Y%m%d_%H%M%S')
        fname = os.path.join(KIFU_DIR, f'kifu_{ts}.json')
        data = {
            'mode': self.mode, 'info': self.info, 'moves': self.moves,
            'result': self.result, 'score': self.score,
        }
        with open(fname, 'w') as f:
            json.dump(data, f, indent=2)
        return fname

    @staticmethod
    def load(fname):
        with open(fname) as f:
            data = json.load(f)
        k = Kifu(data.get('mode', '?'), data.get('info', ''))
        k.moves = data['moves']
        k.result = data.get('result', '')
        k.score = data.get('score', {BLACK: 0, WHITE: 0})
        return k

    @staticmethod
    def list_files():
        if not os.path.exists(KIFU_DIR):
            return []
        files = sorted(os.listdir(KIFU_DIR), reverse=True)
        return [os.path.join(KIFU_DIR, f) for f in files if f.endswith('.json')]


# ── replay ──────────────────────────────────────────────────────────────

def run_replay(stdscr):
    """Replay mode: browse and step through saved kifu files."""
    files = Kifu.list_files()
    if not files:
        _message(stdscr, 'No kifu files found. Play a game first!')
        return

    # File selector
    idx = 0
    while True:
        rows, cols = stdscr.getmaxyx()
        stdscr.erase()
        m = 'Select kifu (arrows move, Enter select, Q back):'
        stdscr.addstr(0, max(0, (cols - len(m)) // 2), m, curses.A_BOLD)
        for i, f in enumerate(files[: min(20, len(files))]):
            name = os.path.basename(f).replace('.json', '').replace('kifu_', '')
            style = curses.A_REVERSE if i == idx else curses.A_NORMAL
            try:
                stdscr.addstr(2 + i, max(0, (cols - len(name)) // 2), name, style)
            except curses.error:
                pass
        stdscr.refresh()
        k = stdscr.getch()
        if k == curses.KEY_UP and idx > 0:
            idx -= 1
        elif k == curses.KEY_DOWN and idx < len(files) - 1:
            idx += 1
        elif k in (10, 13):
            _replay_file(stdscr, Kifu.load(files[idx]))
            return
        elif k in (ord('q'), ord('Q'), 27):
            return


def _replay_file(stdscr, kifu):
    """Step through a kifu record."""
    board = new_board()
    step = 0
    total = len(kifu.moves)

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        pad.erase()
        y = 0
        title = f' Replay: {kifu.info}  [{step}/{total}]  arrows=nav  Q=quit'
        pad.addstr(y, 0, title.ljust(cols)[:cols - 1], curses.A_BOLD)
        y += 2

        # Render board
        for r in range(SIZE):
            label = f'{chr(ord("A") + r)} '
            pad.addstr(y, 0, label[:cols - 1])
            x = LABEL_W
            for c in range(SIZE):
                ch = PIECE_CH[board[r][c]]
                cell = ch if c == SIZE - 1 else ch + HLINE
                # Highlight last shown move
                if step > 0 and (r, c) == (kifu.moves[step - 1][0], kifu.moves[step - 1][1]):
                    style = curses.color_pair(CP_CURSOR) | curses.A_BOLD
                elif board[r][c] == BLACK:
                    style = curses.color_pair(CP_BLACK) | curses.A_BOLD
                elif board[r][c] == WHITE:
                    style = curses.color_pair(CP_WHITE) | curses.A_BOLD
                else:
                    style = curses.color_pair(CP_BOARD)
                try:
                    pad.addstr(y, x, cell[:cols - x], style)
                except curses.error:
                    pass
                x += CELL_W
            y += 1

        y += 1
        if step < total:
            mr, mc, mp, _ = kifu.moves[step]
            pn = 'Black' if mp == BLACK else 'White'
            pad.addstr(y, 0, f' Next: {PIECE_CH[mp]} {pn} -> {chr(ord("A") + mr)}{mc + 1}'.ljust(cols)[:cols - 1],
                       curses.A_DIM)
        else:
            pad.addstr(y, 0, f' End: {kifu.result}'.ljust(cols)[:cols - 1], curses.A_BOLD)
        y += 2
        hint = ' [<-] Back  [->] Forward  [0] Start  [$] End  [R] Reset  [Q] Quit'
        pad.addstr(y, 0, hint.ljust(cols)[:cols - 1], curses.color_pair(CP_BUTTON))
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)

        k = stdscr.getch()
        if k in (ord('q'), ord('Q'), 27):
            return
        if k in (curses.KEY_LEFT, ord('a')) and step > 0:
            step -= 1
            r, c, p, _ = kifu.moves[step]
            board[r][c] = EMPTY
        elif k in (curses.KEY_RIGHT, ord('d')) and step < total:
            r, c, p, _ = kifu.moves[step]
            board[r][c] = p
            step += 1
        elif k in (ord('r'), ord('R'), ord('0'), curses.KEY_HOME):
            # Reset to start
            for i in range(SIZE):
                for j in range(SIZE):
                    board[i][j] = EMPTY
            step = 0
        elif k in (ord('$'), curses.KEY_END):
            # Jump to end
            for i in range(SIZE):
                for j in range(SIZE):
                    board[i][j] = EMPTY
            for i, (r, c, p, _) in enumerate(kifu.moves):
                board[r][c] = p
            step = total


def _message(stdscr, text, duration=2):
    """Show a centered message briefly."""
    rows, cols = stdscr.getmaxyx()
    stdscr.erase()
    stdscr.addstr(rows // 2, max(0, (cols - len(text)) // 2), text, curses.A_BOLD)
    stdscr.refresh()
    time.sleep(duration)
