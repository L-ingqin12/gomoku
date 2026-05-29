#!/usr/bin/env python3
"""
Gomoku (五子棋) — curses edition.
Local / Network / Shared-file / PvE / EvE modes.

Menu:
  1. Local game        — two players, same screen
  2. Host game         — wait for opponent (network)
  3. Join game         — connect to host (network)
  4. Shared game       — two users, same machine (file-based)
  5. Player vs AI      — you vs computer
  6. AI vs AI          — watch two AIs battle
  L. Load saved game
  Q. Quit
"""

import curses
import json
import os
import random
import select
import socket
import time

SAVE_FILE = os.path.expanduser('~/.gomoku_save.json')
SHARED_FILE = '/tmp/gomoku_shared.json'
DEFAULT_PORT = 9999

SIZE = 15
EMPTY = 0
BLACK = 1
WHITE = 2

PIECE_CH = {EMPTY: '┼', BLACK: '●', WHITE: '○'}
HLINE = '─'

DIRS = [(0, 1), (1, 0), (1, 1), (1, -1)]

# Color pairs
CP_BOARD = 1
CP_BLACK = 2
CP_WHITE = 3
CP_CURSOR = 4
CP_BUTTON = 5
CP_WIN = 6
CP_MENU = 7

CELL_W = 2
LABEL_W = 2

BTN_TEXT = ' [Quit]  [Restart]  [Undo]  [Save]'
BTN_MAP = {'quit': (1, 6), 'restart': (9, 18), 'undo': (21, 27), 'save': (30, 36)}


# ═══════════════════════════════════════════════════════════════════════════════
# AI engine
# ═══════════════════════════════════════════════════════════════════════════════

# Pattern scores
WIN_SCORE = 100000000
OPEN_FOUR = 10000000
CLOSED_FOUR = 1000000
OPEN_THREE = 100000
CLOSED_THREE = 10000
OPEN_TWO = 1000
CLOSED_TWO = 100
OPEN_ONE = 10


