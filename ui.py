"""Curses UI: board rendering, menus, win animation, endgame loop."""

import curses
import time

from .constants import SIZE, EMPTY, BLACK, WHITE
from .constants import PIECE_CH, HLINE, CELL_W, LABEL_W
from .constants import CP_BOARD, CP_BLACK, CP_WHITE, CP_CURSOR, CP_BUTTON, CP_WIN, CP_MENU
from .constants import BTN_TEXT
from .game import screen_to_button


# ── board rendering ─────────────────────────────────────────────────────

def draw(pad, board, cursor, current, msg, cols,
         win_cells=None, score=None, status=''):
    """Render the full game UI to a curses pad. Returns (board_top, btn_row)."""
    pad.erase()
    y = 0

    # Title
    pch = PIECE_CH[current]
    pname = 'Black' if current == BLACK else 'White'
    title = f' Gomoku    {pch} {pname}'
    if score:
        title += f'      Score:  ● {score[BLACK]}  -  ○ {score[WHITE]}'
    if status:
        title += f'    {status}'
    pad.addstr(y, 0, title[:cols - 1], curses.A_BOLD)
    y += 1

    # Hint
    pad.addstr(y, 0, ' [Click/Space] Place  [WASD] Move  [S] Save  [U] Undo  [Q] Quit'[:cols - 1],
               curses.A_DIM)
    y += 2

    board_top = y

    # Board
    for r in range(SIZE):
        label = f'{chr(ord("A") + r)} '
        pad.addstr(y, 0, label[:cols - 1])
        x = LABEL_W
        for c in range(SIZE):
            ch = PIECE_CH[board[r][c]]
            cell = ch if c == SIZE - 1 else ch + HLINE

            if win_cells and (r, c) in win_cells:
                style = curses.color_pair(CP_WIN) | curses.A_BOLD
            elif (r, c) == cursor:
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
    btn_row = y
    pad.addstr(y, 0, BTN_TEXT[:cols - 1], curses.color_pair(CP_BUTTON))
    y += 1

    if msg:
        y += 1
        pad.addstr(y, 0, ' ' + msg[:cols - 2], curses.A_BOLD)

    return board_top, btn_row


# ── win animation ───────────────────────────────────────────────────────

def win_flash(pad, board, cursor, current, win_cells, score, cols, rows):
    """Flash winning cells with alternating highlight."""
    for i in range(6):
        wc = win_cells if i % 2 == 0 else None
        draw(pad, board, cursor, current, '', cols, win_cells=wc, score=score)
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        time.sleep(0.15)
    pch = PIECE_CH[current]
    winner = 'Black' if current == BLACK else 'White'
    msg = f' {pch} {pch} {pch}  {winner} WINS!  {pch} {pch} {pch}'
    _, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score)
    pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
    return br


# ── endgame loop ────────────────────────────────────────────────────────

def endgame_loop(stdscr, board, cursor, current, win_cells, score, cols):
    """Wait for restart or quit after game over."""
    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        pch = PIECE_CH[current]
        winner = 'Black' if current == BLACK else 'White'
        m = f'{pch} {winner} WINS!  ● {score[BLACK]} - ○ {score[WHITE]}   [Restart] or [Quit]'
        _, br = draw(pad, board, cursor, current, m, cols, win_cells=win_cells, score=score)
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        k = stdscr.getch()
        if k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bs = curses.getmouse()
                if bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                    b = screen_to_button(my, mx, br)
                    if b == 'restart':
                        return 'restart'
                    if b == 'quit':
                        return 'quit'
            except Exception:
                pass
        elif k in (ord('r'), ord('R')):
            return 'restart'
        elif k in (ord('q'), ord('Q'), 27):
            return 'quit'


# ── menus ───────────────────────────────────────────────────────────────

