"""Game modes: local, PvE, EvE, shared-file."""

import curses
import json
import os
import threading
import time

from .constants import SIZE, EMPTY, BLACK, WHITE, SHARED_FILE
from .constants import PIECE_CH, HLINE, CELL_W, LABEL_W
from .game import find_win, is_full, new_board, screen_to_board, screen_to_button
from .ai import GomokuAI
from .kifu import Kifu
from .ui import draw, win_flash, endgame_loop, show_message


# ═══════════════════════════ local ═══════════════════════════

def run_local(stdscr, initial=None):
    if initial:
        board = initial['board']
        history = initial.get('history', [])
        current = initial['current']
        score = {BLACK: initial['score'].get(str(BLACK), 0),
                 WHITE: initial['score'].get(str(WHITE), 0)}
        msg = 'Loaded!'
    else:
        board = new_board()
        history = []
        current = BLACK
        score = {BLACK: 0, WHITE: 0}
        msg = ''
    cursor = (SIZE // 2, SIZE // 2)
    win_cells = None
    kifu = Kifu('local', 'Two-player local game')

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        bt, br = draw(pad, board, cursor, current, msg, cols,
                      win_cells=win_cells, score=score)
        msg = ''
        win_cells = None
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        key = stdscr.getch()

        # Mouse
        if key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bs = curses.getmouse()
            except Exception:
                continue
            if not (bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)):
                continue
            btn = screen_to_button(my, mx, br)
            if btn == 'quit':
                kifu.result = 'quit'
                kifu.score = score
                kifu.save()
                return
            if btn == 'restart':
                kifu.save()
                board = new_board()
                history.clear()
                cursor = (SIZE // 2, SIZE // 2)
                current = BLACK
                msg = 'New game!'
                kifu = Kifu('local', 'Two-player local game')
                continue
            if btn == 'undo':
                if history:
                    r, c, prev = history.pop()
                    board[r][c] = EMPTY
                    current = prev
                    cursor = (r, c)
                    msg = 'Undone'
                else:
                    msg = 'Nothing to undo'
                continue
            if btn == 'save':
                _save(board, current, score, history)
                msg = 'Saved'
                continue
            pos = screen_to_board(my, mx, bt)
            if pos and board[pos[0]][pos[1]] == EMPTY:
                r, c = pos
                history.append((r, c, current))
                board[r][c] = current
                cursor = (r, c)
                kifu.record(r, c, current)
                wc = find_win(board, r, c)
                if wc:
                    score[current] += 1
                    winner = 'Black' if current == BLACK else 'White'
                    kifu.result = f'{winner} wins'
                    kifu.score = score
                    kifu.save()
                    r2, c2 = stdscr.getmaxyx()
                    p2 = curses.newpad(r2 + 40, max(c2, 32))
                    win_flash(p2, board, cursor, current, wc, score, c2, r2)
                    act = endgame_loop(stdscr, board, cursor, current, wc, score, c2)
                    if act == 'restart':
                        board = new_board()
                        history.clear()
                        cursor = (SIZE // 2, SIZE // 2)
                        current = BLACK
                        msg = 'New game!'
                        kifu = Kifu('local')
                        continue
                    else:
                        return
                elif is_full(board):
                    msg = 'Draw!'
                    continue
                else:
                    current = WHITE if current == BLACK else BLACK
            elif pos:
                cursor = pos
                msg = 'Occupied'
            continue

        # Keyboard
        if key in (ord('q'), ord('Q'), 27):
            kifu.save()
            return
        if key in (ord('r'), ord('R')):
            kifu.save()
            board = new_board()
            history.clear()
            cursor = (SIZE // 2, SIZE // 2)
            current = BLACK
            msg = 'New game!'
            kifu = Kifu('local')
            continue
        if key in (ord('u'), ord('U')):
            if history:
                r, c, prev = history.pop()
                board[r][c] = EMPTY
                current = prev
                cursor = (r, c)
                msg = 'Undone'
            else:
                msg = 'Nothing to undo'
            continue
        if key in (ord('s'), ord('S')):
            _save(board, current, score, history)
            msg = 'Saved'
            continue
        if key in (ord('w'), curses.KEY_UP) and cursor[0] > 0:
            cursor = (cursor[0] - 1, cursor[1])
        elif key in (ord('s'), curses.KEY_DOWN) and cursor[0] < SIZE - 1:
            cursor = (cursor[0] + 1, cursor[1])
        elif key in (ord('a'), curses.KEY_LEFT) and cursor[1] > 0:
            cursor = (cursor[0], cursor[1] - 1)
        elif key in (ord('d'), curses.KEY_RIGHT) and cursor[1] < SIZE - 1:
            cursor = (cursor[0], cursor[1] + 1)
        elif key in (curses.KEY_ENTER, 10, 13, ord(' ')):
            r, c = cursor
            if board[r][c] == EMPTY:
                history.append((r, c, current))
                board[r][c] = current
                kifu.record(r, c, current)
                wc = find_win(board, r, c)
                if wc:
                    score[current] += 1
                    winner = 'Black' if current == BLACK else 'White'
                    kifu.result = f'{winner} wins'
                    kifu.score = score
                    kifu.save()
                    r2, c2 = stdscr.getmaxyx()
                    p2 = curses.newpad(r2 + 40, max(c2, 32))
                    win_flash(p2, board, cursor, current, wc, score, c2, r2)
                    act = endgame_loop(stdscr, board, cursor, current, wc, score, c2)
                    if act == 'restart':
                        board = new_board()
                        history.clear()
                        cursor = (SIZE // 2, SIZE // 2)
                        current = BLACK
                        msg = 'New game!'
                        kifu = Kifu('local')
                        continue
                    else:
                        return
                elif is_full(board):
                    msg = 'Draw!'
                    continue
                else:
                    current = WHITE if current == BLACK else BLACK
            else:
                msg = 'Occupied'


# ═══════════════════════════ PvE ═══════════════════════════

def run_pve(stdscr):
    from .ui import show_pve_menu
    color_name, (diff_name, depth) = show_pve_menu(stdscr)
    if not color_name:
        return

    human_color = BLACK if color_name == 'Black' else WHITE
    ai_color = WHITE if human_color == BLACK else BLACK
    ai = GomokuAI(ai_color, depth)

    board = new_board()
    history = []
    cursor = (SIZE // 2, SIZE // 2)
    current = BLACK
    score = {BLACK: 0, WHITE: 0}
    msg = f'You: {color_name}  AI: {diff_name}'
    win_cells = None
    kifu = Kifu('pve', f'Human({color_name}) vs AI({diff_name}, depth {depth})')
    ai_result = [None]
    ai_thread = [None]

    def ai_worker(b):
        try:
            ai_result[0] = ai.get_move(b, time_limit=15)
        except Exception:
            ai_result[0] = None

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        status = 'Your turn' if current == human_color else 'AI thinking...'
        bt, br = draw(pad, board, cursor, current, msg, cols,
                      win_cells=win_cells, score=score, status=status)
        msg = ''
        win_cells = None

        if current == ai_color:
            pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
            ai_result[0] = None
            ai_thread[0] = threading.Thread(
                target=ai_worker, args=([row[:] for row in board],), daemon=True
            )
            ai_thread[0].start()

            # Poll for quit while AI thinks
            while ai_thread[0].is_alive():
                k = stdscr.getch()
                if k in (ord('q'), ord('Q'), 27):
                    ai.abort()
                    ai_thread[0].join(timeout=1)
                    kifu.result = 'quit'
                    kifu.score = score
                    kifu.save()
                    return
                ai_thread[0].join(timeout=0.1)

            move = ai_result[0]
            if move:
                r, c = move
                if board[r][c] == EMPTY:
                    board[r][c] = ai_color
                    cursor = (r, c)
                    kifu.record(r, c, ai_color)
                    wc = find_win(board, r, c)
                    if wc:
                        score[ai_color] += 1
                        kifu.result = 'AI wins'
                        kifu.score = score
                        kifu.save()
                        r2, c2 = stdscr.getmaxyx()
                        p2 = curses.newpad(r2 + 40, max(c2, 32))
                        win_flash(p2, board, cursor, ai_color, wc, score, c2, r2)
                        pch = PIECE_CH[ai_color]
                        m = f'{pch} AI WINS!  [R] Restart  [Q] Quit'
                        act = endgame_loop(stdscr, board, cursor, ai_color, wc, score, c2)
                        if act == 'restart':
                            board = new_board()
                            history.clear()
                            cursor = (SIZE // 2, SIZE // 2)
                            current = BLACK
                            msg = 'New game!'
                            kifu = Kifu('pve', f'Human({color_name}) vs AI({diff_name})')
                            continue
                        else:
                            return
                    elif is_full(board):
                        msg = 'Draw!'
                        continue
                    else:
                        current = human_color
            continue

        # Human turn
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        key = stdscr.getch()

        if key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bs = curses.getmouse()
            except Exception:
                continue
            if not (bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)):
                continue
            btn = screen_to_button(my, mx, br)
            if btn == 'quit':
                kifu.result = 'quit'
                kifu.score = score
                kifu.save()
                return
            if btn == 'restart':
                kifu.save()
                board = new_board()
                history.clear()
                cursor = (SIZE // 2, SIZE // 2)
                current = BLACK
                msg = 'New game!'
                kifu = Kifu('pve', f'Human({color_name}) vs AI({diff_name})')
                continue
            if btn == 'undo':
                if len(history) >= 2:
                    for _ in range(2):
                        r2, c2, p2 = history.pop()
                        board[r2][c2] = EMPTY
                    current = human_color
                    cursor = (r2, c2)
                    msg = 'Undone (2 moves)'
                elif history:
                    r2, c2, p2 = history.pop()
                    board[r2][c2] = EMPTY
                    current = human_color
                    cursor = (r2, c2)
                    msg = 'Undone'
                else:
                    msg = 'Nothing to undo'
                continue
            pos = screen_to_board(my, mx, bt)
            if pos and board[pos[0]][pos[1]] == EMPTY:
                r, c = pos
                history.append((r, c, human_color))
                board[r][c] = human_color
                cursor = (r, c)
                kifu.record(r, c, human_color)
                wc = find_win(board, r, c)
                if wc:
                    score[human_color] += 1
                    kifu.result = 'Human wins'
                    kifu.score = score
                    kifu.save()
                    r2, c2 = stdscr.getmaxyx()
                    p2 = curses.newpad(r2 + 40, max(c2, 32))
                    win_flash(p2, board, cursor, human_color, wc, score, c2, r2)
                    pch = PIECE_CH[human_color]
                    m = f'{pch} You WIN!  [R] Restart  [Q] Quit'
                    act = endgame_loop(stdscr, board, cursor, human_color, wc, score, c2)
                    if act == 'restart':
                        board = new_board()
                        history.clear()
                        cursor = (SIZE // 2, SIZE // 2)
                        current = BLACK
                        msg = 'New game!'
                        kifu = Kifu('pve', f'Human({color_name}) vs AI({diff_name})')
                        continue
                    else:
                        return
                elif is_full(board):
                    msg = 'Draw!'
                    continue
                else:
                    current = ai_color
            elif pos:
                cursor = pos
                msg = 'Occupied'
            continue

        if key in (ord('q'), ord('Q'), 27):
            kifu.save()
            return
        if key in (ord('r'), ord('R')):
            kifu.save()
            board = new_board()
            history.clear()
            cursor = (SIZE // 2, SIZE // 2)
            current = BLACK
            msg = 'New game!'
            kifu = Kifu('pve', f'Human({color_name}) vs AI({diff_name})')
            continue
        if key in (ord('w'), curses.KEY_UP) and cursor[0] > 0:
            cursor = (cursor[0] - 1, cursor[1])
        elif key in (ord('s'), curses.KEY_DOWN) and cursor[0] < SIZE - 1:
            cursor = (cursor[0] + 1, cursor[1])
        elif key in (ord('a'), curses.KEY_LEFT) and cursor[1] > 0:
            cursor = (cursor[0], cursor[1] - 1)
        elif key in (ord('d'), curses.KEY_RIGHT) and cursor[1] < SIZE - 1:
            cursor = (cursor[0], cursor[1] + 1)
        elif key in (curses.KEY_ENTER, 10, 13, ord(' ')):
            r, c = cursor
            if board[r][c] == EMPTY:
                history.append((r, c, human_color))
                board[r][c] = human_color
                kifu.record(r, c, human_color)
                wc = find_win(board, r, c)
                if wc:
                    score[human_color] += 1
                    kifu.result = 'Human wins'
                    kifu.score = score
                    kifu.save()
                    r2, c2 = stdscr.getmaxyx()
                    p2 = curses.newpad(r2 + 40, max(c2, 32))
                    win_flash(p2, board, cursor, human_color, wc, score, c2, r2)
                    pch = PIECE_CH[human_color]
                    m = f'{pch} You WIN!  [R] Restart  [Q] Quit'
                    act = endgame_loop(stdscr, board, cursor, human_color, wc, score, c2)
                    if act == 'restart':
                        board = new_board()
                        history.clear()
                        cursor = (SIZE // 2, SIZE // 2)
                        current = BLACK
                        msg = 'New game!'
                        kifu = Kifu('pve', f'Human({color_name}) vs AI({diff_name})')
                        continue
                    else:
                        return
                elif is_full(board):
                    msg = 'Draw!'
                    continue
                else:
                    current = ai_color
            else:
                msg = 'Occupied'


# ═══════════════════════════ EvE ═══════════════════════════

def run_eve(stdscr):
    from .ui import show_eve_menu
    b_depth, w_depth = show_eve_menu(stdscr)
    if not b_depth:
        return
    b_depth = min(b_depth, 6)
    w_depth = min(w_depth, 6)

    black_ai = GomokuAI(BLACK, b_depth)
    white_ai = GomokuAI(WHITE, w_depth)
    board = new_board()
    current = BLACK
    score = {BLACK: 0, WHITE: 0}
    msg = f'Q=QUIT | Black(d{b_depth}) vs White(d{w_depth})'
    win_cells = None
    cursor = (SIZE // 2, SIZE // 2)
    kifu = Kifu('eve', f'AI battle: Black(d{b_depth}) vs White(d{w_depth})')
    ai_result = [None]
    ai_thread = [None]

    def ai_worker(b, ai_obj):
        try:
            ai_result[0] = ai_obj.get_move(b, time_limit=12)
        except Exception:
            ai_result[0] = None

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        ai_obj = black_ai if current == BLACK else white_ai
        status = f'AI ({"Black" if current == BLACK else "White"}) thinking... Q=quit'
        draw(pad, board, cursor, current, msg, cols,
             win_cells=win_cells, score=score, status=status)
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        msg = ''
        win_cells = None

        # Run AI in thread, poll for quit
        ai_result[0] = None
        ai_thread[0] = threading.Thread(
            target=ai_worker, args=([row[:] for row in board], ai_obj), daemon=True
        )
        ai_thread[0].start()

        while ai_thread[0].is_alive():
            k = stdscr.getch()
            if k in (ord('q'), ord('Q'), 27):
                ai_obj.abort()
                ai_thread[0].join(timeout=1)
                kifu.result = 'quit'
                kifu.score = score
                kifu.save()
                return
            ai_thread[0].join(timeout=0.1)

        move = ai_result[0]
        if move:
            r, c = move
            if board[r][c] == EMPTY:
                board[r][c] = current
                cursor = (r, c)
                kifu.record(r, c, current)
                wc = find_win(board, r, c)
                if wc:
                    score[current] += 1
                    winner = 'Black AI' if current == BLACK else 'White AI'
                    kifu.result = f'{winner} wins'
                    kifu.score = score
                    kifu.save()
                    r2, c2 = stdscr.getmaxyx()
                    p2 = curses.newpad(r2 + 40, max(c2, 32))
                    win_flash(p2, board, cursor, current, wc, score, c2, r2)
                    pch = PIECE_CH[current]
                    m = f'{pch} {winner} WINS!  [R] Restart  [Q] Quit'
                    act = endgame_loop(stdscr, board, cursor, current, wc, score, c2)
                    if act == 'restart':
                        board = new_board()
                        cursor = (SIZE // 2, SIZE // 2)
                        current = BLACK
                        msg = 'New game!'
                        kifu = Kifu('eve', 'AI battle')
                        continue
                    else:
                        return
                elif is_full(board):
                    msg = 'Draw!'
                    continue
                else:
                    current = WHITE if current == BLACK else BLACK


# ═══════════════════════════ shared ═══════════════════════════

def _save_shared(board, current, score, history, black_uid, white_uid):
    data = {
        'board': board, 'current': current, 'score': score,
        'history': history, 'black_uid': black_uid, 'white_uid': white_uid,
    }
    tmp = SHARED_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.rename(tmp, SHARED_FILE)


def _load_shared():
    if not os.path.exists(SHARED_FILE):
        return None
    with open(SHARED_FILE) as f:
        return json.load(f)


def _wait_for_turn(stdscr, expected_current):
    while True:
        stdscr.nodelay(1)
        k = stdscr.getch()
        stdscr.nodelay(0)
        if k in (ord('q'), ord('Q'), 27):
            return None
        data = _load_shared()
        if data and data['current'] == expected_current:
            return data
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        pad.erase()
        pch = '●' if expected_current == BLACK else '○'
        pad.addstr(0, 0, f' Gomoku  {pch} Waiting for opponent...'.ljust(cols)[:cols - 1],
                   curses.A_BOLD | curses.color_pair(4))  # CP_CURSOR
        pad.addstr(2, 0, ' [Q] Quit')
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        time.sleep(0.5)


def run_shared(stdscr):
    my_uid = os.getuid()
    data = _load_shared()

    if data is None:
        board = new_board()
        history = []
        current = BLACK
        score = {BLACK: 0, WHITE: 0}
        my_color = BLACK
        black_uid = my_uid
        white_uid = None
        _save_shared(board, current, score, history, black_uid, white_uid)
        msg = 'New shared game! You are ● Black.'
    elif data['black_uid'] == my_uid:
        board = data['board']
        current = data['current']
        score = {BLACK: data['score'].get(str(BLACK), 0),
                 WHITE: data['score'].get(str(WHITE), 0)}
        history = data.get('history', [])
        my_color = BLACK
        black_uid = data['black_uid']
        white_uid = data.get('white_uid')
        msg = 'Welcome back! You are ● Black.'
    elif data.get('white_uid') is None:
        board = data['board']
        current = data['current']
        score = {BLACK: data['score'].get(str(BLACK), 0),
                 WHITE: data['score'].get(str(WHITE), 0)}
        history = data.get('history', [])
        my_color = WHITE
        black_uid = data['black_uid']
        white_uid = my_uid
        _save_shared(board, current, score, history, black_uid, white_uid)
        msg = 'Joined! You are ○ White.'
    elif data.get('white_uid') == my_uid:
        board = data['board']
        current = data['current']
        score = {BLACK: data['score'].get(str(BLACK), 0),
                 WHITE: data['score'].get(str(WHITE), 0)}
        history = data.get('history', [])
        my_color = WHITE
        black_uid = data['black_uid']
        white_uid = data['white_uid']
        msg = 'Welcome back! You are ○ White.'
    else:
        show_message(stdscr, 'Game is full (2 players already).')
        return

    cursor = (SIZE // 2, SIZE // 2)
    win_cells = None
    kifu = Kifu('shared', 'Shared file game')

    while True:
        data = _load_shared()
        if data is None:
            msg = 'Shared file deleted.'
            time.sleep(1)
            return
        current = data['current']
        score = {BLACK: data['score'].get(str(BLACK), 0),
                 WHITE: data['score'].get(str(WHITE), 0)}

        if current != my_color:
            data = _wait_for_turn(stdscr, my_color)
            if data is None:
                kifu.save()
                return
            board = data['board']
            current = data['current']
            score = {BLACK: data['score'].get(str(BLACK), 0),
                     WHITE: data['score'].get(str(WHITE), 0)}
            history = data.get('history', [])
            msg = "Opponent moved!"
            continue

        # Our turn
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        bt, br = draw(pad, board, cursor, my_color, msg, cols,
                      win_cells=win_cells, score=score, status='Your turn')
        msg = ''
        win_cells = None
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        key = stdscr.getch()

        if key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bs = curses.getmouse()
            except Exception:
                continue
            if not (bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)):
                continue
            btn = screen_to_button(my, mx, br)
            if btn == 'quit':
                kifu.save()
                return
            if btn == 'restart':
                if my_color == BLACK:
                    board = new_board()
                    history = []
                    cursor = (SIZE // 2, SIZE // 2)
                    _save_shared(board, BLACK, score, history, black_uid, white_uid)
                    msg = 'New game!'
                    kifu = Kifu('shared')
                    continue
                else:
                    msg = 'Only Black can restart'
                continue
            pos = screen_to_board(my, mx, bt)
            if pos and board[pos[0]][pos[1]] == EMPTY:
                r, c = pos
                history.append((r, c, my_color))
                board[r][c] = my_color
                cursor = (r, c)
                kifu.record(r, c, my_color)
                wc = find_win(board, r, c)
                if wc:
                    score[my_color] += 1
                    nxt = WHITE if my_color == BLACK else BLACK
                    _save_shared(board, nxt, score, history, black_uid, white_uid)
                    kifu.result = f'{"Black" if my_color == BLACK else "White"} wins'
                    kifu.save()
                    continue
                elif is_full(board):
                    msg = 'Draw!'
                    continue
                else:
                    nxt = WHITE if my_color == BLACK else BLACK
                    _save_shared(board, nxt, score, history, black_uid, white_uid)
                    msg = 'Move sent.'
                    continue
            elif pos:
                cursor = pos
                msg = 'Occupied'
            continue

        if key in (ord('q'), ord('Q'), 27):
            kifu.save()
            return
        if key in (ord('r'), ord('R')):
            if my_color == BLACK:
                board = new_board()
                history = []
                cursor = (SIZE // 2, SIZE // 2)
                _save_shared(board, BLACK, score, history, black_uid, white_uid)
                msg = 'New game!'
                kifu = Kifu('shared')
                continue
            else:
                msg = 'Only Black can restart'
            continue
        if key in (ord('w'), curses.KEY_UP) and cursor[0] > 0:
            cursor = (cursor[0] - 1, cursor[1])
        elif key in (ord('s'), curses.KEY_DOWN) and cursor[0] < SIZE - 1:
            cursor = (cursor[0] + 1, cursor[1])
        elif key in (ord('a'), curses.KEY_LEFT) and cursor[1] > 0:
            cursor = (cursor[0], cursor[1] - 1)
        elif key in (ord('d'), curses.KEY_RIGHT) and cursor[1] < SIZE - 1:
            cursor = (cursor[0], cursor[1] + 1)
        elif key in (curses.KEY_ENTER, 10, 13, ord(' ')):
            r, c = cursor
            if board[r][c] == EMPTY:
                history.append((r, c, my_color))
                board[r][c] = my_color
                kifu.record(r, c, my_color)
                wc = find_win(board, r, c)
                if wc:
                    score[my_color] += 1
                    nxt = WHITE if my_color == BLACK else BLACK
                    _save_shared(board, nxt, score, history, black_uid, white_uid)
                    kifu.result = f'{"Black" if my_color == BLACK else "White"} wins'
                    kifu.save()
                    continue
                elif is_full(board):
                    msg = 'Draw!'
                    continue
                else:
                    nxt = WHITE if my_color == BLACK else BLACK
                    _save_shared(board, nxt, score, history, black_uid, white_uid)
                    msg = 'Move sent.'
                    continue
            else:
                msg = 'Occupied'


# ── helpers ─────────────────────────────────────────────────────────────

def _save(board, current, score, history):
    from .constants import SAVE_FILE
    with open(SAVE_FILE, 'w') as f:
        json.dump({'board': board, 'current': current,
                    'score': score, 'history': history}, f)


def _load():
    from .constants import SAVE_FILE
    if not os.path.exists(SAVE_FILE):
        return None
    with open(SAVE_FILE) as f:
        return json.load(f)