class GomokuAI:
    """Strong minimax AI with full-board pattern evaluation and iterative deepening."""

    def __init__(self, color, depth=6):
        self.color = color
        self.opponent = WHITE if color == BLACK else BLACK
        self.max_depth = max(2, depth)
        self.nodes = 0
        self.abort = None
        self.deadline = 0
        self.max_nodes = 500000
        self.temperature = 0.15   # 0 = deterministic, higher = more variety
        self.opening_moves = 6    # first N moves use more randomness

    def get_move(self, board, abort_fn=None, time_limit=0):
        self.nodes = 0
        self.abort = abort_fn
        self.deadline = time.time() + time_limit if time_limit > 0 else float('inf')

        # Count how many pieces are on the board
        piece_count = sum(1 for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY)

        # Fast path: empty board → random near-center opening
        if piece_count == 0:
            # Pick randomly from center 3×3 area for variety
            centers = [(SIZE//2 + dr, SIZE//2 + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
            return random.choice(centers)

        # Fast path: only 1 piece → play near it, with some randomness
        if piece_count == 1:
            candidates = self._candidate_moves(board)
            if candidates:
                # Pick randomly from top 5 candidates
                scored = []
                for r, c in candidates:
                    s = self._move_attack(board, r, c, self.color) + self._move_attack(board, r, c, self.opponent) * 1.2
                    scored.append((s, (r, c)))
                scored.sort(reverse=True)
                top = scored[:min(5, len(scored))]
                return random.choice(top)[1]

        candidates = self._candidate_moves(board)
        if not candidates:
            return (SIZE // 2, SIZE // 2)

        # 1) Immediate win
        for r, c in candidates:
            board[r][c] = self.color
            if self._is_win_at(board, r, c, self.color):
                board[r][c] = EMPTY
                return (r, c)
            board[r][c] = EMPTY

        # 2) Block opponent's one-move win
        must_block = []
        for r, c in candidates:
            board[r][c] = self.opponent
            if self._is_win_at(board, r, c, self.opponent):
                must_block.append((r, c))
            board[r][c] = EMPTY
        if len(must_block) == 1:
            return must_block[0]

        # 3) Also block opponent's open-four threats
        for r, c in candidates:
            board[r][c] = self.opponent
            if self._has_open_four(board, r, c, self.opponent):
                if (r, c) not in must_block:
                    must_block.append((r, c))
            board[r][c] = EMPTY

        # 4) Iterative deepening search
        best_move = candidates[0]
        best_score = -float('inf')
        move_scores = {}   # track scores for all moves for randomized selection

        in_opening = piece_count < self.opening_moves

        for d in range(2, self.max_depth + 1, 2):
            if self._should_abort():
                break
            alpha = -float('inf')
            beta = float('inf')
            if best_move in candidates:
                candidates.remove(best_move)
                candidates.insert(0, best_move)

            for r, c in candidates:
                if self._should_abort():
                    break
                board[r][c] = self.color
                if self._is_win_at(board, r, c, self.color):
                    board[r][c] = EMPTY
                    return (r, c)
                score = self._minimax(board, d - 1, alpha, beta, False)
                board[r][c] = EMPTY
                # Add small noise to break ties and add variety
                score += random.uniform(-50, 50)
                move_scores[(r, c)] = score
                if score > best_score:
                    best_score = score
                    best_move = (r, c)
                alpha = max(alpha, score)

            if best_score >= WIN_SCORE // 2:
                break

        # Randomized selection: in opening, pick from top N; always add noise
        if move_scores:
            scored = sorted(move_scores.items(), key=lambda x: x[1], reverse=True)
            if in_opening:
                # Opening: pick randomly from top 5 with weighted probability
                top_n = min(5, len(scored))
                top = scored[:top_n]
                # Softmax-like: higher scores get higher probability
                if top[0][1] > 0:
                    total = sum(s for _, s in top)
                    weights = [s / total for _, s in top]
                else:
                    weights = None
                best_move = random.choices([m for m, _ in top], weights=weights, k=1)[0]
            else:
                # Mid/late game: pick from top 3 if scores are close (noise already applied)
                if len(scored) >= 2 and abs(scored[0][1] - scored[1][1]) < 200:
                    top_n = min(3, len(scored))
                    best_move = random.choice(scored[:top_n])[0]
                else:
                    best_move = scored[0][0]

        return best_move

    def _candidate_moves(self, board):
        """Return candidate moves near existing pieces, sorted by heuristic value."""
        has = any(board[r][c] != EMPTY for r in range(SIZE) for c in range(SIZE))
        if not has:
            return [(SIZE // 2, SIZE // 2)]

        cells = set()
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    for dr in range(-3, 4):
                        for dc in range(-3, 4):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == EMPTY:
                                cells.add((nr, nc))

        # Score each candidate with both attack and defense value
        scored = []
        for r, c in cells:
            attack = self._move_attack(board, r, c, self.color)
            defense = self._move_attack(board, r, c, self.opponent)
            # Weight defense slightly higher — blocking is often more urgent
            s = attack + defense * 1.2
            scored.append((s, (r, c)))
        scored.sort(reverse=True)
        n = min(60, len(scored))
        return [pos for _, pos in scored[:n]]

    def _move_attack(self, board, r, c, player):
        """Score the value of placing 'player' at (r,c)."""
        score = 0
        for dr, dc in DIRS:
            score += self._pattern_value_at(board, r, c, dr, dc, player)
        return score

    def _pattern_value_at(self, board, r, c, dr, dc, player):
        """Evaluate the threat value if 'player' occupies (r,c) in direction (dr,dc)."""
        # Count consecutive pieces and open ends
        count = 1
        open_ends = 0

        # Forward
        step = 1
        while True:
            nr, nc = r + dr * step, c + dc * step
            if 0 <= nr < SIZE and 0 <= nc < SIZE:
                if board[nr][nc] == player:
                    count += 1
                    step += 1
                else:
                    if board[nr][nc] == EMPTY:
                        # Check one more cell for jump patterns
                        nnr, nnc = nr + dr, nc + dc
                        if 0 <= nnr < SIZE and 0 <= nnc < SIZE and board[nnr][nnc] == player:
                            count += 0.5  # partial credit for jump
                        else:
                            open_ends += 1
                    break
            else:
                break

        # Backward
        step = 1
        while True:
            nr, nc = r - dr * step, c - dc * step
            if 0 <= nr < SIZE and 0 <= nc < SIZE:
                if board[nr][nc] == player:
                    count += 1
                    step += 1
                else:
                    if board[nr][nc] == EMPTY:
                        nnr, nnc = nr - dr, nc - dc
                        if 0 <= nnr < SIZE and 0 <= nnc < SIZE and board[nnr][nnc] == player:
                            count += 0.5
                        else:
                            open_ends += 1
                    break
            else:
                break

        return self._score_from_count(int(count), open_ends)

    def _score_from_count(self, count, open_ends):
        if count >= 5: return WIN_SCORE
        if count == 4:
            if open_ends == 2: return OPEN_FOUR
            if open_ends == 1: return CLOSED_FOUR
            return 0
        if count == 3:
            if open_ends == 2: return OPEN_THREE
            if open_ends == 1: return CLOSED_THREE
            return 0
        if count == 2:
            if open_ends == 2: return OPEN_TWO
            if open_ends == 1: return CLOSED_TWO
            return 0
        if count == 1:
            if open_ends == 2: return OPEN_ONE
            return 1
        return 0

    def _minimax(self, board, depth, alpha, beta, maximizing, _recursion=0):
        # Safety: hard recursion limit
        if _recursion > 20:
            return self._evaluate(board)
        if depth == 0 or self._should_abort():
            return self._evaluate(board)

        candidates = self._candidate_moves(board)
        if not candidates:
            return 0

        # Narrower search at deeper levels
        n = len(candidates)
        if depth <= 2:
            candidates = candidates[:min(n, 25)]
        elif depth <= 4:
            candidates = candidates[:min(n, 18)]
        else:
            candidates = candidates[:min(n, 12)]

        if maximizing:
            best = -float('inf')
            for r, c in candidates:
                if self._should_abort():
                    break
                board[r][c] = self.color
                if self._is_win_at(board, r, c, self.color):
                    board[r][c] = EMPTY
                    return WIN_SCORE + depth
                score = self._minimax(board, depth - 1, alpha, beta, False, _recursion + 1)
                board[r][c] = EMPTY
                if score > best:
                    best = score
                alpha = max(alpha, score)
                if alpha >= beta:
                    break
            return best
        else:
            best = float('inf')
            for r, c in candidates:
                if self._should_abort():
                    break
                board[r][c] = self.opponent
                if self._is_win_at(board, r, c, self.opponent):
                    board[r][c] = EMPTY
                    return -(WIN_SCORE + depth)
                score = self._minimax(board, depth - 1, alpha, beta, True, _recursion + 1)
                board[r][c] = EMPTY
                if score < best:
                    best = score
                beta = min(beta, score)
                if alpha >= beta:
                    break
            return best

    def _is_win_at(self, board, r, c, player):
        """Check if placing at (r,c) wins."""
        for dr, dc in DIRS:
            n = 1
            for s in (1, -1):
                step = 1
                while True:
                    nr, nc = r + dr * step * s, c + dc * step * s
                    if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == player:
                        n += 1; step += 1
                    else:
                        break
            if n >= 5:
                return True
        return False

    def _has_open_four(self, board, r, c, player):
        """Check if placing at (r,c) creates an open four (both ends open)."""
        for dr, dc in DIRS:
            count = 1
            open_ends = 0
            # Forward
            step = 1
            while True:
                nr, nc = r + dr * step, c + dc * step
                if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == player:
                    count += 1; step += 1
                else:
                    if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == EMPTY:
                        open_ends += 1
                    break
            # Backward
            step = 1
            while True:
                nr, nc = r - dr * step, c - dc * step
                if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == player:
                    count += 1; step += 1
                else:
                    if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == EMPTY:
                        open_ends += 1
                    break
            if count == 4 and open_ends == 2:
                return True
        return False

    def _evaluate(self, board):
        """Full-board evaluation with tiny noise for variety."""
        my_score = 0
        opp_score = 0
        has = False
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    has = True
                if board[r][c] == self.color:
                    my_score += self._position_score(board, r, c, self.color)
                elif board[r][c] == self.opponent:
                    opp_score += self._position_score(board, r, c, self.opponent)
        if not has:
            return 0
        total_pieces = sum(1 for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY)
        if total_pieces < 6:
            for r, c in [(SIZE//2, SIZE//2)]:
                if board[r][c] == self.color:
                    my_score += 50
                elif board[r][c] == self.opponent:
                    opp_score += 50
        # Tiny noise to break exact ties (1 part in 10,000)
        noise = random.randint(-50, 50)
        return my_score - opp_score * 1.15 + noise

    def _position_score(self, board, r, c, player):
        """Score all lines passing through (r,c) for the given player."""
        total = 0
        for dr, dc in DIRS:
            total += self._pattern_value_at(board, r, c, dr, dc, player)
        return total

    def _should_abort(self):
        """Check if search should be interrupted."""
        self.nodes += 1
        # Hard cap: never exceed max_nodes
        if self.nodes > self.max_nodes:
            return True
        # Periodic check: every 1024 nodes
        if self.nodes % 1024 == 0:
            if time.time() > self.deadline:
                return True
            if self.abort and self.abort():
                return True
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════════

def save_game(board, current, score, history):
    with open(SAVE_FILE, 'w') as f:
        json.dump({'board': board, 'current': current, 'score': score, 'history': history}, f)
    return f'Saved to {SAVE_FILE}'


def load_game():
    if not os.path.exists(SAVE_FILE):
        return None
    with open(SAVE_FILE) as f:
        return json.load(f)


def save_shared(board, current, score, history, black_uid, white_uid):
    data = {
        'board': board, 'current': current, 'score': score,
        'history': history, 'black_uid': black_uid, 'white_uid': white_uid,
    }
    tmp = SHARED_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.rename(tmp, SHARED_FILE)


def load_shared():
    if not os.path.exists(SHARED_FILE):
        return None
    with open(SHARED_FILE) as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════════════
# Game logic
# ═══════════════════════════════════════════════════════════════════════════════

def in_bounds(r, c):
    return 0 <= r < SIZE and 0 <= c < SIZE


def find_win(board, r, c):
    p = board[r][c]
    for dr, dc in DIRS:
        cells = [(r, c)]
        for s in (1, -1):
            step = 1
            while True:
                nr, nc = r + dr * step * s, c + dc * step * s
                if in_bounds(nr, nc) and board[nr][nc] == p:
                    cells.append((nr, nc))
                    step += 1
                else:
                    break
        if len(cells) >= 5:
            cells.sort()
            return cells
    return None


def is_full(board):
    for row in board:
        if EMPTY in row:
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Coordinate mapping
# ═══════════════════════════════════════════════════════════════════════════════

def screen_to_board(scr_row, scr_col, board_top):
    r = scr_row - board_top
    if not (0 <= r < SIZE):
        return None
    for c in range(SIZE):
        left = LABEL_W + c * CELL_W
        right = left + 1
        if left <= scr_col <= right:
            return (r, c)
    return None


def screen_to_button(scr_row, scr_col, btn_row):
    if abs(scr_row - btn_row) > 1:
        return None
    for name, (lx, rx) in BTN_MAP.items():
        if lx <= scr_col <= rx:
            return name
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Drawing
# ═══════════════════════════════════════════════════════════════════════════════

def draw(pad, board, cursor, current, msg, cols, win_cells=None, score=None, status=''):
    pad.erase()
    y = 0

    pch = PIECE_CH[current]
    pname = 'Black' if current == BLACK else 'White'
    title = f' Gomoku    {pch} {pname}'
    if score:
        title += f'      Score:  ● {score[BLACK]}  -  ○ {score[WHITE]}'
    if status:
        title += f'    {status}'
    pad.addstr(y, 0, title[:cols - 1], curses.A_BOLD)
    y += 1

    hint = ' [Click/Space] Place  [WASD] Move  [S] Save  [U] Undo  [Q] Quit'
    pad.addstr(y, 0, hint[:cols - 1], curses.A_DIM)
    y += 1
    y += 1

    board_top = y

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


def win_flash(pad, board, cursor, current, win_cells, score, cols, rows):
    for i in range(6):
        if i % 2 == 0:
            draw(pad, board, cursor, current, '', cols, win_cells=win_cells, score=score)
        else:
            draw(pad, board, cursor, current, '', cols, score=score)
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        time.sleep(0.15)
    pch = PIECE_CH[current]
    winner = 'Black' if current == BLACK else 'White'
    msg = f' {pch} {pch} {pch}  {winner} WINS!  {pch} {pch} {pch}'
    _, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score)
    pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
    return br


def endgame_loop(stdscr, board, cursor, current, win_cells, score, cols):
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
                    if b == 'restart': return 'restart'
                    if b == 'quit': return 'quit'
            except Exception:
                pass
        elif k in (ord('r'), ord('R')): return 'restart'
        elif k in (ord('q'), ord('Q'), 27): return 'quit'


# ═══════════════════════════════════════════════════════════════════════════════
# Wait-for-turn (shared mode)
# ═══════════════════════════════════════════════════════════════════════════════

def wait_for_turn(stdscr, expected_current):
    while True:
        stdscr.nodelay(1)
        k = stdscr.getch()
        stdscr.nodelay(0)
        if k in (ord('q'), ord('Q'), 27):
            return None

        data = load_shared()
        if data and data['current'] == expected_current:
            return data

        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        pad.erase()
        pch = '●' if expected_current == BLACK else '○'
        pad.addstr(0, 0, f' Gomoku    {pch} Waiting for opponent...'.ljust(cols)[:cols-1],
                   curses.A_BOLD | curses.color_pair(CP_CURSOR))
        pad.addstr(2, 0, '  [Q] Quit')
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        time.sleep(0.5)


# ═══════════════════════════════════════════════════════════════════════════════
# Menu
# ═══════════════════════════════════════════════════════════════════════════════

def show_menu(stdscr):
    rows, cols = stdscr.getmaxyx()
    menu = [
        '╔══════════════════════════╗',
        '║       GOMOKU 五子棋      ║',
        '╠══════════════════════════╣',
        '║  1. Local game          ║',
        '║  2. Host game (server)  ║',
        '║  3. Join game (client)  ║',
        '║  4. Shared (same-PC)    ║',
        '║  5. Player vs AI        ║',
        '║  6. AI vs AI            ║',
        '║  L. Load saved game     ║',
        '║  Q. Quit                ║',
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
        if k in (ord('l'), ord('L')): return 'load'
        if k in (ord('q'), ord('Q'), 27): return 'quit'


def show_pve_menu(stdscr):
    """Submenu for PvE: choose color and difficulty."""
    rows, cols = stdscr.getmaxyx()
    menu = [
        '╔══════════════════════════╗',
        '║     Player vs AI         ║',
        '╠══════════════════════════╣',
        '║  Choose your color:      ║',
        '║    B. Black (first)      ║',
        '║    W. White (second)     ║',
        '║                          ║',
        '║  Choose difficulty:      ║',
        '║    1. Easy   (depth 4)   ║',
        '║    2. Medium (depth 6)   ║',
        '║    3. Hard   (depth 8)   ║',
        '║                          ║',
        '║  Q. Back                 ║',
        '╚══════════════════════════╝',
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
        # Show current selection
        sel_line = ''
        if color_choice:
            sel_line += f'Color: {color_choice}  '
        if diff_choice:
            sel_line += f'Difficulty: {diff_choice}'
        if sel_line:
            try:
                stdscr.addstr(y + len(menu), x, sel_line[:cols - x], curses.A_BOLD)
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

        if color_choice and diff_choice:
            if k in (10, 13):  # Enter
                return color_choice, diff_choice


def show_eve_menu(stdscr):
    """Submenu for EvE: choose AI difficulties."""
    rows, cols = stdscr.getmaxyx()
    menu = [
        '╔══════════════════════════╗',
        '║       AI vs AI           ║',
        '╠══════════════════════════╣',
        '║  Black AI difficulty:    ║',
        '║    1. Easy   (depth 2)   ║',
        '║    2. Medium (depth 4)   ║',
        '║    3. Hard   (depth 6)   ║',
        '║                          ║',
        '║  White AI difficulty:    ║',
        '║    4. Easy   (depth 2)   ║',
        '║    5. Medium (depth 4)   ║',
        '║    6. Hard   (depth 6)   ║',
        '║                          ║',
        '║  Enter = Start           ║',
        '║  Q. Back                 ║',
        '╚══════════════════════════╝',
    ]
    b_depth = 4
    w_depth = 4
    b_label = 'Medium'
    w_label = 'Medium'
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
        if k in (10, 13):  # Enter
            return b_depth, w_depth


# ═══════════════════════════════════════════════════════════════════════════════
# Local game
# ═══════════════════════════════════════════════════════════════════════════════

def run_local(stdscr, initial=None):
    if initial:
        board = initial['board']
        history = initial.get('history', [])
        current = initial['current']
        score = {BLACK: initial['score'].get(str(BLACK), 0), WHITE: initial['score'].get(str(WHITE), 0)}
        msg = 'Loaded saved game!'
    else:
        board = [[EMPTY] * SIZE for _ in range(SIZE)]
        history = []
        current = BLACK
        score = {BLACK: 0, WHITE: 0}
        msg = ''
    cursor = (SIZE // 2, SIZE // 2)
    win_cells = None

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score)
        msg = ''; win_cells = None
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)

        key = stdscr.getch()

        # Mouse
        if key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bs = curses.getmouse()
            except Exception:
                continue
            if bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                btn = screen_to_button(my, mx, br)
                if btn == 'quit': return
                if btn == 'restart':
                    board = [[EMPTY]*SIZE for _ in range(SIZE)]
                    history.clear(); cursor = (SIZE//2, SIZE//2); current = BLACK
                    msg = 'New game!'; continue
                if btn == 'undo':
                    if history:
                        r, c, prev = history.pop()
                        board[r][c] = EMPTY; current = prev; cursor = (r, c)
                        msg = 'Undone'
                    else: msg = 'Nothing to undo'
                    continue
                if btn == 'save':
                    msg = save_game(board, current, score, history); continue
                pos = screen_to_board(my, mx, bt)
                if pos is not None:
                    r, c = pos
                    if board[r][c] == EMPTY:
                        history.append((r,c,current)); board[r][c]=current; cursor=(r,c)
                        wc = find_win(board,r,c)
                        if wc:
                            score[current] += 1
                            r2,c2 = stdscr.getmaxyx()
                            p2 = curses.newpad(r2+40, max(c2,32))
                            win_flash(p2,board,cursor,current,wc,score,c2,r2)
                            act = endgame_loop(stdscr,board,cursor,current,wc,score,c2)
                            if act == 'restart':
                                board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                            else: return
                            continue
                        elif is_full(board): msg='Draw!'; continue
                        else: current = WHITE if current==BLACK else BLACK
                    else: cursor=(r,c); msg='Occupied'
            continue

        # Keyboard
        if key in (ord('q'), ord('Q'), 27): return
        if key in (ord('r'), ord('R')):
            board=[[EMPTY]*SIZE for _ in range(SIZE)]
            history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'; continue
        if key in (ord('u'), ord('U')):
            if history:
                r,c,prev=history.pop(); board[r][c]=EMPTY; current=prev; cursor=(r,c); msg='Undone'
            else: msg='Nothing to undo'
            continue
        if key in (ord('s'), ord('S')):
            msg=save_game(board,current,score,history); continue
        if key in (ord('w'), curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1, cursor[1])
        elif key in (ord('s'), curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1, cursor[1])
        elif key in (ord('a'), curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0], cursor[1]-1)
        elif key in (ord('d'), curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0], cursor[1]+1)
        elif key in (curses.KEY_ENTER, 10, 13, ord(' ')):
            r,c=cursor
            if board[r][c]==EMPTY:
                history.append((r,c,current)); board[r][c]=current
                wc=find_win(board,r,c)
                if wc:
                    score[current]+=1
                    r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40, max(c2,32))
                    win_flash(p2,board,cursor,current,wc,score,c2,r2)
                    act=endgame_loop(stdscr,board,cursor,current,wc,score,c2)
                    if act=='restart':
                        board=[[EMPTY]*SIZE for _ in range(SIZE)]
                        history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                    else: return
                    continue
                elif is_full(board): msg='Draw!'; continue
                else: current=WHITE if current==BLACK else BLACK
            else: msg='Occupied'


# ═══════════════════════════════════════════════════════════════════════════════
# Player vs AI
# ═══════════════════════════════════════════════════════════════════════════════

def run_pve(stdscr):
    color_name, (diff_name, depth) = show_pve_menu(stdscr)
    if not color_name: return

    human_color = BLACK if color_name == 'Black' else WHITE
    ai_color = WHITE if human_color == BLACK else BLACK
    ai = GomokuAI(ai_color, depth)

    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    history = []
    cursor = (SIZE // 2, SIZE // 2)
    current = BLACK  # always starts with black
    score = {BLACK: 0, WHITE: 0}
    msg = f'You: {color_name}  AI: {diff_name} (depth {depth})'
    win_cells = None

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        status = 'Your turn' if current == human_color else 'AI thinking...'
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        msg = ''; win_cells = None

        if current == ai_color:
            pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
            # AI move (15s time limit, Q to abort)
            def pve_abort():
                stdscr.nodelay(1)
                k = stdscr.getch()
                stdscr.nodelay(0)
                return k in (ord('q'), ord('Q'), 27)
            move = ai.get_move([row[:] for row in board],
                               abort_fn=pve_abort, time_limit=15)
            if move:
                r, c = move
                if board[r][c] == EMPTY:
                    board[r][c] = ai_color
                    cursor = (r, c)
                    wc = find_win(board, r, c)
                    if wc:
                        score[ai_color] += 1
                        r2, c2 = stdscr.getmaxyx()
                        p2 = curses.newpad(r2+40, max(c2,32))
                        win_flash(p2, board, cursor, ai_color, wc, score, c2, r2)
                        pch = PIECE_CH[ai_color]
                        m = f'{pch} AI WINS!  ● {score[BLACK]} - ○ {score[WHITE]}   [R] Restart  [Q] Quit'
                        act = endgame_loop(stdscr, board, cursor, ai_color, wc, score, c2)
                        if act == 'restart':
                            board = [[EMPTY]*SIZE for _ in range(SIZE)]
                            history.clear(); cursor = (SIZE//2, SIZE//2); current = BLACK
                            msg = 'New game!'
                        else: return
                        continue
                    elif is_full(board): msg = 'Draw!'; continue
                    else: current = human_color
            continue

        # Human turn
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        key = stdscr.getch()

        if key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bs = curses.getmouse()
            except Exception:
                continue
            if bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                btn = screen_to_button(my, mx, br)
                if btn == 'quit': return
                if btn == 'restart':
                    board = [[EMPTY]*SIZE for _ in range(SIZE)]
                    history.clear(); cursor = (SIZE//2, SIZE//2); current = BLACK
                    msg = 'New game!'; continue
                if btn == 'undo':
                    # Undo both AI's last move and your last move
                    if len(history) >= 2:
                        for _ in range(2):
                            r2, c2, p2 = history.pop()
                            board[r2][c2] = EMPTY
                        current = human_color; cursor = (r2, c2)
                        msg = 'Undone (2 moves)'
                    elif history:
                        r2, c2, p2 = history.pop()
                        board[r2][c2] = EMPTY
                        current = human_color; cursor = (r2, c2)
                        msg = 'Undone'
                    else: msg = 'Nothing to undo'
                    continue
                pos = screen_to_board(my, mx, bt)
                if pos is not None and board[pos[0]][pos[1]] == EMPTY:
                    r, c = pos
                    history.append((r,c,human_color)); board[r][c]=human_color; cursor=(r,c)
                    wc = find_win(board, r, c)
                    if wc:
                        score[human_color] += 1
                        r2,c2 = stdscr.getmaxyx(); p2 = curses.newpad(r2+40, max(c2,32))
                        win_flash(p2,board,cursor,human_color,wc,score,c2,r2)
                        pch = PIECE_CH[human_color]
                        m = f'{pch} You WIN!  ● {score[BLACK]} - ○ {score[WHITE]}   [R] Restart  [Q] Quit'
                        act = endgame_loop(stdscr,board,cursor,human_color,wc,score,c2)
                        if act == 'restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]
                            history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                            msg='New game!'
                        else: return
                        continue
                    elif is_full(board): msg='Draw!'; continue
                    else: current = ai_color
                elif pos is not None: cursor = pos; msg = 'Occupied'
            continue

        if key in (ord('q'), ord('Q'), 27): return
        if key in (ord('r'), ord('R')):
            board=[[EMPTY]*SIZE for _ in range(SIZE)]
            history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'; continue
        if key in (ord('w'), curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1, cursor[1])
        elif key in (ord('s'), curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1, cursor[1])
        elif key in (ord('a'), curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0], cursor[1]-1)
        elif key in (ord('d'), curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0], cursor[1]+1)
        elif key in (curses.KEY_ENTER, 10, 13, ord(' ')):
            r,c=cursor
            if board[r][c]==EMPTY:
                history.append((r,c,human_color)); board[r][c]=human_color
                wc=find_win(board,r,c)
                if wc:
                    score[human_color]+=1
                    r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40, max(c2,32))
                    win_flash(p2,board,cursor,human_color,wc,score,c2,r2)
                    pch=PIECE_CH[human_color]
                    m=f'{pch} You WIN!  ● {score[BLACK]} - ○ {score[WHITE]}   [R] Restart  [Q] Quit'
                    act=endgame_loop(stdscr,board,cursor,human_color,wc,score,c2)
                    if act=='restart':
                        board=[[EMPTY]*SIZE for _ in range(SIZE)]
                        history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                    else: return
                    continue
                elif is_full(board): msg='Draw!'; continue
                else: current=ai_color
            else: msg='Occupied'


# ═══════════════════════════════════════════════════════════════════════════════
# AI vs AI (spectate)
# ═══════════════════════════════════════════════════════════════════════════════

def run_eve(stdscr):
    b_depth, w_depth = show_eve_menu(stdscr)
    if not b_depth: return

    # Cap depth for EvE to keep it responsive
    b_depth = min(b_depth, 6)
    w_depth = min(w_depth, 6)

    black_ai = GomokuAI(BLACK, b_depth)
    white_ai = GomokuAI(WHITE, w_depth)

    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    current = BLACK
    score = {BLACK: 0, WHITE: 0}
    msg = f'AI battle: Black(depth {b_depth}) vs White(depth {w_depth})  [Q] quit'
    win_cells = None
    cursor = (SIZE // 2, SIZE // 2)

    def make_abort_checker(scr):
        """Return a callable that checks for quit key without blocking."""
        def check():
            scr.nodelay(1)
            k = scr.getch()
            scr.nodelay(0)
            return k in (ord('q'), ord('Q'), 27)
        return check

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows + 40, max(cols, 32))
        ai = black_ai if current == BLACK else white_ai
        status = f'AI ({"Black" if current==BLACK else "White"}) thinking...'
        draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        pad.refresh(0, 0, 0, 0, rows - 1, cols - 1)
        msg = ''; win_cells = None

        # Check for quit before AI move
        stdscr.nodelay(1)
        k = stdscr.getch()
        stdscr.nodelay(0)
        if k in (ord('q'), ord('Q'), 27):
            return

        # AI move with abort check + 12s time limit
        move = ai.get_move([row[:] for row in board],
                           abort_fn=make_abort_checker(stdscr),
                           time_limit=12)
        if move:
            r, c = move
            if board[r][c] == EMPTY:
                board[r][c] = current
                cursor = (r, c)
                wc = find_win(board, r, c)
                if wc:
                    score[current] += 1
                    r2, c2 = stdscr.getmaxyx()
                    p2 = curses.newpad(r2+40, max(c2,32))
                    win_flash(p2, board, cursor, current, wc, score, c2, r2)
                    pch = PIECE_CH[current]
                    winner = 'Black AI' if current == BLACK else 'White AI'
                    m = f'{pch} {winner} WINS!  ● {score[BLACK]} - ○ {score[WHITE]}   [R] Restart  [Q] Quit'
                    act = endgame_loop(stdscr, board, cursor, current, wc, score, c2)
                    if act == 'restart':
                        board = [[EMPTY]*SIZE for _ in range(SIZE)]
                        cursor = (SIZE//2, SIZE//2); current = BLACK
                        msg = 'New game!'
                    else: return
                    continue
                elif is_full(board): msg = 'Draw!'; continue
                else: current = WHITE if current == BLACK else BLACK


# ═══════════════════════════════════════════════════════════════════════════════
# Network helpers
# ═══════════════════════════════════════════════════════════════════════════════

def recv_move(sock, timeout=0.1):
    ready, _, _ = select.select([sock], [], [], timeout)
    if ready:
        data = sock.recv(1024)
        if data:
            try:
                r, c = map(int, data.decode().strip().split(','))
                return (r, c)
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


def show_ip_screen(stdscr, port):
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
    lines = [
        'Waiting for opponent to connect...',
        '',
        f'  Your IP:   {ip}',
        f'  Port:      {port}',
        '',
        '  Press Q to cancel',
    ]
    for i, line in enumerate(lines):
        try:
            stdscr.addstr(rows//2-3+i, max(0, (cols-len(line))//2), line, curses.A_BOLD)
        except curses.error:
            pass
    stdscr.refresh()
    return ip


def show_join_screen(stdscr):
    curses.echo()
    curses.curs_set(1)
    rows, cols = stdscr.getmaxyx()
    ip = ''
    while True:
        stdscr.erase()
        msg = 'Enter host IP address: '
        stdscr.addstr(rows//2, max(0, (cols-len(msg)-len(ip))//2), msg + ip)
        stdscr.refresh()
        k = stdscr.getch()
        if k in (10, 13): break
        if k in (27,): curses.noecho(); curses.curs_set(0); return None
        if k in (curses.KEY_BACKSPACE, 127, 8): ip = ip[:-1]
        elif 32 <= k <= 126: ip += chr(k)
    curses.noecho()
    curses.curs_set(0)
    return ip.strip() or None


# ═══════════════════════════════════════════════════════════════════════════════
# Network modes (host / join)
# ═══════════════════════════════════════════════════════════════════════════════

def run_host(stdscr):
    port = DEFAULT_PORT
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(1)
    server.setblocking(False)

    show_ip_screen(stdscr, port)
    while True:
        k = stdscr.getch()
        if k in (ord('q'), ord('Q'), 27): server.close(); return
        try: client, _ = server.accept(); break
        except BlockingIOError: continue
    server.close()

    board = [[EMPTY]*SIZE for _ in range(SIZE)]
    history = []; cursor = (SIZE//2, SIZE//2)
    current = BLACK; score = {BLACK:0, WHITE:0}
    msg = 'Connected! You are ● Black'; win_cells = None; my_turn = True

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        status = 'Your turn' if my_turn else "Opponent's turn"
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        msg = ''; win_cells = None; pad.refresh(0,0,0,0,rows-1,cols-1)

        if my_turn:
            key = stdscr.getch()
            if key == curses.KEY_MOUSE:
                try:
                    _,mx,my,_,bs = curses.getmouse()
                except Exception:
                    continue
                if bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                    btn = screen_to_button(my,mx,br)
                    if btn == 'quit': client.close(); return
                    pos = screen_to_board(my,mx,bt)
                    if pos is not None and board[pos[0]][pos[1]]==EMPTY:
                        r,c = pos
                        board[r][c]=BLACK; history.append((r,c,BLACK)); cursor=(r,c)
                        send_move(client,r,c)
                        wc = find_win(board,r,c)
                        if wc:
                            score[BLACK]+=1
                            r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                            win_flash(p2,board,cursor,BLACK,wc,score,c2,r2)
                            act=endgame_loop(stdscr,board,cursor,BLACK,wc,score,c2)
                            client.close()
                            if act=='restart':
                                board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                                msg='New game!'; my_turn=True
                            else: return
                            continue
                        elif is_full(board): msg='Draw!'; continue
                        my_turn=False; continue
                continue
            if key in (ord('q'),ord('Q'),27): client.close(); return
            if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
            elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
            elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
            elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
            elif key in (curses.KEY_ENTER,10,13,ord(' ')):
                r,c=cursor
                if board[r][c]==EMPTY:
                    board[r][c]=BLACK; history.append((r,c,BLACK))
                    send_move(client,r,c)
                    wc=find_win(board,r,c)
                    if wc:
                        score[BLACK]+=1
                        r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        win_flash(p2,board,cursor,BLACK,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,BLACK,wc,score,c2)
                        client.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]
                            history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                            msg='New game!'; my_turn=True
                        else: return
                        continue
                    elif is_full(board): msg='Draw!'; continue
                    my_turn=False
        else:
            move = recv_move(client, timeout=0.3)
            if move is not None:
                r,c = move
                if board[r][c]==EMPTY:
                    board[r][c]=WHITE; cursor=(r,c)
                    wc=find_win(board,r,c)
                    if wc:
                        score[WHITE]+=1
                        r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        win_flash(p2,board,cursor,WHITE,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,WHITE,wc,score,c2)
                        client.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]
                            history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                            msg='New game!'; my_turn=True
                        else: return
                        continue
                    my_turn=True; continue
            data = recv_all(client, timeout=0.05)
            if data == 'QUIT': msg='Opponent disconnected'; client.close(); time.sleep(1); return
            stdscr.nodelay(1); k=stdscr.getch(); stdscr.nodelay(0)
            if k in (ord('q'),ord('Q'),27): send_move(client,-1,-1); client.close(); return
            rows2,cols2=stdscr.getmaxyx()
            p2=curses.newpad(rows2+40,max(cols2,32))
            draw(p2,board,cursor,current,'Waiting for opponent...',cols2,score=score)
            p2.refresh(0,0,0,0,rows2-1,cols2-1)


def run_join(stdscr):
    ip = show_join_screen(stdscr)
    if not ip: return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect((ip, DEFAULT_PORT))
    except Exception as e:
        rows, cols = stdscr.getmaxyx()
        stdscr.erase()
        m = f'Could not connect: {e}'
        stdscr.addstr(rows//2, max(0,(cols-len(m))//2), m)
        stdscr.refresh(); time.sleep(2); return

    board = [[EMPTY]*SIZE for _ in range(SIZE)]
    history = []; cursor = (SIZE//2, SIZE//2)
    current = WHITE; score = {BLACK:0, WHITE:0}
    msg = 'Connected! You are ○ White'; win_cells = None; my_turn = False

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        status = 'Your turn' if my_turn else "Opponent's turn"
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        msg=''; win_cells=None; pad.refresh(0,0,0,0,rows-1,cols-1)

        if my_turn:
            key = stdscr.getch()
            if key == curses.KEY_MOUSE:
                try:
                    _,mx,my,_,bs = curses.getmouse()
                except Exception:
                    continue
                if bs & (curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                    btn = screen_to_button(my,mx,br)
                    if btn=='quit': sock.sendall(b'QUIT'); sock.close(); return
                    pos = screen_to_board(my,mx,bt)
                    if pos is not None and board[pos[0]][pos[1]]==EMPTY:
                        r,c=pos
                        board[r][c]=WHITE; history.append((r,c,WHITE)); cursor=(r,c)
                        send_move(sock,r,c)
                        wc=find_win(board,r,c)
                        if wc:
                            score[WHITE]+=1
                            r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                            win_flash(p2,board,cursor,WHITE,wc,score,c2,r2)
                            act=endgame_loop(stdscr,board,cursor,WHITE,wc,score,c2)
                            sock.close()
                            if act=='restart':
                                board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                history.clear(); cursor=(SIZE//2,SIZE//2); current=WHITE
                                msg='New game!'; my_turn=False
                            else: return
                            continue
                        elif is_full(board): msg='Draw!'; continue
                        my_turn=False; continue
                continue
            if key in (ord('q'),ord('Q'),27): sock.sendall(b'QUIT'); sock.close(); return
            if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
            elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
            elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
            elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
            elif key in (curses.KEY_ENTER,10,13,ord(' ')):
                r,c=cursor
                if board[r][c]==EMPTY:
                    board[r][c]=WHITE; history.append((r,c,WHITE))
                    send_move(sock,r,c)
                    wc=find_win(board,r,c)
                    if wc:
                        score[WHITE]+=1
                        r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        win_flash(p2,board,cursor,WHITE,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,WHITE,wc,score,c2)
                        sock.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]
                            history.clear(); cursor=(SIZE//2,SIZE//2); current=WHITE
                            msg='New game!'; my_turn=False
                        else: return
                        continue
                    elif is_full(board): msg='Draw!'; continue
                    my_turn=False
        else:
            move = recv_move(sock, timeout=0.3)
            if move is not None:
                r,c = move
                if r < 0: msg='Opponent quit'; sock.close(); time.sleep(1); return
                if board[r][c]==EMPTY:
                    board[r][c]=BLACK; cursor=(r,c)
                    wc=find_win(board,r,c)
                    if wc:
                        score[BLACK]+=1
                        r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        win_flash(p2,board,cursor,BLACK,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,BLACK,wc,score,c2)
                        sock.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]
                            history.clear(); cursor=(SIZE//2,SIZE//2); current=WHITE
                            msg='New game!'; my_turn=False
                        else: return
                        continue
                    my_turn=True; continue
            data = recv_all(sock, timeout=0.05)
            if data=='QUIT': msg='Opponent disconnected'; sock.close(); time.sleep(1); return
            stdscr.nodelay(1); k=stdscr.getch(); stdscr.nodelay(0)
            if k in (ord('q'),ord('Q'),27): sock.sendall(b'QUIT'); sock.close(); return
            rows2,cols2=stdscr.getmaxyx()
            p2=curses.newpad(rows2+40,max(cols2,32))
            draw(p2,board,cursor,current,'Waiting for opponent...',cols2,score=score)
            p2.refresh(0,0,0,0,rows2-1,cols2-1)


# ═══════════════════════════════════════════════════════════════════════════════
# Shared mode (same-machine, file-based)
# ═══════════════════════════════════════════════════════════════════════════════

def run_shared(stdscr):
    my_uid = os.getuid()
    data = load_shared()

    if data is None:
        board = [[EMPTY]*SIZE for _ in range(SIZE)]
        history = []; current = BLACK; score = {BLACK:0, WHITE:0}
        my_color = BLACK; black_uid = my_uid; white_uid = None
        save_shared(board, current, score, history, black_uid, white_uid)
        msg = f'New shared game! You are ● Black.'
    elif data['black_uid'] == my_uid:
        board = data['board']; current = data['current']
        score = {BLACK: data['score'].get(str(BLACK),0), WHITE: data['score'].get(str(WHITE),0)}
        history = data.get('history',[]); my_color = BLACK
        black_uid = data['black_uid']; white_uid = data.get('white_uid')
        msg = 'Welcome back! You are ● Black.'
    elif data.get('white_uid') is None:
        board = data['board']; current = data['current']
        score = {BLACK: data['score'].get(str(BLACK),0), WHITE: data['score'].get(str(WHITE),0)}
        history = data.get('history',[]); my_color = WHITE
        black_uid = data['black_uid']; white_uid = my_uid
        save_shared(board, current, score, history, black_uid, white_uid)
        msg = 'Joined! You are ○ White.'
    elif data.get('white_uid') == my_uid:
        board = data['board']; current = data['current']
        score = {BLACK: data['score'].get(str(BLACK),0), WHITE: data['score'].get(str(WHITE),0)}
        history = data.get('history',[]); my_color = WHITE
        black_uid = data['black_uid']; white_uid = data['white_uid']
        msg = 'Welcome back! You are ○ White.'
    else:
        rows, cols = stdscr.getmaxyx(); stdscr.erase()
        m2 = 'Game is full (2 players already).'
        stdscr.addstr(rows//2, max(0,(cols-len(m2))//2), m2, curses.A_BOLD)
        stdscr.refresh(); time.sleep(2); return

    cursor = (SIZE//2, SIZE//2); win_cells = None

    while True:
        data = load_shared()
        if data is None: msg='Shared file deleted.'; time.sleep(1); return
        current = data['current']
        score = {BLACK: data['score'].get(str(BLACK),0), WHITE: data['score'].get(str(WHITE),0)}

        if current != my_color:
            data = wait_for_turn(stdscr, my_color)
            if data is None: return
            board = data['board']; current = data['current']
            score = {BLACK: data['score'].get(str(BLACK),0), WHITE: data['score'].get(str(WHITE),0)}
            history = data.get('history',[]); msg = "Opponent moved! Your turn."
            # Check opponent win
            opp = WHITE if my_color==BLACK else BLACK
            for r in range(SIZE):
                for c in range(SIZE):
                    if board[r][c]==opp:
                        wc = find_win(board,r,c)
                        if wc:
                            win_cells = wc; pch = PIECE_CH[opp]
                            rows2,cols2=stdscr.getmaxyx(); p2=curses.newpad(rows2+40,max(cols2,32))
                            win_flash(p2,board,(r,c),opp,wc,score,cols2,rows2)
                            m3 = f'{pch} Opponent WINS!  ● {score[BLACK]} - ○ {score[WHITE]}   [R] Restart  [Q] Quit'
                            while True:
                                d3=load_shared()
                                if d3: score={BLACK:d3['score'].get(str(BLACK),0),WHITE:d3['score'].get(str(WHITE),0)}
                                r3,c3=stdscr.getmaxyx(); p3=curses.newpad(r3+40,max(c3,32))
                                _,br3=draw(p3,board,(SIZE//2,SIZE//2),opp,m3,c3,win_cells=wc,score=score)
                                p3.refresh(0,0,0,0,r3-1,c3-1); k3=stdscr.getch()
                                if k3==curses.KEY_MOUSE:
                                    try:
                                        _,mx3,my3,_,bs3=curses.getmouse()
                                        if bs3&(curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                                            b3=screen_to_button(my3,mx3,br3)
                                            if b3 in ('restart','quit'):
                                                if my_color==BLACK:
                                                    save_shared([[EMPTY]*SIZE for _ in range(SIZE)],BLACK,score,[],black_uid,white_uid)
                                                if b3=='quit': return
                                                board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                                history=[]; cursor=(SIZE//2,SIZE//2); current=BLACK
                                                msg='New game!'; win_cells=None; break
                                    except Exception: pass
                                elif k3 in (ord('r'),ord('R')):
                                    if my_color==BLACK:
                                        save_shared([[EMPTY]*SIZE for _ in range(SIZE)],BLACK,score,[],black_uid,white_uid)
                                    board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                    history=[]; cursor=(SIZE//2,SIZE//2); current=BLACK
                                    msg='New game!'; win_cells=None; break
                                elif k3 in (ord('q'),ord('Q'),27): return
                            break
                if win_cells: break
            continue

        # Our turn
        rows,cols=stdscr.getmaxyx(); pad=curses.newpad(rows+40,max(cols,32))
        bt,br=draw(pad,board,cursor,my_color,msg,cols,win_cells=win_cells,score=score,status='Your turn')
        msg=''; win_cells=None; pad.refresh(0,0,0,0,rows-1,cols-1)
        key=stdscr.getch()
        if key==curses.KEY_MOUSE:
            try:
                _,mx,my,_,bs=curses.getmouse()
            except Exception: continue
            if bs&(curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                btn=screen_to_button(my,mx,br)
                if btn=='quit': return
                if btn=='restart':
                    if my_color==BLACK:
                        board=[[EMPTY]*SIZE for _ in range(SIZE)]
                        history=[]; cursor=(SIZE//2,SIZE//2)
                        save_shared(board,BLACK,score,history,black_uid,white_uid); msg='New game!'
                    else: msg='Only Black can restart'
                    continue
                pos=screen_to_board(my,mx,bt)
                if pos is not None and board[pos[0]][pos[1]]==EMPTY:
                    r,c=pos
                    history.append((r,c,my_color)); board[r][c]=my_color; cursor=(r,c)
                    wc=find_win(board,r,c)
                    if wc:
                        score[my_color]+=1
                        save_shared(board,(WHITE if my_color==BLACK else BLACK),score,history,black_uid,white_uid)
                        r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        win_flash(p2,board,cursor,my_color,wc,score,c2,r2)
                        pch=PIECE_CH[my_color]; m=f'{pch} You WIN!  ● {score[BLACK]} - ○ {score[WHITE]}   [R] Restart  [Q] Quit'
                        while True:
                            d2=load_shared()
                            if d2: score={BLACK:d2['score'].get(str(BLACK),0),WHITE:d2['score'].get(str(WHITE),0)}
                            r3,c3=stdscr.getmaxyx(); p3=curses.newpad(r3+40,max(c3,32))
                            _,br3=draw(p3,board,(SIZE//2,SIZE//2),my_color,m,c3,win_cells=wc,score=score)
                            p3.refresh(0,0,0,0,r3-1,c3-1); k3=stdscr.getch()
                            if k3==curses.KEY_MOUSE:
                                try:
                                    _,mx3,my3,_,bs3=curses.getmouse()
                                    if bs3&(curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                                        b3=screen_to_button(my3,mx3,br3)
                                        if b3 in ('restart','quit'):
                                            if my_color==BLACK:
                                                save_shared([[EMPTY]*SIZE for _ in range(SIZE)],BLACK,score,[],black_uid,white_uid)
                                            if b3=='quit': return
                                            board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                            history=[]; cursor=(SIZE//2,SIZE//2); current=BLACK
                                            msg='New game!'; win_cells=None; break
                                except Exception: pass
                            elif k3 in (ord('r'),ord('R')):
                                if my_color==BLACK:
                                    save_shared([[EMPTY]*SIZE for _ in range(SIZE)],BLACK,score,[],black_uid,white_uid)
                                board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                history=[]; cursor=(SIZE//2,SIZE//2); current=BLACK
                                msg='New game!'; win_cells=None; break
                            elif k3 in (ord('q'),ord('Q'),27): return
                        continue
                    elif is_full(board): msg='Draw!'; continue
                    else:
                        save_shared(board,(WHITE if my_color==BLACK else BLACK),score,history,black_uid,white_uid)
                        msg='Move sent. Waiting...'; continue
                elif pos is not None: cursor=pos; msg='Occupied'
            continue
        if key in (ord('q'),ord('Q'),27): return
        if key in (ord('r'),ord('R')):
            if my_color==BLACK:
                board=[[EMPTY]*SIZE for _ in range(SIZE)]; history=[]; cursor=(SIZE//2,SIZE//2)
                save_shared(board,BLACK,score,history,black_uid,white_uid); msg='New game!'
            else: msg='Only Black can restart'
            continue
        if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
        elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
        elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
        elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
        elif key in (curses.KEY_ENTER,10,13,ord(' ')):
            r,c=cursor
            if board[r][c]==EMPTY:
                history.append((r,c,my_color)); board[r][c]=my_color
                wc=find_win(board,r,c)
                if wc:
                    score[my_color]+=1
                    save_shared(board,(WHITE if my_color==BLACK else BLACK),score,history,black_uid,white_uid)
                    r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                    win_flash(p2,board,cursor,my_color,wc,score,c2,r2)
                    pch=PIECE_CH[my_color]; m=f'{pch} You WIN!  ● {score[BLACK]} - ○ {score[WHITE]}   [R] Restart  [Q] Quit'
                    while True:
                        d2=load_shared()
                        if d2: score={BLACK:d2['score'].get(str(BLACK),0),WHITE:d2['score'].get(str(WHITE),0)}
                        r3,c3=stdscr.getmaxyx(); p3=curses.newpad(r3+40,max(c3,32))
                        _,br3=draw(p3,board,(SIZE//2,SIZE//2),my_color,m,c3,win_cells=wc,score=score)
                        p3.refresh(0,0,0,0,r3-1,c3-1); k3=stdscr.getch()
                        if k3==curses.KEY_MOUSE:
                            try:
                                _,mx3,my3,_,bs3=curses.getmouse()
                                if bs3&(curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                                    b3=screen_to_button(my3,mx3,br3)
                                    if b3 in ('restart','quit'):
                                        if my_color==BLACK:
                                            save_shared([[EMPTY]*SIZE for _ in range(SIZE)],BLACK,score,[],black_uid,white_uid)
                                        if b3=='quit': return
                                        board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                        history=[]; cursor=(SIZE//2,SIZE//2); current=BLACK
                                        msg='New game!'; win_cells=None; break
                            except Exception: pass
                        elif k3 in (ord('r'),ord('R')):
                            if my_color==BLACK:
                                save_shared([[EMPTY]*SIZE for _ in range(SIZE)],BLACK,score,[],black_uid,white_uid)
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]
                            history=[]; cursor=(SIZE//2,SIZE//2); current=BLACK
                            msg='New game!'; win_cells=None; break
                        elif k3 in (ord('q'),ord('Q'),27): return
                    continue
                elif is_full(board): msg='Draw!'; continue
                else:
                    save_shared(board,(WHITE if my_color==BLACK else BLACK),score,history,black_uid,white_uid)
                    msg='Move sent. Waiting...'; continue
            else: msg='Occupied'


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    curses.curs_set(0)
    stdscr.nodelay(0)
    stdscr.keypad(1)

    curses.init_pair(CP_BOARD, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_BLACK, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(CP_WHITE, curses.COLOR_WHITE, curses.COLOR_YELLOW)
    curses.init_pair(CP_CURSOR, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(CP_BUTTON, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(CP_WIN, curses.COLOR_BLACK, curses.COLOR_RED)
    curses.init_pair(CP_MENU, curses.COLOR_WHITE, curses.COLOR_BLUE)

    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
    except Exception:
        pass

    while True:
        choice = show_menu(stdscr)
        if choice == 'local': run_local(stdscr)
        elif choice == 'host': run_host(stdscr)
        elif choice == 'join': run_join(stdscr)
        elif choice == 'shared': run_shared(stdscr)
        elif choice == 'pve': run_pve(stdscr)
        elif choice == 'eve': run_eve(stdscr)
        elif choice == 'load':
            data = load_game()
            if data:
                run_local(stdscr, initial=data)
            else:
                rows, cols = stdscr.getmaxyx()
                stdscr.erase(); m = 'No saved game found.'
                stdscr.addstr(rows//2, max(0,(cols-len(m))//2), m, curses.A_BOLD)
                stdscr.refresh(); time.sleep(1.5)
        elif choice == 'quit': break


if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'Error: {e}')
        raise
