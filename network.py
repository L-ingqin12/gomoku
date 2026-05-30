"""Network game modes: host and join."""

import curses
import select
import socket
import time

from .constants import SIZE, EMPTY, BLACK, WHITE, DEFAULT_PORT
from .constants import PIECE_CH
from .game import find_win, is_full, new_board, screen_to_board, screen_to_button
from .kifu import Kifu
from .ui import draw, win_flash, endgame_loop


def recv_move(sock, timeout=0.1):
    ready, _, _ = select.select([sock], [], [], timeout)
    if ready:
        data = sock.recv(1024)
        if data:
            try:
                return tuple(map(int, data.decode().strip().split(',')))
            except Exception:
                return None
    return None


def send_move(sock, r, c):
    sock.sendall(f'{r},{c}'.encode())


def recv_all(sock, timeout=0.1):
    ready, _, _ = select.select([sock], [], [], timeout)
    if ready:
        return sock.recv(4096).decode()
    return None


# ── IP display ──────────────────────────────────────────────────────────

def _show_ip_screen(stdscr, port):
    socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = '?.?.?.?'
    rows, cols = stdscr.getmaxyx()
    stdscr.erase()
    for i, line in enumerate([
        'Waiting for opponent to connect...', '',
        f'  Your IP:   {ip}', f'  Port:      {port}', '',
        '  Press Q to cancel',
    ]):
        try:
            stdscr.addstr(rows // 2 - 3 + i, max(0, (cols - len(line)) // 2),
                          line, curses.A_BOLD)
        except curses.error:
            pass
    stdscr.refresh()
    return ip


