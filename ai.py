"""Gomoku AI engine: minimax + alpha-beta + VCF threat search."""

import random
import time

from .constants import SIZE, EMPTY, BLACK, WHITE, DIRS
from .constants import WIN_SCORE, FOUR_SCORE, THREE_SCORE, TWO_SCORE


def _count_run(board, r, c, dr, dc, player):
    """Count consecutive pieces and open ends."""
    count = 1
    open_ends = 0
    for sign in (1, -1):
        step = 1
        while True:
            nr, nc = r + dr * step * sign, c + dc * step * sign
            if 0 <= nr < SIZE and 0 <= nc < SIZE:
                if board[nr][nc] == player:
                    count += 1
                    step += 1
                else:
                    if board[nr][nc] == EMPTY:
                        open_ends += 1
                    break
            else:
                break
    return count, open_ends


def _pattern_score(count, open_ends):
    """Score a run pattern."""
    if count >= 5:
        return WIN_SCORE
    if count == 4:
        return FOUR_SCORE if open_ends == 2 else (FOUR_SCORE // 4 if open_ends == 1 else 0)
    if count == 3:
        return THREE_SCORE if open_ends == 2 else (THREE_SCORE // 5 if open_ends == 1 else 0)
    if count == 2:
        return TWO_SCORE if open_ends == 2 else (TWO_SCORE // 4 if open_ends == 1 else 0)
    if count == 1:
        return 10 if open_ends >= 1 else 0
    return 0


class GomokuAI:
    """Minimax AI with iterative deepening, VCF threat search, and pattern DB."""

    def __init__(self, color, depth=6):
        self.color = color
        self.opponent = WHITE if color == BLACK else BLACK
        self.max_depth = max(2, depth)
        self.nodes = 0
        self.max_nodes = 500_000
        self._abort_flag = False

    def abort(self):
        self._abort_flag = True

    # ── main entry ──────────────────────────────────────────────────────

    def get_move(self, board, time_limit=0):
        self.nodes = 0
        self._abort_flag = False
        deadline = time.time() + time_limit if time_limit > 0 else float('inf')

        piece_count = sum(
            1 for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY
        )

        # Opening: random near-center
        if piece_count == 0:
            centers = [
                (SIZE // 2 + dr, SIZE // 2 + dc)
                for dr in (-1, 0, 1) for dc in (-1, 0, 1)
            ]
            return random.choice(centers)

        candidates = self._candidates(board)
        if not candidates:
            return (SIZE // 2, SIZE // 2)

        # Immediate win
        for r, c in candidates:
            board[r][c] = self.color
            if self._is_win(board, r, c, self.color):
                board[r][c] = EMPTY
                return (r, c)
            board[r][c] = EMPTY

        # Block opponent win
        blocks = self._find_blocks(board, candidates)
        if len(blocks) == 1:
            return blocks[0]

        # VCF search
        vcf = self._vcf_search(board, 4)
        if vcf:
            return vcf

        # Block opponent VCF
        opp = GomokuAI(self.opponent, 2)
        opp_vcf = opp._vcf_search(board, 3)
        if opp_vcf:
            return opp_vcf

        # Iterative deepening minimax
        return self._iterative_deepening(board, candidates, deadline, piece_count)

    # ── candidate generation ────────────────────────────────────────────

    def _candidates(self, board):
        has_any = any(
            board[r][c] != EMPTY for r in range(SIZE) for c in range(SIZE)
        )
        if not has_any:
            return [(SIZE // 2, SIZE // 2)]

        cells = set()
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    for dr in range(-3, 4):
                        for dc in range(-3, 4):
                            nr, nc = r + dr, c + dc
                            if (
                                0 <= nr < SIZE
                                and 0 <= nc < SIZE
                                and board[nr][nc] == EMPTY
                            ):
                                cells.add((nr, nc))

        scored = []
        for r, c in cells:
            atk = self._cell_score(board, r, c, self.color)
            dfn = self._cell_score(board, r, c, self.opponent)
            scored.append((atk + dfn * 1.25, (r, c)))
        scored.sort(reverse=True)
        return [pos for _, pos in scored[: min(60, len(scored))]]

    def _cell_score(self, board, r, c, player):
        total = 0
        for dr, dc in DIRS:
            cnt, oe = _count_run(board, r, c, dr, dc, player)
            total += _pattern_score(cnt, oe)
        return total

    # ── blocking ────────────────────────────────────────────────────────

    def _find_blocks(self, board, candidates):
        """Find moves that must be blocked (opponent live-4 / rush-4)."""
        blocks = []
        # Immediate win block
        for r, c in candidates:
            board[r][c] = self.opponent
            if self._is_win(board, r, c, self.opponent):
                blocks.append((r, c))
            board[r][c] = EMPTY
        if blocks:
            return blocks

        # Live-4 / rush-4 block
        for r, c in candidates:
            board[r][c] = self.opponent
            for dr, dc in DIRS:
                cnt, oe = _count_run(board, r, c, dr, dc, self.opponent)
                if cnt == 4 and oe >= 1:
                    blocks.append((r, c))
                    break
            board[r][c] = EMPTY
        return blocks

    # ── VCF threat search ───────────────────────────────────────────────

    def _vcf_search(self, board, max_depth):
        """Threat-space search for forced win sequences."""
        threats = self._find_all_threats(board, self.color)
        for start_r, start_c in threats:
            board[start_r][start_c] = self.color
            if self._vcf_recurse(board, 1, max_depth, start_r, start_c):
                board[start_r][start_c] = EMPTY
                return (start_r, start_c)
            board[start_r][start_c] = EMPTY
        return None

    def _vcf_recurse(self, board, depth, max_depth, last_r, last_c):
        if depth >= max_depth:
            return False
        if self._is_win(board, last_r, last_c, self.color):
            return True

        our_threats = self._find_all_threats(board, self.color)
        if not our_threats:
            return False

        # Double threat = win
        l4 = l3 = 0
        for tr, tc in our_threats:
            for dr, dc in DIRS:
                cnt, oe = _count_run(board, tr, tc, dr, dc, self.color)
                if cnt == 4 and oe == 2:
                    l4 += 1
                if cnt == 3 and oe == 2:
                    l3 += 1
        if l4 >= 2 or (l4 >= 1 and l3 >= 1):
            return True

        opp_defenses = list(set(self._find_all_threats(board, self.opponent) + our_threats[:10]))
        for dr, dc in opp_defenses[:8]:
            if board[dr][dc] != EMPTY:
                continue
            saved = board[dr][dc]
            board[dr][dc] = self.opponent
            follow_ups = self._find_all_threats(board, self.color)
            for fr, fc in follow_ups[:5]:
                if board[fr][fc] != EMPTY:
                    continue
                board[fr][fc] = self.color
                if self._vcf_recurse(board, depth + 1, max_depth, fr, fc):
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
                if board[r][c] != EMPTY:
                    continue
                for dr, dc in DIRS:
                    cnt, oe = _count_run(board, r, c, dr, dc, player)
                    if (cnt == 4 and oe >= 1) or (cnt == 3 and oe == 2):
                        threats.add((r, c))
                        break
        return list(threats)

    # ── minimax search ──────────────────────────────────────────────────

    def _iterative_deepening(self, board, candidates, deadline, piece_count):
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
                    board[r][c] = EMPTY
                    return (r, c)
                score = self._minimax(
                    board, d - 1, -float('inf'), float('inf'), False, deadline
                )
                board[r][c] = EMPTY
                score += random.uniform(-30, 30)
                move_scores[(r, c)] = score
                if score > best_score:
                    best_score = score
                    best_move = (r, c)

            if best_score >= WIN_SCORE // 2:
                break

        return self._select_from_scores(move_scores, in_opening, best_move)

    def _select_from_scores(self, move_scores, in_opening, fallback):
        """Pick a move with randomized selection for variety."""
        if not move_scores:
            return fallback
        scored = sorted(move_scores.items(), key=lambda x: x[1], reverse=True)
        if in_opening:
            top_n = min(5, len(scored))
            top = scored[:top_n]
            if top[0][1] > 0:
                total = sum(s for _, s in top)
                weights = [s / total for _, s in top] if total > 0 else None
            else:
                weights = None
            return random.choices([m for m, _ in top], weights=weights, k=1)[0]
        elif len(scored) >= 2 and abs(scored[0][1] - scored[1][1]) < 300:
            return random.choice(scored[: min(3, len(scored))])[0]
        return scored[0][0]

    def _minimax(self, board, depth, alpha, beta, maximizing, deadline, _rec=0):
        if _rec > 20 or self._abort_flag or time.time() > deadline:
            return self._evaluate(board)
        if depth == 0:
            return self._evaluate(board)

        cands = self._candidates(board)
        if not cands:
            return 0

        n = len(cands)
        if depth <= 2:
            cands = cands[: min(n, 25)]
        elif depth <= 4:
            cands = cands[: min(n, 18)]
        else:
            cands = cands[: min(n, 12)]

        if maximizing:
            best = -float('inf')
            for r, c in cands:
                board[r][c] = self.color
                if self._is_win(board, r, c, self.color):
                    board[r][c] = EMPTY
                    return WIN_SCORE + depth
                s = self._minimax(board, depth - 1, alpha, beta, False, deadline, _rec + 1)
                board[r][c] = EMPTY
                if s > best:
                    best = s
                alpha = max(alpha, s)
                if alpha >= beta:
                    break
            return best
        else:
            best = float('inf')
            for r, c in cands:
                board[r][c] = self.opponent
                if self._is_win(board, r, c, self.opponent):
                    board[r][c] = EMPTY
                    return -(WIN_SCORE + depth)
                s = self._minimax(board, depth - 1, alpha, beta, True, deadline, _rec + 1)
                board[r][c] = EMPTY
                if s < best:
                    best = s
                beta = min(beta, s)
                if alpha >= beta:
                    break
            return best

    # ── evaluation ──────────────────────────────────────────────────────

    def _is_win(self, board, r, c, player):
        for dr, dc in DIRS:
            cnt, _ = _count_run(board, r, c, dr, dc, player)
            if cnt >= 5:
                return True
        return False

    def _evaluate(self, board):
        my_score = 0
        opp_score = 0
        has = False
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] == self.color:
                    has = True
                    my_score += sum(
                        _pattern_score(*_count_run(board, r, c, dr, dc, self.color))
                        for dr, dc in DIRS
                    )
                elif board[r][c] == self.opponent:
                    has = True
                    opp_score += sum(
                        _pattern_score(*_count_run(board, r, c, dr, dc, self.opponent))
                        for dr, dc in DIRS
                    )
        if not has:
            return 0
        return my_score - opp_score * 1.15 + random.randint(-40, 40)
