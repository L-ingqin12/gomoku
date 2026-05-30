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
        self.max_depth = max(2, min(depth, 6))  # cap at 6 for performance
        self.nodes = 0
        self.max_nodes = 500_000
        self._abort_flag = False
        self._deadline = float('inf')
        self._last_opp_move = None
        self._tt = {}
        self._defense_mult = 1.15
        self._candidate_df_mult = 1.25

    def abort(self):
        self._abort_flag = True

    def _timed_out(self):
        """Check if time limit or node limit exceeded."""
        if self._abort_flag:
            return True
        if self.nodes > self.max_nodes:
            return True
        if time.time() > self._deadline:
            return True
        return False

    # ── main entry ──────────────────────────────────────────────────────

    def get_move(self, board, time_limit=15):
        """Return best move. time_limit: max seconds (default 15s)."""
        self.nodes = 0
        self._abort_flag = False
        self._deadline = time.time() + max(time_limit, 1)  # minimum 1s

        piece_count = sum(
            1 for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY
        )

        # Find opponent's last move for localized defense
        self._find_last_opponent_move(board)

        # Assess position: aggressive when winning, defensive when threatened
        self._assess_position(board)

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

        # VCF disabled — time is better spent on deeper minimax
        # (uncomment below to re-enable for critical situations only)
        # if time.time() + 2 < self._deadline:
        #     vcf = self._vcf_search(board, 4)
        #     if vcf: return vcf

        # Iterative deepening minimax — guaranteed to return a move
        move = self._iterative_deepening(board, candidates, piece_count)
        if move is not None:
            return move
        # Foolproof fallback: return first empty candidate
        for r, c in candidates:
            if board[r][c] == EMPTY:
                return (r, c)
        # Absolute last resort
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] == EMPTY:
                    return (r, c)
        return (SIZE // 2, SIZE // 2)

    def _assess_position(self, board):
        """Assess board: set dynamic defense_mult based on threat balance.
        - AI has strong threats → aggressive (lower defense, higher attack)
        - Opponent has threats → defensive (higher defense)
        - Neutral → balanced"""
        my_best = 0
        opp_best = 0
        # Quick scan: sample cells near pieces to find best threats
        sampled = set()
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    for dr in range(-2, 3):
                        for dc in range(-2, 3):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < SIZE and 0 <= nc < SIZE and (nr, nc) not in sampled:
                                sampled.add((nr, nc))
                                if board[nr][nc] == EMPTY:
                                    # Check what threat this would create for each player
                                    for dr2, dc2 in DIRS:
                                        cnt, oe = _count_run(board, nr, nc, dr2, dc2, self.color)
                                        s = _pattern_score(cnt, oe)
                                        if s > my_best:
                                            my_best = s
                                        cnt, oe = _count_run(board, nr, nc, dr2, dc2, self.opponent)
                                        s = _pattern_score(cnt, oe)
                                        if s > opp_best:
                                            opp_best = s
        # Dynamic defense_mult
        if my_best >= THREE_SCORE and my_best > opp_best * 2:
            # AI has dominant threat → go aggressive
            self._defense_mult = 0.8
            self._candidate_df_mult = 0.9
        elif opp_best >= THREE_SCORE and opp_best > my_best * 2:
            # Opponent has strong threat → go defensive
            self._defense_mult = 1.5
            self._candidate_df_mult = 1.8
        elif my_best >= THREE_SCORE:
            # AI has threat but opponent close → slightly aggressive
            self._defense_mult = 1.0
            self._candidate_df_mult = 1.1
        elif opp_best >= THREE_SCORE:
            # Opponent threat → slightly defensive
            self._defense_mult = 1.3
            self._candidate_df_mult = 1.5
        else:
            # Neutral → balanced
            self._defense_mult = 1.15
            self._candidate_df_mult = 1.25

    def _find_last_opponent_move(self, board):
        """Find opponent's most recent move by checking board against last known state.
        Falls back to scanning for any opponent piece if no history."""
        # Simple heuristic: find an opponent piece with fewest friendly neighbors
        # (most likely the last move, since opponent just played)
        best = None
        best_neighbors = 999
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] == self.opponent:
                    # Count friendly neighbors (pieces of same color nearby)
                    neighbors = 0
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == self.opponent:
                                neighbors += 1
                    if neighbors < best_neighbors:
                        best_neighbors = neighbors
                        best = (r, c)
        self._last_opp_move = best
        return best

    # ── candidate generation ────────────────────────────────────────────

    def _candidates(self, board):
        if self._timed_out():
            return [(SIZE // 2, SIZE // 2)]
        has_any = any(
            board[r][c] != EMPTY for r in range(SIZE) for c in range(SIZE)
        )
        if not has_any:
            return [(SIZE // 2, SIZE // 2)]

        cells = set()
        for r in range(SIZE):
            if self._timed_out():
                break
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    # Radius 2 around each piece (was 3) — tight enough for threats
                    for dr in range(-2, 3):
                        for dc in range(-2, 3):
                            nr, nc = r + dr, c + dc
                            if (
                                0 <= nr < SIZE
                                and 0 <= nc < SIZE
                                and board[nr][nc] == EMPTY
                            ):
                                cells.add((nr, nc))

        scored = []
        for i, (r, c) in enumerate(cells):
            if i % 16 == 0 and self._timed_out():
                break
            atk = self._cell_score(board, r, c, self.color)
            dfn = self._cell_score(board, r, c, self.opponent)
            s = atk + dfn * self._candidate_df_mult
            # Proximity bonus: cells near opponent's last move get priority
            if self._last_opp_move:
                lr, lc = self._last_opp_move
                dist = abs(r - lr) + abs(c - lc)
                if dist <= 2:
                    s += 500  # significant bonus for immediate response area
                elif dist <= 4:
                    s += 100  # moderate bonus for nearby area
            scored.append((s, (r, c)))
        scored.sort(reverse=True)
        return [pos for _, pos in scored[: min(25, len(scored))]]

    def _cell_score(self, board, r, c, player):
        total = 0
        for dr, dc in DIRS:
            cnt, oe = _count_run(board, r, c, dr, dc, player)
            total += _pattern_score(cnt, oe)
        return total

    # ── blocking ────────────────────────────────────────────────────────

    def _find_blocks(self, board, candidates):
        """Find urgent defensive moves (opponent win / live-4 / rush-4 / double-three).
        Prioritizes threats near opponent's last move."""
        if self._timed_out():
            return []
        blocks = []
        # 1) Immediate five-in-row block — highest priority
        for r, c in candidates:
            if self._timed_out():
                break
            board[r][c] = self.opponent
            if self._is_win(board, r, c, self.opponent):
                blocks.append((r, c))
            board[r][c] = EMPTY
        if blocks:
            return blocks

        # 2) Prioritize candidates near opponent's last move
        ordered = list(candidates)
        if self._last_opp_move:
            lr, lc = self._last_opp_move
            ordered.sort(key=lambda pos: abs(pos[0] - lr) + abs(pos[1] - lc))

        # 3) Live-4 / rush-4 detection (near last move first)
        for r, c in ordered:
            if self._timed_out():
                break
            board[r][c] = self.opponent
            for dr, dc in DIRS:
                cnt, oe = _count_run(board, r, c, dr, dc, self.opponent)
                if cnt == 4 and oe >= 1:
                    blocks.append((r, c))
                    break
            board[r][c] = EMPTY
            if len(blocks) >= 2:  # multiple live-4 threats — block one
                break
        if blocks:
            return blocks

        # 4) Double live-3 detection (opponent creating dual threat)
        live3_spots = []
        for r, c in ordered:
            if self._timed_out():
                break
            board[r][c] = self.opponent
            l3_count = 0
            for dr, dc in DIRS:
                cnt, oe = _count_run(board, r, c, dr, dc, self.opponent)
                if cnt == 3 and oe == 2:
                    l3_count += 1
            if l3_count >= 2:  # creates double live-3 → must block
                blocks.append((r, c))
            elif l3_count == 1:
                live3_spots.append((r, c))
            board[r][c] = EMPTY
        if blocks:
            return blocks
        # If opponent has multiple live-3 threats, block the one near last move
        if len(live3_spots) >= 2:
            return [live3_spots[0]]

        return []

    # ── VCF threat search ───────────────────────────────────────────────

    def _vcf_search(self, board, max_depth):
        """Threat-space search for forced win sequences."""
        if self._timed_out():
            return None
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
        """Find positions where 'player' can create live-4/rush-4/live-3.
        Only scans cells near existing pieces for speed."""
        threats = set()
        # Collect cells near any piece (radius 2)
        near = set()
        for r in range(SIZE):
            if self._timed_out():
                break
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    for dr in range(-2, 3):
                        for dc in range(-2, 3):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] == EMPTY:
                                near.add((nr, nc))
        for r, c in near:
            if self._timed_out():
                break
            for dr, dc in DIRS:
                cnt, oe = _count_run(board, r, c, dr, dc, player)
                if (cnt == 4 and oe >= 1) or (cnt == 3 and oe == 2):
                    threats.add((r, c))
                    break
        return list(threats)

    # ── minimax search ──────────────────────────────────────────────────

    def _iterative_deepening(self, board, candidates, piece_count):
        best_move = candidates[0]
        best_score = -float('inf')
        move_scores = {}
        in_opening = piece_count < 6

        for d in range(2, self.max_depth + 1, 2):
            if self._timed_out():
                break
            if best_move in candidates:
                candidates.remove(best_move)
                candidates.insert(0, best_move)

            for r, c in candidates:
                if self._timed_out():
                    break
                board[r][c] = self.color
                if self._is_win(board, r, c, self.color):
                    board[r][c] = EMPTY
                    return (r, c)
                score = self._minimax(board, d - 1, -float('inf'), float('inf'), False)
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

    def _board_hash(self, board):
        """Fast hash of board state for transposition table."""
        # Only hash occupied cells — much faster than full board
        pieces = []
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    pieces.append((r, c, board[r][c]))
        return tuple(pieces)

    def _minimax(self, board, depth, alpha, beta, maximizing, _rec=0):
        if _rec > 20 or self._timed_out():
            return self._evaluate(board)
        if depth == 0:
            return self._evaluate(board)

        # Transposition table lookup
        bh = (self._board_hash(board), depth, maximizing)
        if bh in self._tt:
            tt_depth, tt_score, tt_bound = self._tt[bh]
            if tt_depth >= depth:
                if tt_bound == 'exact':
                    return tt_score
                if tt_bound == 'lower' and tt_score >= beta:
                    return tt_score
                if tt_bound == 'upper' and tt_score <= alpha:
                    return tt_score

        cands = self._candidates(board)
        if not cands:
            return 0

        n = len(cands)
        if depth <= 2:
            cands = cands[: min(n, 12)]
        elif depth <= 4:
            cands = cands[: min(n, 8)]
        else:
            cands = cands[: min(n, 5)]

        if maximizing:
            best = -float('inf')
            first = True
            for (r, c) in cands:
                if self._timed_out():
                    break
                board[r][c] = self.color
                if self._is_win(board, r, c, self.color):
                    board[r][c] = EMPTY
                    return WIN_SCORE + depth
                # Principal Variation Search
                if first:
                    s = self._minimax(board, depth - 1, alpha, beta, False, _rec + 1)
                    first = False
                else:
                    # Null-window search — cheap check if move is worse
                    s = self._minimax(board, depth - 1, alpha, alpha + 1, False, _rec + 1)
                    if alpha < s < beta:
                        # Re-search with full window — it might be better
                        s = self._minimax(board, depth - 1, alpha, beta, False, _rec + 1)
                board[r][c] = EMPTY
                if s > best:
                    best = s
                alpha = max(alpha, s)
                if alpha >= beta:
                    break
            # Store in TT
            self._tt[bh] = (depth, best, 'exact' if best > alpha else 'upper')
            return best
        else:
            best = float('inf')
            first = True
            for (r, c) in cands:
                if self._timed_out():
                    break
                board[r][c] = self.opponent
                if self._is_win(board, r, c, self.opponent):
                    board[r][c] = EMPTY
                    return -(WIN_SCORE + depth)
                if first:
                    s = self._minimax(board, depth - 1, alpha, beta, True, _rec + 1)
                    first = False
                else:
                    s = self._minimax(board, depth - 1, beta - 1, beta, True, _rec + 1)
                    if alpha < s < beta:
                        s = self._minimax(board, depth - 1, alpha, beta, True, _rec + 1)
                board[r][c] = EMPTY
                if s < best:
                    best = s
                beta = min(beta, s)
                if alpha >= beta:
                    break
            self._tt[bh] = (depth, best, 'exact' if best < beta else 'lower')
            return best

    # ── evaluation ──────────────────────────────────────────────────────

    def _is_win(self, board, r, c, player):
        for dr, dc in DIRS:
            cnt, _ = _count_run(board, r, c, dr, dc, player)
            if cnt >= 5:
                return True
        return False

    def _evaluate(self, board):
        """Sample-based evaluation: only scores cells near pieces."""
        my_score = 0
        opp_score = 0
        scored = set()
        # Only evaluate cells within radius 1 of any piece
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    for dr in range(-1, 2):
                        for dc in range(-1, 2):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < SIZE and 0 <= nc < SIZE and (nr, nc) not in scored:
                                scored.add((nr, nc))
                                if board[nr][nc] == self.color:
                                    my_score += sum(
                                        _pattern_score(*_count_run(board, nr, nc, ddr, ddc, self.color))
                                        for ddr, ddc in DIRS
                                    )
                                elif board[nr][nc] == self.opponent:
                                    opp_score += sum(
                                        _pattern_score(*_count_run(board, nr, nc, ddr, ddc, self.opponent))
                                        for ddr, ddc in DIRS
                                    )
        if not scored:
            return 0
        return my_score - opp_score * self._defense_mult + random.uniform(-40, 40)