def _show_join_screen(stdscr):
    curses.echo()
    curses.curs_set(1)
    rows, cols = stdscr.getmaxyx()
    ip = ''
    while True:
        stdscr.erase()
        msg = 'Enter host IP address: '
        stdscr.addstr(rows // 2, max(0, (cols - len(msg) - len(ip)) // 2), msg + ip)
        stdscr.refresh()
        k = stdscr.getch()
        if k in (10, 13):
            break
        if k in (27,):
            curses.noecho()
            curses.curs_set(0)
            return None
        if k in (curses.KEY_BACKSPACE, 127, 8):
            ip = ip[:-1]
        elif 32 <= k <= 126:
            ip += chr(k)
    curses.noecho()
    curses.curs_set(0)
    return ip.strip() or None


# ── host ────────────────────────────────────────────────────────────────

def run_host(stdscr):
    port = DEFAULT_PORT
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(1)
    server.setblocking(False)

    _show_ip_screen(stdscr, port)
    while True:
        k = stdscr.getch()
        if k in (ord('q'), ord('Q'), 27):
            server.close()
            return
        try:
            client, _ = server.accept()
            break
        except BlockingIOError:
            continue
    server.close()

    board = new_board()
    history = []
    cursor = (SIZE // 2, SIZE // 2)
    current = BLACK
    score = {BLACK: 0, WHITE: 0}
    msg = 'Connected! You are ● Black'
    win_cells = None
    my_turn = True
    kifu = Kifu('host', 'Network game - host (Black)')

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        status = 'Your turn' if my_turn else "Opponent's turn"
        bt, br = draw(pad, board, cursor, current, msg, cols,
                      win_cells=win_cells, score=score, status=status)
        msg = ''
        win_cells = None
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)

        if my_turn:
            key = stdscr.getch()
            if key == curses.KEY_MOUSE:
                move = _handle_mouse(stdscr, key, bt, br)
                if move:
                    r, c = move
                    if board[r][c] == EMPTY:
                        board[r][c] = BLACK
                        history.append((r, c, BLACK))
                        cursor = (r, c)
                        send_move(client, r, c)
                        kifu.record(r, c, BLACK)
                        result = _check_result(stdscr, board, cursor, BLACK,
                                               score, kifu, 'Black')
                        if result == 'win':
                            client.close()
                            if _restart_or_quit(stdscr, board, cursor, BLACK,
                                                find_win(board, r, c), score, kifu):
                                history.clear()
                                cursor = (SIZE // 2, SIZE // 2)
                                current = BLACK
                                msg = 'New game!'
                                my_turn = True
                                continue
                            else:
                                return
                        elif result == 'draw':
                            msg = 'Draw!'
                            continue
                        my_turn = False
                        continue
                continue
            if key in (ord('q'), ord('Q'), 27):
                client.close()
                kifu.save()
                return
            # Movement
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
                    board[r][c] = BLACK
                    history.append((r, c, BLACK))
                    send_move(client, r, c)
                    kifu.record(r, c, BLACK)
                    result = _check_result(stdscr, board, cursor, BLACK,
                                           score, kifu, 'Black')
                    if result == 'win':
                        client.close()
                        if _restart_or_quit(stdscr, board, cursor, BLACK,
                                            find_win(board, r, c), score, kifu):
                            history.clear()
                            cursor = (SIZE // 2, SIZE // 2)
                            current = BLACK
                            msg = 'New game!'
                            my_turn = True
                            continue
                        else:
                            return
                    elif result == 'draw':
                        msg = 'Draw!'
                        continue
                    my_turn = False
        else:
            move = recv_move(client, timeout=0.3)
            if move is not None:
                r, c = move
                if board[r][c] == EMPTY:
                    board[r][c] = WHITE
                    cursor = (r, c)
                    kifu.record(r, c, WHITE)
                    wc = find_win(board, r, c)
                    if wc:
                        score[WHITE] += 1
                        kifu.result = 'White wins'
                        kifu.score = score
                        kifu.save()
                        r2, c2 = stdscr.getmaxyx()
                        p2 = curses.newpad(r2 + 40, max(c2, 32))
                        win_flash(p2, board, cursor, WHITE, wc, score, c2, r2)
                        act = endgame_loop(stdscr, board, cursor, WHITE, wc, score, c2)
                        client.close()
                        if act == 'restart':
                            board = new_board()
                            history.clear()
                            cursor = (SIZE // 2, SIZE // 2)
                            current = BLACK
                            msg = 'New game!'
                            my_turn = True
                            kifu = Kifu('host')
                            continue
                        else:
                            return
                    my_turn = True
                    continue
            data = recv_all(client, timeout=0.05)
            if data == 'QUIT':
                msg = 'Opponent disconnected'
                client.close()
                time.sleep(1)
                return
            stdscr.nodelay(1)
            k = stdscr.getch()
            stdscr.nodelay(0)
            if k in (ord('q'), ord('Q'), 27):
                send_move(client, -1, -1)
                client.close()
                return


# ── join ────────────────────────────────────────────────────────────────

def run_join(stdscr):
    ip = _show_join_screen(stdscr)
    if not ip:
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect((ip, DEFAULT_PORT))
    except Exception as e:
        rows, cols = stdscr.getmaxyx()
        stdscr.erase()
        m = f'Could not connect: {e}'
        stdscr.addstr(rows // 2, max(0, (cols - len(m)) // 2), m)
        stdscr.refresh()
        time.sleep(2)
        return

    board = new_board()
    history = []
    cursor = (SIZE // 2, SIZE // 2)
    current = WHITE
    score = {BLACK: 0, WHITE: 0}
    msg = 'Connected! You are ○ White'
    win_cells = None
    my_turn = False
    kifu = Kifu('join', 'Network game - client (White)')

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        status = 'Your turn' if my_turn else "Opponent's turn"
        bt, br = draw(pad, board, cursor, current, msg, cols,
                      win_cells=win_cells, score=score, status=status)
        msg = ''
        win_cells = None
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)

        if my_turn:
            key = stdscr.getch()
            if key == curses.KEY_MOUSE:
                move = _handle_mouse(stdscr, key, bt, br)
                if move:
                    r, c = move
                    if board[r][c] == EMPTY:
                        board[r][c] = WHITE
                        history.append((r, c, WHITE))
                        cursor = (r, c)
                        send_move(sock, r, c)
                        kifu.record(r, c, WHITE)
                        result = _check_result(stdscr, board, cursor, WHITE,
                                               score, kifu, 'White')
                        if result == 'win':
                            sock.close()
                            if _restart_or_quit(stdscr, board, cursor, WHITE,
                                                find_win(board, r, c), score, kifu):
                                history.clear()
                                cursor = (SIZE // 2, SIZE // 2)
                                current = WHITE
                                msg = 'New game!'
                                my_turn = False
                                continue
                            else:
                                return
                        elif result == 'draw':
                            msg = 'Draw!'
                            continue
                        my_turn = False
                        continue
                continue
            if key in (ord('q'), ord('Q'), 27):
                sock.sendall(b'QUIT')
                sock.close()
                kifu.save()
                return
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
                    board[r][c] = WHITE
                    history.append((r, c, WHITE))
                    send_move(sock, r, c)
                    kifu.record(r, c, WHITE)
                    result = _check_result(stdscr, board, cursor, WHITE,
                                           score, kifu, 'White')
                    if result == 'win':
                        sock.close()
                        if _restart_or_quit(stdscr, board, cursor, WHITE,
                                            find_win(board, r, c), score, kifu):
                            history.clear()
                            cursor = (SIZE // 2, SIZE // 2)
                            current = WHITE
                            msg = 'New game!'
                            my_turn = False
                            continue
                        else:
                            return
                    elif result == 'draw':
                        msg = 'Draw!'
                        continue
                    my_turn = False
        else:
            move = recv_move(sock, timeout=0.3)
            if move is not None:
                r, c = move
                if r < 0:
                    msg = 'Opponent quit'
                    sock.close()
                    time.sleep(1)
                    return
                if board[r][c] == EMPTY:
                    board[r][c] = BLACK
                    cursor = (r, c)
                    kifu.record(r, c, BLACK)
                    wc = find_win(board, r, c)
                    if wc:
                        score[BLACK] += 1
                        kifu.result = 'Black wins'
                        kifu.score = score
                        kifu.save()
                        r2, c2 = stdscr.getmaxyx()
                        p2 = curses.newpad(r2 + 40, max(c2, 32))
                        win_flash(p2, board, cursor, BLACK, wc, score, c2, r2)
                        act = endgame_loop(stdscr, board, cursor, BLACK, wc, score, c2)
                        sock.close()
                        if act == 'restart':
                            board = new_board()
                            history.clear()
                            cursor = (SIZE // 2, SIZE // 2)
                            current = WHITE
                            msg = 'New game!'
                            my_turn = False
                            kifu = Kifu('join')
                            continue
                        else:
                            return
                    my_turn = True
                    continue
            data = recv_all(sock, timeout=0.05)
            if data == 'QUIT':
                msg = 'Opponent disconnected'
                sock.close()
                time.sleep(1)
                return
            stdscr.nodelay(1)
            k = stdscr.getch()
            stdscr.nodelay(0)
            if k in (ord('q'), ord('Q'), 27):
                sock.sendall(b'QUIT')
                sock.close()
                return


# ── shared helpers ──────────────────────────────────────────────────────

def _handle_mouse(stdscr, key, bt, br):
    """Parse a mouse click. Returns (r,c) board pos or None."""
    try:
        _, mx, my, _, bs = curses.getmouse()
    except Exception:
        return None
    if not (bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)):
        return None
    btn = screen_to_button(my, mx, br)
    if btn:
        return 'BTN_' + btn  # signal button press
    return screen_to_board(my, mx, bt)


def _check_result(stdscr, board, cursor, player, score, kifu, name):
    """Check for win/draw after a move. Returns 'win', 'draw', or None."""
    r, c = cursor
    if find_win(board, r, c):
        score[player] += 1
        kifu.result = f'{name} wins'
        kifu.score = score
        return 'win'
    if is_full(board):
        return 'draw'
    return None


def _restart_or_quit(stdscr, board, cursor, player, wc, score, kifu):
    """Show win animation + endgame loop. Returns True to restart."""
    kifu.save()
    r2, c2 = stdscr.getmaxyx()
    p2 = curses.newpad(r2 + 40, max(c2, 32))
    win_flash(p2, board, cursor, player, wc, score, c2, r2)
    act = endgame_loop(stdscr, board, cursor, player, wc, score, c2)
    return act == 'restart'
