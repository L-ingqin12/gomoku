#!/usr/bin/env python3
"""
Gomoku (五子棋) — curses terminal game.
Modes: Local / Network / Shared / PvE AI / EvE AI / Replay

AI: Minimax + alpha-beta + VCF threat search + pattern DB
"""

import curses
import json
import os
import random
import select
import socket
import threading
import time

SAVE_FILE = os.path.expanduser('~/.gomoku_save.json')
SHARED_FILE = '/tmp/gomoku_shared.json'
KIFU_DIR = os.path.expanduser('~/.gomoku_kifu')
DEFAULT_PORT = 9999

SIZE = 15
EMPTY = 0
BLACK = 1
WHITE = 2

PIECE_CH = {EMPTY: '┼', BLACK: '●', WHITE: '○'}
HLINE = '─'
DIRS = [(0, 1), (1, 0), (1, 1), (1, -1)]

CP_BOARD = 1; CP_BLACK = 2; CP_WHITE = 3; CP_CURSOR = 4
CP_BUTTON = 5; CP_WIN = 6; CP_MENU = 7

CELL_W = 2; LABEL_W = 2

BTN_TEXT = ' [Quit]  [Restart]  [Undo]  [Save]'
BTN_MAP = {'quit': (1, 6), 'restart': (9, 18), 'undo': (21, 27), 'save': (30, 36)}

os.makedirs(KIFU_DIR, exist_ok=True)


# ═══════════════════════════ AI Engine ═══════════════════════════

WIN_SCORE = 100_000_000
FOUR_SCORE = 10_000_000
THREE_SCORE = 100_000
TWO_SCORE = 1_000


def _count_run(board, r, c, dr, dc, player):
    """Count consecutive 'player' pieces through (r,c) and return (count, open_ends)."""
    count = 1; open_ends = 0
    for sign in (1, -1):
        step = 1
        while True:
            nr, nc = r + dr * step * sign, c + dc * step * sign
            if 0 <= nr < SIZE and 0 <= nc < SIZE:
                if board[nr][nc] == player:
                    count += 1; step += 1
                else:
                    if board[nr][nc] == EMPTY: open_ends += 1
                    break
            else: break
    return count, open_ends


def _pattern_type(count, open_ends):
    """Classify a run into a threat level."""
    if count >= 5: return 'WIN'
    if count == 4:
        if open_ends == 2: return 'LIVE4'
        if open_ends == 1: return 'RUSH4'
        return None
    if count == 3:
        if open_ends == 2: return 'LIVE3'
        if open_ends == 1: return 'SLEEP3'
        return None
    if count == 2:
        if open_ends == 2: return 'LIVE2'
        if open_ends == 1: return 'SLEEP2'
        return None
    if count == 1:
        if open_ends >= 1: return 'ONE'
        return None
    return None


def _pattern_score(count, open_ends):
    t = _pattern_type(count, open_ends)
    if t == 'WIN': return WIN_SCORE
    if t == 'LIVE4': return FOUR_SCORE
    if t == 'RUSH4': return FOUR_SCORE // 4
    if t == 'LIVE3': return THREE_SCORE
    if t == 'SLEEP3': return THREE_SCORE // 5
    if t == 'LIVE2': return TWO_SCORE
    if t == 'SLEEP2': return TWO_SCORE // 4
    if t == 'ONE': return 10
    return 0