def show_menu(stdscr):
    """Main menu: returns 'local', 'host', 'join', 'shared', 'pve', 'eve', 'replay', 'load', 'quit'."""
    rows, cols = stdscr.getmaxyx()
    menu = [
        '╔══════════════════════════╗', '║       GOMOKU 五子棋      ║',
        '╠══════════════════════════╣', '║  1. Local game          ║',
        '║  2. Host game (server)  ║', '║  3. Join game (client)  ║',
        '║  4. Shared (same-PC)    ║', '║  5. Player vs AI        ║',
        '║  6. AI vs AI            ║', '║  7. Replay kifu         ║',
        '║  L. Load saved game     ║', '║  Q. Quit                ║',
        '╚══════════════════════════╝',
    ]
    while True:
        stdscr.erase()
        y = max(0, (rows - len(menu)) // 2)
        x = max(0, (cols - 28) // 2)
        for i, line in enumerate(menu):
            try:
                stdscr.addstr(y + i, x, line, curses.color_pair(CP_MENU) | curses.A_BOLD)
            except curses.error:
                pass
        stdscr.refresh()
        k = stdscr.getch()
        if k in (ord('1'),): return 'local'
        if k in (ord('2'),): return 'host'
        if k in (ord('3'),): return 'join'
        if k in (ord('4'),): return 'shared'
        if k in (ord('5'),): return 'pve'
        if k in (ord('6'),): return 'eve'
        if k in (ord('7'),): return 'replay'
        if k in (ord('l'), ord('L')): return 'load'
        if k in (ord('q'), ord('Q'), 27): return 'quit'


def show_pve_menu(stdscr):
    """PvE submenu: returns (color_name, (diff_name, depth)) or (None, None)."""
    rows, cols = stdscr.getmaxyx()
    menu = [
        '╔══════════════════════════╗', '║     Player vs AI         ║',
        '╠══════════════════════════╣', '║  Choose your color:      ║',
        '║    B. Black (first)      ║', '║    W. White (second)     ║',
        '║                          ║', '║  Choose difficulty:      ║',
        '║    1. Easy   (depth 4)   ║', '║    2. Medium (depth 6)   ║',
        '║    3. Hard   (depth 8)   ║', '║                          ║',
        '║  Q. Back                 ║', '╚══════════════════════════╝',
    ]
    color_choice = None
    diff_choice = None
    while True:
        stdscr.erase()
        y = max(0, (rows - len(menu)) // 2)
        x = max(0, (cols - 28) // 2)
        for i, line in enumerate(menu):
            try:
                stdscr.addstr(y + i, x, line, curses.color_pair(CP_MENU))
            except curses.error:
                pass
        sel = ''
        if color_choice: sel += f'Color: {color_choice}  '
        if diff_choice: sel += f'Difficulty: {diff_choice}'
        if sel:
            try:
                stdscr.addstr(y + len(menu), x, sel[:cols - x], curses.A_BOLD)
            except curses.error:
                pass
        stdscr.refresh()
        k = stdscr.getch()
        if k in (ord('b'), ord('B')): color_choice = 'Black'
        if k in (ord('w'), ord('W')): color_choice = 'White'
        if k in (ord('1'),): diff_choice = ('Easy', 4)
        if k in (ord('2'),): diff_choice = ('Medium', 6)
        if k in (ord('3'),): diff_choice = ('Hard', 8)
        if k in (ord('q'), ord('Q'), 27): return None, None
        if color_choice and diff_choice and k in (10, 13):
            return color_choice, diff_choice


def show_eve_menu(stdscr):
    """EvE submenu: returns (b_depth, w_depth) or (None, None)."""
    rows, cols = stdscr.getmaxyx()
    menu = [
        '╔══════════════════════════╗', '║       AI vs AI           ║',
        '╠══════════════════════════╣', '║  Black AI difficulty:    ║',
        '║    1. Easy   (depth 2)   ║', '║    2. Medium (depth 4)   ║',
        '║    3. Hard   (depth 6)   ║', '║                          ║',
        '║  White AI difficulty:    ║', '║    4. Easy   (depth 2)   ║',
        '║    5. Medium (depth 4)   ║', '║    6. Hard   (depth 6)   ║',
        '║  Enter = Start           ║', '║  Q. Back                 ║',
        '╚══════════════════════════╝',
    ]
    b_depth, w_depth = 4, 4
    b_label, w_label = 'Medium', 'Medium'
    while True:
        stdscr.erase()
        y = max(0, (rows - len(menu)) // 2)
        x = max(0, (cols - 28) // 2)
        for i, line in enumerate(menu):
            try:
                stdscr.addstr(y + i, x, line, curses.color_pair(CP_MENU))
            except curses.error:
                pass
        info = f'Black={b_label}  White={w_label}'
        try:
            stdscr.addstr(y + len(menu), x, info[:cols - x], curses.A_BOLD)
        except curses.error:
            pass
        stdscr.refresh()
        k = stdscr.getch()
        if k in (ord('1'),): b_depth, b_label = 2, 'Easy'
        if k in (ord('2'),): b_depth, b_label = 4, 'Medium'
        if k in (ord('3'),): b_depth, b_label = 6, 'Hard'
        if k in (ord('4'),): w_depth, w_label = 2, 'Easy'
        if k in (ord('5'),): w_depth, w_label = 4, 'Medium'
        if k in (ord('6'),): w_depth, w_label = 6, 'Hard'
        if k in (ord('q'), ord('Q'), 27): return None, None
        if k in (10, 13): return b_depth, w_depth


def show_message(stdscr, text, duration=2):
    """Display a centered message briefly."""
    rows, cols = stdscr.getmaxyx()
    stdscr.erase()
    stdscr.addstr(rows // 2, max(0, (cols - len(text)) // 2), text, curses.A_BOLD)
    stdscr.refresh()
    time.sleep(duration)