class GomokuAI:
    """Strong Gomoku AI with minimax + VCF threat search + pattern evaluation."""

    def __init__(self, color, depth=6):
        self.color = color
        self.opponent = WHITE if color == BLACK else BLACK
        self.max_depth = max(2, depth)
        self.nodes = 0
        self.max_nodes = 500_000
        self._abort_flag = False

    def abort(self):
        self._abort_flag = True

    def get_move(self, board, time_limit=0):
        self.nodes = 0
        self._abort_flag = False
        deadline = time.time() + time_limit if time_limit > 0 else float('inf')

        piece_count = sum(1 for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY)

        # Fast path: empty board
        if piece_count == 0:
            centers = [(SIZE//2+dr, SIZE//2+dc) for dr in (-1,0,1) for dc in (-1,0,1)]
            return random.choice(centers)

        candidates = self._candidates(board)
        if not candidates:
            return (SIZE // 2, SIZE // 2)

        # 1) Immediate win
        for r, c in candidates:
            board[r][c] = self.color
            if self._is_win(board, r, c, self.color):
                board[r][c] = EMPTY; return (r, c)
            board[r][c] = EMPTY

        # 2) Block opponent win
        blocks = []
        for r, c in candidates:
            board[r][c] = self.opponent
            if self._is_win(board, r, c, self.opponent):
                blocks.append((r, c))
            board[r][c] = EMPTY
        if len(blocks) == 1:
            return blocks[0]

        # 2b) Block opponent live-4 / rush-4
        if not blocks:
            for r, c in candidates:
                board[r][c] = self.opponent
                for dr, dc in DIRS:
                    cnt, oe = _count_run(board, r, c, dr, dc, self.opponent)
                    if cnt == 4 and oe >= 1:
                        blocks.append((r, c))
                        break
                board[r][c] = EMPTY
            if len(blocks) == 1:
                return blocks[0]
            if len(blocks) > 1:
                # Multiple blocks needed — try VCF for counter-play
                pass

        # 3) VCF (Victory by Continuous Four) search
        vcf_move = self._vcf_search(board, 4)
        if vcf_move:
            return vcf_move

        # 4) Block opponent's VCF
        opp = GomokuAI(self.opponent, 2)
        opp_vcf = opp._vcf_search(board, 3)
        if opp_vcf:
            return opp_vcf

        # 5) Iterative deepening minimax
        best_move = candidates[0]
        best_score = -float('inf')
        move_scores = {}
        in_opening = piece_count < 6

        for d in range(2, self.max_depth + 1, 2):
            if self._abort_flag or time.time() > deadline:
                break
            if best_move in candidates:
                candidates.remove(best_move)
                candidates.insert(0, best_move)

            for r, c in candidates:
                if self._abort_flag or time.time() > deadline:
                    break
                board[r][c] = self.color
                if self._is_win(board, r, c, self.color):
                    board[r][c] = EMPTY; return (r, c)
                score = self._minimax(board, d - 1, -float('inf'), float('inf'), False, deadline)
                board[r][c] = EMPTY
                score += random.uniform(-30, 30)
                move_scores[(r, c)] = score
                if score > best_score:
                    best_score = score; best_move = (r, c)

            if best_score >= WIN_SCORE // 2:
                break

        # Randomized selection
        if move_scores:
            scored = sorted(move_scores.items(), key=lambda x: x[1], reverse=True)
            if in_opening:
                top_n = min(5, len(scored))
                top = scored[:top_n]
                if top[0][1] > 0:
                    total = sum(s for _, s in top)
                    weights = [s/total for _, s in top] if total > 0 else None
                else:
                    weights = None
                best_move = random.choices([m for m,_ in top], weights=weights, k=1)[0]
            elif len(scored) >= 2 and abs(scored[0][1] - scored[1][1]) < 300:
                best_move = random.choice(scored[:min(3, len(scored))])[0]
            else:
                best_move = scored[0][0]

        return best_move

    def _candidates(self, board):
        """Candidate moves near existing pieces, sorted by heuristic score."""
        has_any = any(board[r][c] != EMPTY for r in range(SIZE) for c in range(SIZE))
        if not has_any:
            return [(SIZE//2, SIZE//2)]

        cells = set()
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    for dr in range(-3, 4):
                        for dc in range(-3, 4):
                            nr, nc = r+dr, c+dc
                            if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == EMPTY:
                                cells.add((nr, nc))

        scored = []
        for r, c in cells:
            atk = self._cell_score(board, r, c, self.color)
            dfn = self._cell_score(board, r, c, self.opponent)
            scored.append((atk + dfn * 1.25, (r, c)))
        scored.sort(reverse=True)
        return [pos for _, pos in scored[:min(60, len(scored))]]

    def _cell_score(self, board, r, c, player):
        """Score placing 'player' at (r,c)."""
        total = 0
        for dr, dc in DIRS:
            cnt, oe = _count_run(board, r, c, dr, dc, player)
            total += _pattern_score(cnt, oe)
        return total

    def _minimax(self, board, depth, alpha, beta, maximizing, deadline, _rec=0):
        if _rec > 20 or self._abort_flag or time.time() > deadline:
            return self._evaluate(board)
        if depth == 0:
            return self._evaluate(board)

        cands = self._candidates(board)
        if not cands:
            return 0

        n = len(cands)
        if depth <= 2: cands = cands[:min(n, 25)]
        elif depth <= 4: cands = cands[:min(n, 18)]
        else: cands = cands[:min(n, 12)]

        if maximizing:
            best = -float('inf')
            for r, c in cands:
                board[r][c] = self.color
                if self._is_win(board, r, c, self.color):
                    board[r][c] = EMPTY; return WIN_SCORE + depth
                s = self._minimax(board, depth-1, alpha, beta, False, deadline, _rec+1)
                board[r][c] = EMPTY
                if s > best: best = s
                alpha = max(alpha, s)
                if alpha >= beta: break
            return best
        else:
            best = float('inf')
            for r, c in cands:
                board[r][c] = self.opponent
                if self._is_win(board, r, c, self.opponent):
                    board[r][c] = EMPTY; return -(WIN_SCORE + depth)
                s = self._minimax(board, depth-1, alpha, beta, True, deadline, _rec+1)
                board[r][c] = EMPTY
                if s < best: best = s
                beta = min(beta, s)
                if alpha >= beta: break
            return best

    def _is_win(self, board, r, c, player):
        for dr, dc in DIRS:
            cnt, _ = _count_run(board, r, c, dr, dc, player)
            if cnt >= 5: return True
        return False

    def _vcf_search(self, board, max_depth):
        """Threat-space search: look for forced winning sequences starting with a threat.
           Returns the first move of a winning VCF sequence, or None."""
        threats = self._find_all_threats(board, self.color)
        for start_r, start_c in threats:
            board[start_r][start_c] = self.color
            if self._vcf_recurse(board, 1, max_depth, start_r, start_c):
                board[start_r][start_c] = EMPTY
                return (start_r, start_c)
            board[start_r][start_c] = EMPTY
        return None

    def _vcf_recurse(self, board, depth, max_depth, last_r, last_c):
        """Recursive VCF: after playing our threat, can opponent defend all? If not, we win."""
        if depth >= max_depth:
            return False

        # If we have a winning line, we already won
        if self._is_win(board, last_r, last_c, self.color):
            return True

        # Find opponent's defenses (must block all our live-4 / double-threat positions)
        our_threats = self._find_all_threats(board, self.color)
        if not our_threats:
            return False  # no follow-up threat

        # Check if we have a double threat (win)
        live4_count = 0
        live3_count = 0
        for tr, tc in our_threats:
            for dr, dc in DIRS:
                cnt, oe = _count_run(board, tr, tc, dr, dc, self.color)
                if cnt == 4 and oe == 2: live4_count += 1
                if cnt == 3 and oe == 2: live3_count += 1
        if live4_count >= 2 or (live4_count >= 1 and live3_count >= 1):
            return True

        # Opponent tries each defense
        opp_defenses = self._find_all_threats(board, self.opponent)
        # Also need to block our threats
        opp_defenses = list(set(opp_defenses + our_threats[:10]))

        for dr, dc in opp_defenses[:8]:  # limit branching
            if board[dr][dc] != EMPTY: continue
            saved = board[dr][dc]
            board[dr][dc] = self.opponent
            # Can we still force a win?
            follow_ups = self._find_all_threats(board, self.color)
            for fr, fc in follow_ups[:5]:
                if board[fr][fc] != EMPTY: continue
                board[fr][fc] = self.color
                if self._vcf_recurse(board, depth+1, max_depth, fr, fc):
                    board[fr][fc] = EMPTY
                    board[dr][dc] = saved
                    return True
                board[fr][fc] = EMPTY
            board[dr][dc] = saved
        return False

    def _find_all_threats(self, board, player):
        """Find all positions where 'player' can create a live-4, rush-4, or live-3."""
        threats = set()
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY: continue
                has_threat = False
                for dr, dc in DIRS:
                    cnt, oe = _count_run(board, r, c, dr, dc, player)
                    if (cnt == 4 and oe >= 1) or (cnt == 3 and oe == 2):
                        has_threat = True; break
                if has_threat:
                    threats.add((r, c))
        return list(threats)

    def _evaluate(self, board):
        my_score = 0; opp_score = 0
        has = False
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] == self.color:
                    has = True
                    my_score += sum(_pattern_score(*_count_run(board, r, c, dr, dc, self.color)) for dr, dc in DIRS)
                elif board[r][c] == self.opponent:
                    has = True
                    opp_score += sum(_pattern_score(*_count_run(board, r, c, dr, dc, self.opponent)) for dr, dc in DIRS)
        if not has: return 0
        return my_score - opp_score * 1.15 + random.randint(-40, 40)


# ═══════════════════════════ Kifu (棋谱) ═══════════════════════════

class Kifu:
    """Game record for replay."""
    def __init__(self, mode='local', info=''):
        self.mode = mode
        self.info = info
        self.moves = []  # list of (r, c, player, seconds)
        self.result = ''
        self.score = {BLACK: 0, WHITE: 0}
        self.started = time.time()

    def record(self, r, c, player):
        self.moves.append((r, c, player, time.time() - self.started))

    def save(self):
        ts = time.strftime('%Y%m%d_%H%M%S')
        fname = os.path.join(KIFU_DIR, f'kifu_{ts}.json')
        with open(fname, 'w') as f:
            json.dump({
                'mode': self.mode, 'info': self.info, 'moves': self.moves,
                'result': self.result, 'score': self.score,
            }, f, indent=2)
        return fname

    @staticmethod
    def load(fname):
        with open(fname) as f:
            data = json.load(f)
        k = Kifu(data.get('mode', '?'), data.get('info', ''))
        k.moves = data['moves']; k.result = data.get('result', '')
        k.score = data.get('score', {BLACK:0, WHITE:0})
        return k

    @staticmethod
    def list_files():
        if not os.path.exists(KIFU_DIR): return []
        files = sorted(os.listdir(KIFU_DIR), reverse=True)
        return [os.path.join(KIFU_DIR, f) for f in files if f.endswith('.json')]


# ═══════════════════════════ Replay mode ═══════════════════════════

def run_replay(stdscr):
    files = Kifu.list_files()
    if not files:
        rows, cols = stdscr.getmaxyx()
        stdscr.erase()
        m = 'No kifu files found. Play a game first!'
        stdscr.addstr(rows//2, max(0, (cols-len(m))//2), m, curses.A_BOLD)
        stdscr.refresh(); time.sleep(2); return

    # File selector
    idx = 0
    while True:
        rows, cols = stdscr.getmaxyx()
        stdscr.erase()
        m = 'Select kifu (↑↓ move, Enter select, Q back):'
        stdscr.addstr(0, max(0, (cols-len(m))//2), m, curses.A_BOLD)
        for i, f in enumerate(files[:min(20, len(files))]):
            name = os.path.basename(f).replace('.json', '').replace('kifu_', '')
            style = curses.A_REVERSE if i == idx else curses.A_NORMAL
            try:
                stdscr.addstr(2+i, max(0, (cols-len(name))//2), name, style)
            except curses.error: pass
        stdscr.refresh()
        k = stdscr.getch()
        if k == curses.KEY_UP and idx > 0: idx -= 1
        elif k == curses.KEY_DOWN and idx < len(files)-1: idx += 1
        elif k in (10, 13):
            kifu = Kifu.load(files[idx])
            _replay_kifu(stdscr, kifu)
            return
        elif k in (ord('q'), ord('Q'), 27): return


def _replay_kifu(stdscr, kifu):
    board = [[EMPTY]*SIZE for _ in range(SIZE)]
    step = 0
    total = len(kifu.moves)
    cursor = (SIZE//2, SIZE//2)

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        pad.erase()
        y = 0
        pad.addstr(y, 0, f' Replay: {kifu.info}  [{step}/{total}]  ← → navigate  Q quit'.ljust(cols)[:cols-1], curses.A_BOLD)
        y += 2

        # Render board up to step
        board_top = y
        for r in range(SIZE):
            label = f'{chr(ord("A")+r)} '
            pad.addstr(y, 0, label[:cols-1]); x = LABEL_W
            for c in range(SIZE):
                ch = PIECE_CH[board[r][c]]
                cell = ch if c == SIZE-1 else ch + HLINE
                # Highlight last move
                if kifu.moves and step > 0 and (r,c) == (kifu.moves[step-1][0], kifu.moves[step-1][1]):
                    style = curses.color_pair(CP_CURSOR) | curses.A_BOLD
                elif board[r][c] == BLACK:
                    style = curses.color_pair(CP_BLACK) | curses.A_BOLD
                elif board[r][c] == WHITE:
                    style = curses.color_pair(CP_WHITE) | curses.A_BOLD
                else:
                    style = curses.color_pair(CP_BOARD)
                try: pad.addstr(y, x, cell[:cols-x], style)
                except curses.error: pass
                x += CELL_W
            y += 1

        y += 1
        if step < total:
            mr, mc, mp, _ = kifu.moves[step]
            pn = 'Black' if mp==BLACK else 'White'
            pad.addstr(y, 0, f' Next: {PIECE_CH[mp]} {pn} → {chr(ord("A")+mr)}{mc+1}'.ljust(cols)[:cols-1], curses.A_DIM)
        else:
            pad.addstr(y, 0, f' End: {kifu.result}'.ljust(cols)[:cols-1], curses.A_BOLD)
        y += 2
        pad.addstr(y, 0, ' [←] Back  [→] Forward  [Q] Quit'.ljust(cols)[:cols-1], curses.color_pair(CP_BUTTON))
        pad.refresh(0, 0, 0, 0, rows-1, cols-1)

        k = stdscr.getch()
        if k in (ord('q'), ord('Q'), 27): return
        if k in (curses.KEY_LEFT, ord('a')) and step > 0:
            step -= 1; r, c, p, _ = kifu.moves[step]; board[r][c] = EMPTY
        elif k in (curses.KEY_RIGHT, ord('d')) and step < total:
            r, c, p, _ = kifu.moves[step]; board[r][c] = p; step += 1
        elif k in (ord('r'), ord('R')):  # restart replay
            board = [[EMPTY]*SIZE for _ in range(SIZE)]; step = 0
        elif k in (curses.KEY_HOME,): step = 0; board = [[EMPTY]*SIZE for _ in range(SIZE)]
        elif k in (curses.KEY_END,):
            board = [[EMPTY]*SIZE for _ in range(SIZE)]
            for i, (r, c, p, _) in enumerate(kifu.moves): board[r][c] = p
            step = total


# ═══════════════════════════ Persistence ═══════════════════════════

def save_game(board, current, score, history):
    with open(SAVE_FILE, 'w') as f:
        json.dump({'board': board, 'current': current, 'score': score, 'history': history}, f)
    return f'Saved'


def load_game():
    if not os.path.exists(SAVE_FILE): return None
    with open(SAVE_FILE) as f: return json.load(f)


def save_shared(board, current, score, history, black_uid, white_uid):
    data = {'board': board, 'current': current, 'score': score, 'history': history,
            'black_uid': black_uid, 'white_uid': white_uid}
    tmp = SHARED_FILE + '.tmp'
    with open(tmp, 'w') as f: json.dump(data, f)
    os.rename(tmp, SHARED_FILE)


def load_shared():
    if not os.path.exists(SHARED_FILE): return None
    with open(SHARED_FILE) as f: return json.load(f)


def wait_for_turn(stdscr, expected_current):
    while True:
        stdscr.nodelay(1); k = stdscr.getch(); stdscr.nodelay(0)
        if k in (ord('q'), ord('Q'), 27): return None
        data = load_shared()
        if data and data['current'] == expected_current: return data
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32)); pad.erase()
        pch = '●' if expected_current == BLACK else '○'
        pad.addstr(0, 0, f' Gomoku  {pch} Waiting for opponent...'.ljust(cols)[:cols-1],
                   curses.A_BOLD|curses.color_pair(CP_CURSOR))
        pad.addstr(2, 0, ' [Q] Quit'); pad.refresh(0,0,0,0,rows-1,cols-1)
        time.sleep(0.5)


# ═══════════════════════════ Game logic ═══════════════════════════

def in_bounds(r, c): return 0 <= r < SIZE and 0 <= c < SIZE


def find_win(board, r, c):
    p = board[r][c]
    for dr, dc in DIRS:
        cells = [(r, c)]
        for s in (1, -1):
            step = 1
            while True:
                nr, nc = r + dr*step*s, c + dc*step*s
                if in_bounds(nr, nc) and board[nr][nc] == p: cells.append((nr,nc)); step += 1
                else: break
        if len(cells) >= 5: cells.sort(); return cells
    return None


def is_full(board):
    for row in board:
        if EMPTY in row: return False
    return True


# ═══════════════════════════ Coordinate mapping ═══════════════════════════

def screen_to_board(scr_row, scr_col, board_top):
    r = scr_row - board_top
    if not (0 <= r < SIZE): return None
    for c in range(SIZE):
        left = LABEL_W + c*CELL_W; right = left + 1
        if left <= scr_col <= right: return (r, c)
    return None


def screen_to_button(scr_row, scr_col, btn_row):
    if abs(scr_row - btn_row) > 1: return None
    for name, (lx, rx) in BTN_MAP.items():
        if lx <= scr_col <= rx: return name
    return None


# ═══════════════════════════ Drawing ═══════════════════════════

def draw(pad, board, cursor, current, msg, cols, win_cells=None, score=None, status=''):
    pad.erase(); y = 0
    pch = PIECE_CH[current]; pname = 'Black' if current == BLACK else 'White'
    title = f' Gomoku    {pch} {pname}'
    if score: title += f'      Score:  ● {score[BLACK]}  -  ○ {score[WHITE]}'
    if status: title += f'    {status}'
    pad.addstr(y, 0, title[:cols-1], curses.A_BOLD); y += 1
    hint = ' [Click/Space] Place  [WASD] Move  [S] Save  [U] Undo  [Q] Quit'
    pad.addstr(y, 0, hint[:cols-1], curses.A_DIM); y += 2
    board_top = y

    for r in range(SIZE):
        label = f'{chr(ord("A")+r)} '
        pad.addstr(y, 0, label[:cols-1]); x = LABEL_W
        for c in range(SIZE):
            ch = PIECE_CH[board[r][c]]; cell = ch if c == SIZE-1 else ch + HLINE
            if win_cells and (r,c) in win_cells: style = curses.color_pair(CP_WIN)|curses.A_BOLD
            elif (r,c) == cursor: style = curses.color_pair(CP_CURSOR)|curses.A_BOLD
            elif board[r][c] == BLACK: style = curses.color_pair(CP_BLACK)|curses.A_BOLD
            elif board[r][c] == WHITE: style = curses.color_pair(CP_WHITE)|curses.A_BOLD
            else: style = curses.color_pair(CP_BOARD)
            try: pad.addstr(y, x, cell[:cols-x], style)
            except curses.error: pass
            x += CELL_W
        y += 1

    y += 1; btn_row = y
    pad.addstr(y, 0, BTN_TEXT[:cols-1], curses.color_pair(CP_BUTTON)); y += 1
    if msg: y += 1; pad.addstr(y, 0, ' '+msg[:cols-2], curses.A_BOLD)
    return board_top, btn_row


def win_flash(pad, board, cursor, current, win_cells, score, cols, rows):
    for i in range(6):
        draw(pad, board, cursor, current, '', cols,
             win_cells=win_cells if i%2==0 else None, score=score)
        pad.refresh(0, 0, 0, 0, rows-1, cols-1); time.sleep(0.15)
    pch = PIECE_CH[current]; winner = 'Black' if current==BLACK else 'White'
    msg = f' {pch} {pch} {pch}  {winner} WINS!  {pch} {pch} {pch}'
    _, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score)
    pad.refresh(0, 0, 0, 0, rows-1, cols-1); return br


def endgame_loop(stdscr, board, cursor, current, win_cells, score, cols):
    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        pch = PIECE_CH[current]; winner = 'Black' if current==BLACK else 'White'
        m = f'{pch} {winner} WINS!  ● {score[BLACK]} - ○ {score[WHITE]}   [Restart] or [Quit]'
        _, br = draw(pad, board, cursor, current, m, cols, win_cells=win_cells, score=score)
        pad.refresh(0, 0, 0, 0, rows-1, cols-1)
        k = stdscr.getch()
        if k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bs = curses.getmouse()
                if bs & (curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                    b = screen_to_button(my, mx, br)
                    if b == 'restart': return 'restart'
                    if b == 'quit': return 'quit'
            except Exception: pass
        elif k in (ord('r'), ord('R')): return 'restart'
        elif k in (ord('q'), ord('Q'), 27): return 'quit'


# ═══════════════════════════ Menu ═══════════════════════════

def show_menu(stdscr):
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
        y = max(0, (rows-len(menu))//2); x = max(0, (cols-28)//2)
        for i, line in enumerate(menu):
            try: stdscr.addstr(y+i, x, line, curses.color_pair(CP_MENU)|curses.A_BOLD)
            except curses.error: pass
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
    color_choice = None; diff_choice = None
    while True:
        stdscr.erase()
        y = max(0, (rows-len(menu))//2); x = max(0, (cols-28)//2)
        for i, line in enumerate(menu):
            try: stdscr.addstr(y+i, x, line, curses.color_pair(CP_MENU))
            except curses.error: pass
        sel = ''
        if color_choice: sel += f'Color: {color_choice}  '
        if diff_choice: sel += f'Difficulty: {diff_choice}'
        if sel:
            try: stdscr.addstr(y+len(menu), x, sel[:cols-x], curses.A_BOLD)
            except curses.error: pass
        stdscr.refresh()
        k = stdscr.getch()
        if k in (ord('b'), ord('B')): color_choice = 'Black'
        if k in (ord('w'), ord('W')): color_choice = 'White'
        if k in (ord('1'),): diff_choice = ('Easy', 4)
        if k in (ord('2'),): diff_choice = ('Medium', 6)
        if k in (ord('3'),): diff_choice = ('Hard', 8)
        if k in (ord('q'), ord('Q'), 27): return None, None
        if color_choice and diff_choice and k in (10, 13): return color_choice, diff_choice


def show_eve_menu(stdscr):
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
    b_depth=4; w_depth=4; b_label='Medium'; w_label='Medium'
    while True:
        stdscr.erase()
        y = max(0,(rows-len(menu))//2); x = max(0,(cols-28)//2)
        for i, line in enumerate(menu):
            try: stdscr.addstr(y+i, x, line, curses.color_pair(CP_MENU))
            except curses.error: pass
        info = f'Black={b_label}  White={w_label}'
        try: stdscr.addstr(y+len(menu), x, info[:cols-x], curses.A_BOLD)
        except curses.error: pass
        stdscr.refresh()
        k = stdscr.getch()
        if k in (ord('1'),): b_depth,b_label = 2,'Easy'
        if k in (ord('2'),): b_depth,b_label = 4,'Medium'
        if k in (ord('3'),): b_depth,b_label = 6,'Hard'
        if k in (ord('4'),): w_depth,w_label = 2,'Easy'
        if k in (ord('5'),): w_depth,w_label = 4,'Medium'
        if k in (ord('6'),): w_depth,w_label = 6,'Hard'
        if k in (ord('q'),ord('Q'),27): return None,None
        if k in (10,13): return b_depth,w_depth


# ═══════════════════════════ Local game ═══════════════════════════

def run_local(stdscr, initial=None):
    if initial:
        board = initial['board']; history = initial.get('history',[])
        current = initial['current']
        score = {BLACK: initial['score'].get(str(BLACK),0), WHITE: initial['score'].get(str(WHITE),0)}
        msg = 'Loaded!'
    else:
        board = [[EMPTY]*SIZE for _ in range(SIZE)]; history = []
        current = BLACK; score = {BLACK:0, WHITE:0}; msg = ''
    cursor = (SIZE//2, SIZE//2); win_cells = None
    kifu = Kifu('local', 'Two-player local game')

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score)
        msg=''; win_cells=None; pad.refresh(0,0,0,0,rows-1,cols-1)
        key = stdscr.getch()

        if key == curses.KEY_MOUSE:
            try: _,mx,my,_,bs = curses.getmouse()
            except Exception: continue
            if bs & (curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                btn = screen_to_button(my,mx,br)
                if btn=='quit': kifu.result='quit'; kifu.score=score; kifu.save(); return
                if btn=='restart':
                    kifu.save(); board=[[EMPTY]*SIZE for _ in range(SIZE)]
                    history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                    msg='New game!'; kifu=Kifu('local','Two-player local game'); continue
                if btn=='undo':
                    if history: r,c,prev=history.pop(); board[r][c]=EMPTY; current=prev; cursor=(r,c); msg='Undone'
                    else: msg='Nothing to undo'
                    continue
                if btn=='save': msg=save_game(board,current,score,history); continue
                pos = screen_to_board(my,mx,bt)
                if pos is not None:
                    r,c=pos
                    if board[r][c]==EMPTY:
                        history.append((r,c,current)); board[r][c]=current; cursor=(r,c)
                        kifu.record(r,c,current)
                        wc=find_win(board,r,c)
                        if wc:
                            score[current]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                            winner='Black' if current==BLACK else 'White'
                            kifu.result=f'{winner} wins'; kifu.score=score; kifu.save()
                            win_flash(p2,board,cursor,current,wc,score,c2,r2)
                            act=endgame_loop(stdscr,board,cursor,current,wc,score,c2)
                            if act=='restart':
                                board=[[EMPTY]*SIZE for _ in range(SIZE)]
                                history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                                msg='New game!'; kifu=Kifu('local'); continue
                            else: return
                        elif is_full(board): msg='Draw!'; continue
                        else: current=WHITE if current==BLACK else BLACK
                    else: cursor=(r,c); msg='Occupied'
            continue

        if key in (ord('q'),ord('Q'),27): kifu.save(); return
        if key in (ord('r'),ord('R')):
            kifu.save(); board=[[EMPTY]*SIZE for _ in range(SIZE)]
            history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
            msg='New game!'; kifu=Kifu('local'); continue
        if key in (ord('u'),ord('U')):
            if history: r,c,prev=history.pop(); board[r][c]=EMPTY; current=prev; cursor=(r,c); msg='Undone'
            else: msg='Nothing to undo'
            continue
        if key in (ord('s'),ord('S')): msg=save_game(board,current,score,history); continue
        if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
        elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
        elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
        elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
        elif key in (curses.KEY_ENTER,10,13,ord(' ')):
            r,c=cursor
            if board[r][c]==EMPTY:
                history.append((r,c,current)); board[r][c]=current; kifu.record(r,c,current)
                wc=find_win(board,r,c)
                if wc:
                    score[current]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                    winner='Black' if current==BLACK else 'White'
                    kifu.result=f'{winner} wins'; kifu.score=score; kifu.save()
                    win_flash(p2,board,cursor,current,wc,score,c2,r2)
                    act=endgame_loop(stdscr,board,cursor,current,wc,score,c2)
                    if act=='restart':
                        board=[[EMPTY]*SIZE for _ in range(SIZE)]
                        history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                        msg='New game!'; kifu=Kifu('local'); continue
                    else: return
                elif is_full(board): msg='Draw!'; continue
                else: current=WHITE if current==BLACK else BLACK
            else: msg='Occupied'


# ═══════════════════════════ Player vs AI ═══════════════════════════

def run_pve(stdscr):
    color_name, (diff_name, depth) = show_pve_menu(stdscr)
    if not color_name: return

    human_color = BLACK if color_name=='Black' else WHITE
    ai_color = WHITE if human_color==BLACK else BLACK
    ai = GomokuAI(ai_color, depth)

    board = [[EMPTY]*SIZE for _ in range(SIZE)]; history = []
    cursor = (SIZE//2, SIZE//2); current = BLACK
    score = {BLACK:0, WHITE:0}; msg = f'You: {color_name}  AI: {diff_name}'
    win_cells = None
    kifu = Kifu('pve', f'Human({color_name}) vs AI({diff_name}, depth {depth})')
    ai_thread = [None]
    ai_result = [None]

    def ai_worker(b):
        try: ai_result[0] = ai.get_move(b, time_limit=15)
        except Exception: ai_result[0] = None

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        status = 'Your turn' if current==human_color else 'AI thinking...'
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        msg=''; win_cells=None

        if current == ai_color:
            pad.refresh(0,0,0,0,rows-1,cols-1)
            # Run AI in thread; main thread polls for Q
            ai_result[0] = None
            ai_thread[0] = threading.Thread(target=ai_worker, args=([row[:] for row in board],), daemon=True)
            ai_thread[0].start()

            while ai_thread[0].is_alive():
                k = stdscr.getch()
                if k in (ord('q'), ord('Q'), 27):
                    ai.abort()
                    ai_thread[0].join(timeout=1)
                    kifu.result='quit'; kifu.score=score; kifu.save()
                    return
                ai_thread[0].join(timeout=0.1)

            move = ai_result[0]
            if move:
                r, c = move
                if board[r][c]==EMPTY:
                    board[r][c]=ai_color; cursor=(r,c); kifu.record(r,c,ai_color)
                    wc=find_win(board,r,c)
                    if wc:
                        score[ai_color]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        kifu.result=f'AI wins'; kifu.score=score; kifu.save()
                        win_flash(p2,board,cursor,ai_color,wc,score,c2,r2)
                        pch=PIECE_CH[ai_color]; m=f'{pch} AI WINS!  [R] Restart  [Q] Quit'
                        act=endgame_loop(stdscr,board,cursor,ai_color,wc,score,c2)
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                            cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                            kifu=Kifu('pve',f'Human({color_name}) vs AI({diff_name})'); continue
                        else: return
                    elif is_full(board): msg='Draw!'; continue
                    else: current=human_color
            continue

        pad.refresh(0,0,0,0,rows-1,cols-1)
        key = stdscr.getch()

        if key == curses.KEY_MOUSE:
            try: _,mx,my,_,bs = curses.getmouse()
            except Exception: continue
            if bs & (curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                btn = screen_to_button(my,mx,br)
                if btn=='quit': kifu.result='quit'; kifu.score=score; kifu.save(); return
                if btn=='restart':
                    kifu.save(); board=[[EMPTY]*SIZE for _ in range(SIZE)]
                    history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
                    msg='New game!'; kifu=Kifu('pve',f'Human({color_name}) vs AI({diff_name})'); continue
                if btn=='undo':
                    if len(history)>=2:
                        for _ in range(2): r2,c2,p2=history.pop(); board[r2][c2]=EMPTY
                        current=human_color; cursor=(r2,c2); msg='Undone (2 moves)'
                    elif history: r2,c2,p2=history.pop(); board[r2][c2]=EMPTY; current=human_color; cursor=(r2,c2); msg='Undone'
                    else: msg='Nothing to undo'
                    continue
                pos = screen_to_board(my,mx,bt)
                if pos is not None and board[pos[0]][pos[1]]==EMPTY:
                    r,c=pos; history.append((r,c,human_color)); board[r][c]=human_color; cursor=(r,c)
                    kifu.record(r,c,human_color)
                    wc=find_win(board,r,c)
                    if wc:
                        score[human_color]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        kifu.result=f'Human wins'; kifu.score=score; kifu.save()
                        win_flash(p2,board,cursor,human_color,wc,score,c2,r2)
                        pch=PIECE_CH[human_color]; m=f'{pch} You WIN!  [R] Restart  [Q] Quit'
                        act=endgame_loop(stdscr,board,cursor,human_color,wc,score,c2)
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                            cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                            kifu=Kifu('pve',f'Human({color_name}) vs AI({diff_name})'); continue
                        else: return
                    elif is_full(board): msg='Draw!'; continue
                    else: current=ai_color
                elif pos is not None: cursor=pos; msg='Occupied'
            continue

        if key in (ord('q'),ord('Q'),27): kifu.save(); return
        if key in (ord('r'),ord('R')):
            kifu.save(); board=[[EMPTY]*SIZE for _ in range(SIZE)]
            history.clear(); cursor=(SIZE//2,SIZE//2); current=BLACK
            msg='New game!'; kifu=Kifu('pve',f'Human({color_name}) vs AI({diff_name})'); continue
        if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
        elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
        elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
        elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
        elif key in (curses.KEY_ENTER,10,13,ord(' ')):
            r,c=cursor
            if board[r][c]==EMPTY:
                history.append((r,c,human_color)); board[r][c]=human_color; kifu.record(r,c,human_color)
                wc=find_win(board,r,c)
                if wc:
                    score[human_color]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                    kifu.result=f'Human wins'; kifu.score=score; kifu.save()
                    win_flash(p2,board,cursor,human_color,wc,score,c2,r2)
                    pch=PIECE_CH[human_color]; m=f'{pch} You WIN!  [R] Restart  [Q] Quit'
                    act=endgame_loop(stdscr,board,cursor,human_color,wc,score,c2)
                    if act=='restart':
                        board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                        cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                        kifu=Kifu('pve',f'Human({color_name}) vs AI({diff_name})'); continue
                    else: return
                elif is_full(board): msg='Draw!'; continue
                else: current=ai_color
            else: msg='Occupied'


# ═══════════════════════════ AI vs AI ═══════════════════════════

def run_eve(stdscr):
    b_depth, w_depth = show_eve_menu(stdscr)
    if not b_depth: return
    b_depth = min(b_depth, 6); w_depth = min(w_depth, 6)

    black_ai = GomokuAI(BLACK, b_depth); white_ai = GomokuAI(WHITE, w_depth)
    board = [[EMPTY]*SIZE for _ in range(SIZE)]
    current = BLACK; score = {BLACK:0, WHITE:0}
    msg = f'Q=QUIT | Black(d{b_depth}) vs White(d{w_depth})'
    win_cells = None; cursor = (SIZE//2, SIZE//2)
    kifu = Kifu('eve', f'AI battle: Black(d{b_depth}) vs White(d{w_depth})')
    ai_thread = [None]; ai_result = [None]

    def ai_worker(b, ai_obj):
        try: ai_result[0] = ai_obj.get_move(b, time_limit=12)
        except Exception: ai_result[0] = None

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        ai_obj = black_ai if current==BLACK else white_ai
        status = f'AI ({"Black" if current==BLACK else "White"}) thinking... Q=quit'
        draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        pad.refresh(0,0,0,0,rows-1,cols-1)
        msg=''; win_cells=None

        # Run AI in thread; poll for Q
        ai_result[0] = None
        ai_thread[0] = threading.Thread(target=ai_worker, args=([row[:] for row in board], ai_obj), daemon=True)
        ai_thread[0].start()

        while ai_thread[0].is_alive():
            k = stdscr.getch()
            if k in (ord('q'), ord('Q'), 27):
                ai_obj.abort()
                ai_thread[0].join(timeout=1)
                kifu.result='quit'; kifu.score=score; kifu.save()
                return
            ai_thread[0].join(timeout=0.1)

        move = ai_result[0]
        if move:
            r, c = move
            if board[r][c]==EMPTY:
                board[r][c]=current; cursor=(r,c); kifu.record(r,c,current)
                wc=find_win(board,r,c)
                if wc:
                    score[current]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                    winner='Black AI' if current==BLACK else 'White AI'
                    kifu.result=f'{winner} wins'; kifu.score=score; kifu.save()
                    win_flash(p2,board,cursor,current,wc,score,c2,r2)
                    pch=PIECE_CH[current]; m=f'{pch} {winner} WINS!  [R] Restart  [Q] Quit'
                    act=endgame_loop(stdscr,board,cursor,current,wc,score,c2)
                    if act=='restart':
                        board=[[EMPTY]*SIZE for _ in range(SIZE)]; cursor=(SIZE//2,SIZE//2)
                        current=BLACK; msg='New game!'; kifu=Kifu('eve','AI battle'); continue
                    else: return
                elif is_full(board): msg='Draw!'; continue
                else: current=WHITE if current==BLACK else BLACK


# ═══════════════════════════ Network helpers ═══════════════════════════

def recv_move(sock, timeout=0.1):
    ready,_,_ = select.select([sock],[],[],timeout)
    if ready:
        data = sock.recv(1024)
        if data:
            try: return tuple(map(int, data.decode().strip().split(',')))
            except Exception: return None
    return None


def send_move(sock, r, c): sock.sendall(f'{r},{c}'.encode())


def recv_all(sock, timeout=0.1):
    ready,_,_ = select.select([sock],[],[],timeout)
    if ready: return sock.recv(4096).decode()
    return None


def show_ip_screen(stdscr, port):
    socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8',80))
        ip = s.getsockname()[0]; s.close()
    except Exception: ip = '?.?.?.?'
    rows, cols = stdscr.getmaxyx(); stdscr.erase()
    for i, line in enumerate([
        'Waiting for opponent to connect...', '',
        f'  Your IP:   {ip}', f'  Port:      {port}', '',
        '  Press Q to cancel',
    ]):
        try: stdscr.addstr(rows//2-3+i, max(0,(cols-len(line))//2), line, curses.A_BOLD)
        except curses.error: pass
    stdscr.refresh(); return ip


def show_join_screen(stdscr):
    curses.echo(); curses.curs_set(1)
    rows, cols = stdscr.getmaxyx(); ip = ''
    while True:
        stdscr.erase(); msg = 'Enter host IP address: '
        stdscr.addstr(rows//2, max(0,(cols-len(msg)-len(ip))//2), msg+ip); stdscr.refresh()
        k = stdscr.getch()
        if k in (10,13): break
        if k in (27,): curses.noecho(); curses.curs_set(0); return None
        if k in (curses.KEY_BACKSPACE,127,8): ip=ip[:-1]
        elif 32<=k<=126: ip+=chr(k)
    curses.noecho(); curses.curs_set(0)
    return ip.strip() or None


# ═══════════════════════════ Network modes ═══════════════════════════

def run_host(stdscr):
    port = DEFAULT_PORT
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port)); server.listen(1); server.setblocking(False)
    show_ip_screen(stdscr, port)
    while True:
        k = stdscr.getch()
        if k in (ord('q'),ord('Q'),27): server.close(); return
        try: client,_ = server.accept(); break
        except BlockingIOError: continue
    server.close()

    board = [[EMPTY]*SIZE for _ in range(SIZE)]; history = []
    cursor = (SIZE//2, SIZE//2); current = BLACK
    score = {BLACK:0, WHITE:0}; msg = 'Connected! You are ● Black'
    win_cells = None; my_turn = True
    kifu = Kifu('host', 'Network game - host (Black)')

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        status = 'Your turn' if my_turn else "Opponent's turn"
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        msg=''; win_cells=None; pad.refresh(0,0,0,0,rows-1,cols-1)

        if my_turn:
            key = stdscr.getch()
            if key == curses.KEY_MOUSE:
                try: _,mx,my,_,bs = curses.getmouse()
                except Exception: continue
                if bs & (curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                    btn = screen_to_button(my,mx,br)
                    if btn=='quit': client.close(); kifu.save(); return
                    pos = screen_to_board(my,mx,bt)
                    if pos is not None and board[pos[0]][pos[1]]==EMPTY:
                        r,c=pos; board[r][c]=BLACK; history.append((r,c,BLACK)); cursor=(r,c)
                        send_move(client,r,c); kifu.record(r,c,BLACK)
                        wc=find_win(board,r,c)
                        if wc:
                            score[BLACK]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                            kifu.result='Black wins'; kifu.score=score; kifu.save()
                            win_flash(p2,board,cursor,BLACK,wc,score,c2,r2)
                            act=endgame_loop(stdscr,board,cursor,BLACK,wc,score,c2); client.close()
                            if act=='restart':
                                board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                                cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                                my_turn=True; kifu=Kifu('host'); continue
                            else: return
                        elif is_full(board): msg='Draw!'; continue
                        my_turn=False; continue
                continue
            if key in (ord('q'),ord('Q'),27): client.close(); kifu.save(); return
            if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
            elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
            elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
            elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
            elif key in (curses.KEY_ENTER,10,13,ord(' ')):
                r,c=cursor
                if board[r][c]==EMPTY:
                    board[r][c]=BLACK; history.append((r,c,BLACK)); send_move(client,r,c); kifu.record(r,c,BLACK)
                    wc=find_win(board,r,c)
                    if wc:
                        score[BLACK]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        kifu.result='Black wins'; kifu.score=score; kifu.save()
                        win_flash(p2,board,cursor,BLACK,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,BLACK,wc,score,c2); client.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                            cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                            my_turn=True; kifu=Kifu('host'); continue
                        else: return
                    elif is_full(board): msg='Draw!'; continue
                    my_turn=False
        else:
            move = recv_move(client, timeout=0.3)
            if move is not None:
                r,c=move
                if board[r][c]==EMPTY:
                    board[r][c]=WHITE; cursor=(r,c); kifu.record(r,c,WHITE)
                    wc=find_win(board,r,c)
                    if wc:
                        score[WHITE]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        kifu.result='White wins'; kifu.score=score; kifu.save()
                        win_flash(p2,board,cursor,WHITE,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,WHITE,wc,score,c2); client.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                            cursor=(SIZE//2,SIZE//2); current=BLACK; msg='New game!'
                            my_turn=True; kifu=Kifu('host'); continue
                        else: return
                    my_turn=True; continue
            data = recv_all(client, timeout=0.05)
            if data=='QUIT': msg='Opponent disconnected'; client.close(); time.sleep(1); return
            stdscr.nodelay(1); k=stdscr.getch(); stdscr.nodelay(0)
            if k in (ord('q'),ord('Q'),27): send_move(client,-1,-1); client.close(); return


def run_join(stdscr):
    ip = show_join_screen(stdscr)
    if not ip: return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.settimeout(3)
    try: sock.connect((ip, DEFAULT_PORT))
    except Exception as e:
        rows, cols = stdscr.getmaxyx(); stdscr.erase()
        m = f'Could not connect: {e}'; stdscr.addstr(rows//2, max(0,(cols-len(m))//2), m)
        stdscr.refresh(); time.sleep(2); return

    board = [[EMPTY]*SIZE for _ in range(SIZE)]; history = []
    cursor = (SIZE//2, SIZE//2); current = WHITE
    score = {BLACK:0, WHITE:0}; msg = 'Connected! You are ○ White'
    win_cells = None; my_turn = False
    kifu = Kifu('join', 'Network game - client (White)')

    while True:
        rows, cols = stdscr.getmaxyx()
        pad = curses.newpad(rows+40, max(cols,32))
        status = 'Your turn' if my_turn else "Opponent's turn"
        bt, br = draw(pad, board, cursor, current, msg, cols, win_cells=win_cells, score=score, status=status)
        msg=''; win_cells=None; pad.refresh(0,0,0,0,rows-1,cols-1)

        if my_turn:
            key = stdscr.getch()
            if key == curses.KEY_MOUSE:
                try: _,mx,my,_,bs = curses.getmouse()
                except Exception: continue
                if bs & (curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                    btn = screen_to_button(my,mx,br)
                    if btn=='quit': sock.sendall(b'QUIT'); sock.close(); kifu.save(); return
                    pos = screen_to_board(my,mx,bt)
                    if pos is not None and board[pos[0]][pos[1]]==EMPTY:
                        r,c=pos; board[r][c]=WHITE; history.append((r,c,WHITE)); cursor=(r,c)
                        send_move(sock,r,c); kifu.record(r,c,WHITE)
                        wc=find_win(board,r,c)
                        if wc:
                            score[WHITE]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                            kifu.result='White wins'; kifu.score=score; kifu.save()
                            win_flash(p2,board,cursor,WHITE,wc,score,c2,r2)
                            act=endgame_loop(stdscr,board,cursor,WHITE,wc,score,c2); sock.close()
                            if act=='restart':
                                board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                                cursor=(SIZE//2,SIZE//2); current=WHITE; msg='New game!'
                                my_turn=False; kifu=Kifu('join'); continue
                            else: return
                        elif is_full(board): msg='Draw!'; continue
                        my_turn=False; continue
                continue
            if key in (ord('q'),ord('Q'),27): sock.sendall(b'QUIT'); sock.close(); kifu.save(); return
            if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
            elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
            elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
            elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
            elif key in (curses.KEY_ENTER,10,13,ord(' ')):
                r,c=cursor
                if board[r][c]==EMPTY:
                    board[r][c]=WHITE; history.append((r,c,WHITE)); send_move(sock,r,c); kifu.record(r,c,WHITE)
                    wc=find_win(board,r,c)
                    if wc:
                        score[WHITE]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        kifu.result='White wins'; kifu.score=score; kifu.save()
                        win_flash(p2,board,cursor,WHITE,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,WHITE,wc,score,c2); sock.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                            cursor=(SIZE//2,SIZE//2); current=WHITE; msg='New game!'
                            my_turn=False; kifu=Kifu('join'); continue
                        else: return
                    elif is_full(board): msg='Draw!'; continue
                    my_turn=False
        else:
            move = recv_move(sock, timeout=0.3)
            if move is not None:
                r,c=move
                if r<0: msg='Opponent quit'; sock.close(); time.sleep(1); return
                if board[r][c]==EMPTY:
                    board[r][c]=BLACK; cursor=(r,c); kifu.record(r,c,BLACK)
                    wc=find_win(board,r,c)
                    if wc:
                        score[BLACK]+=1; r2,c2=stdscr.getmaxyx(); p2=curses.newpad(r2+40,max(c2,32))
                        kifu.result='Black wins'; kifu.score=score; kifu.save()
                        win_flash(p2,board,cursor,BLACK,wc,score,c2,r2)
                        act=endgame_loop(stdscr,board,cursor,BLACK,wc,score,c2); sock.close()
                        if act=='restart':
                            board=[[EMPTY]*SIZE for _ in range(SIZE)]; history.clear()
                            cursor=(SIZE//2,SIZE//2); current=WHITE; msg='New game!'
                            my_turn=False; kifu=Kifu('join'); continue
                        else: return
                    my_turn=True; continue
            data = recv_all(sock, timeout=0.05)
            if data=='QUIT': msg='Opponent disconnected'; sock.close(); time.sleep(1); return
            stdscr.nodelay(1); k=stdscr.getch(); stdscr.nodelay(0)
            if k in (ord('q'),ord('Q'),27): sock.sendall(b'QUIT'); sock.close(); return


# ═══════════════════════════ Shared mode ═══════════════════════════

def run_shared(stdscr):
    my_uid = os.getuid(); data = load_shared()
    if data is None:
        board = [[EMPTY]*SIZE for _ in range(SIZE)]; history = []
        current = BLACK; score = {BLACK:0, WHITE:0}
        my_color = BLACK; black_uid = my_uid; white_uid = None
        save_shared(board, current, score, history, black_uid, white_uid)
        msg = 'New shared game! You are ● Black.'
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
    kifu = Kifu('shared', 'Shared file game')

    while True:
        data = load_shared()
        if data is None: msg='Shared file deleted.'; time.sleep(1); return
        current = data['current']
        score = {BLACK: data['score'].get(str(BLACK),0), WHITE: data['score'].get(str(WHITE),0)}

        if current != my_color:
            data = wait_for_turn(stdscr, my_color)
            if data is None: kifu.save(); return
            board = data['board']; current = data['current']
            score = {BLACK: data['score'].get(str(BLACK),0), WHITE: data['score'].get(str(WHITE),0)}
            history = data.get('history',[]); msg = "Opponent moved!"
            continue

        rows,cols=stdscr.getmaxyx(); pad=curses.newpad(rows+40,max(cols,32))
        bt,br=draw(pad,board,cursor,my_color,msg,cols,win_cells=win_cells,score=score,status='Your turn')
        msg=''; win_cells=None; pad.refresh(0,0,0,0,rows-1,cols-1)
        key=stdscr.getch()
        if key==curses.KEY_MOUSE:
            try: _,mx,my,_,bs=curses.getmouse()
            except Exception: continue
            if bs&(curses.BUTTON1_CLICKED|curses.BUTTON1_PRESSED):
                btn=screen_to_button(my,mx,br)
                if btn=='quit': kifu.save(); return
                if btn=='restart':
                    if my_color==BLACK:
                        board=[[EMPTY]*SIZE for _ in range(SIZE)]; history=[]; cursor=(SIZE//2,SIZE//2)
                        save_shared(board,BLACK,score,history,black_uid,white_uid); msg='New game!'
                        kifu=Kifu('shared'); continue
                    else: msg='Only Black can restart'
                    continue
                pos=screen_to_board(my,mx,bt)
                if pos is not None and board[pos[0]][pos[1]]==EMPTY:
                    r,c=pos; history.append((r,c,my_color)); board[r][c]=my_color; cursor=(r,c)
                    kifu.record(r,c,my_color)
                    wc=find_win(board,r,c)
                    if wc:
                        score[my_color]+=1; nxt=WHITE if my_color==BLACK else BLACK
                        save_shared(board,nxt,score,history,black_uid,white_uid)
                        kifu.result=f'{"Black" if my_color==BLACK else "White"} wins'; kifu.save()
                        continue
                    elif is_full(board): msg='Draw!'; continue
                    else:
                        nxt=WHITE if my_color==BLACK else BLACK
                        save_shared(board,nxt,score,history,black_uid,white_uid)
                        msg='Move sent.'; continue
                elif pos is not None: cursor=pos; msg='Occupied'
            continue
        if key in (ord('q'),ord('Q'),27): kifu.save(); return
        if key in (ord('r'),ord('R')):
            if my_color==BLACK:
                board=[[EMPTY]*SIZE for _ in range(SIZE)]; history=[]; cursor=(SIZE//2,SIZE//2)
                save_shared(board,BLACK,score,history,black_uid,white_uid); msg='New game!'
                kifu=Kifu('shared'); continue
            else: msg='Only Black can restart'; continue
        if key in (ord('w'),curses.KEY_UP) and cursor[0]>0: cursor=(cursor[0]-1,cursor[1])
        elif key in (ord('s'),curses.KEY_DOWN) and cursor[0]<SIZE-1: cursor=(cursor[0]+1,cursor[1])
        elif key in (ord('a'),curses.KEY_LEFT) and cursor[1]>0: cursor=(cursor[0],cursor[1]-1)
        elif key in (ord('d'),curses.KEY_RIGHT) and cursor[1]<SIZE-1: cursor=(cursor[0],cursor[1]+1)
        elif key in (curses.KEY_ENTER,10,13,ord(' ')):
            r,c=cursor
            if board[r][c]==EMPTY:
                history.append((r,c,my_color)); board[r][c]=my_color; kifu.record(r,c,my_color)
                wc=find_win(board,r,c)
                if wc:
                    score[my_color]+=1; nxt=WHITE if my_color==BLACK else BLACK
                    save_shared(board,nxt,score,history,black_uid,white_uid)
                    kifu.result=f'{"Black" if my_color==BLACK else "White"} wins'; kifu.save()
                    continue
                elif is_full(board): msg='Draw!'; continue
                else:
                    nxt=WHITE if my_color==BLACK else BLACK
                    save_shared(board,nxt,score,history,black_uid,white_uid); msg='Move sent.'; continue
            else: msg='Occupied'


# ═══════════════════════════ Entry ═══════════════════════════

def main(stdscr):
    curses.start_color(); curses.use_default_colors()
    curses.curs_set(0); stdscr.nodelay(0); stdscr.keypad(1)
    curses.init_pair(CP_BOARD, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_BLACK, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(CP_WHITE, curses.COLOR_WHITE, curses.COLOR_YELLOW)
    curses.init_pair(CP_CURSOR, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(CP_BUTTON, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(CP_WIN, curses.COLOR_BLACK, curses.COLOR_RED)
    curses.init_pair(CP_MENU, curses.COLOR_WHITE, curses.COLOR_BLUE)
    try: curses.mousemask(curses.ALL_MOUSE_EVENTS)
    except Exception: pass

    while True:
        choice = show_menu(stdscr)
        if choice == 'local': run_local(stdscr)
        elif choice == 'host': run_host(stdscr)
        elif choice == 'join': run_join(stdscr)
        elif choice == 'shared': run_shared(stdscr)
        elif choice == 'pve': run_pve(stdscr)
        elif choice == 'eve': run_eve(stdscr)
        elif choice == 'replay': run_replay(stdscr)
        elif choice == 'load':
            data = load_game()
            if data: run_local(stdscr, initial=data)
            else:
                rows, cols = stdscr.getmaxyx(); stdscr.erase()
                m = 'No saved game found.'
                stdscr.addstr(rows//2, max(0,(cols-len(m))//2), m, curses.A_BOLD)
                stdscr.refresh(); time.sleep(1.5)
        elif choice == 'quit': break


if __name__ == '__main__':
    try: curses.wrapper(main)
    except KeyboardInterrupt: pass
    except Exception as e: print(f'Error: {e}'); raise
