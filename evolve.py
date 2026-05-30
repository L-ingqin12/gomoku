"""
AI self-evolution: opening book + self-play training + weight tuning.

Opening Book:
  - Records board-state → move → win-rate from played games
  - Persists to JSON for cross-session learning
  - Queries best move by win rate with min-samples threshold

Self-Play:
  - Simulates AI vs AI games for training data
  - Mutates evaluation weights for exploration
  - Tournament-based selection of best weights
"""

import json
import os
import random
import time

from .constants import SIZE, EMPTY, BLACK, WHITE
from .game import new_board, find_win, is_full

# Default tunable evaluation weights
DEFAULT_WEIGHTS = {
    'defense_mult': 1.15,     # how much to weight opponent patterns
    'center_bonus': 50,        # bonus for center control in opening
    'noise_range': 40,         # random noise added to eval
    'candidate_noise': 30,     # noise on move scores during search
    'live4_score': 10_000_000,
    'rush4_score': 2_500_000,
    'live3_score': 100_000,
    'sleep3_score': 20_000,
    'live2_score': 1_000,
    'sleep2_score': 250,
    'vcf_depth': 4,
    'vcf_opp_depth': 3,
    'candidate_df_mult': 1.25,  # defense multiplier in candidate scoring
}


# ═══════════════════════════ Opening Book ═══════════════════════════

class OpeningBook:
    """Persistent opening book: board-state → move win-rate statistics.

    State key: tuple(board flattened as 225 ints)
    Stored as: {state_key: {move_str: [wins, total]}}
    """

    def __init__(self, path):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    raw = json.load(f)
                if not raw:
                    return
                # Convert string move keys back; keep state keys as-is (they're stringified lists)
                self.data = {}
                for state_key, moves in raw.items():
                    converted = {}
                    for mk, v in moves.items():
                        parts = mk.split(',')
                        converted[(int(parts[0]), int(parts[1]))] = v
                    self.data[state_key] = converted
            except (json.JSONDecodeError, ValueError):
                self.data = {}

    def _state_key(self, state):
        """Convert board state tuple to string key (first 8 moves only)."""
        # Only store opening phase (first ~8 moves) to keep book small
        piece_count = sum(1 for x in state if x != EMPTY)
        if piece_count > 8:
            return None
        return str(list(state))

    def record(self, state, move, outcome):
        """Record a move played from 'state' with 'outcome' (0..1 win rate)."""
        key = self._state_key(state)
        if key is None:
            return
        if key not in self.data:
            self.data[key] = {}
        move_key = (move[0], move[1])
        if move_key not in self.data[key]:
            self.data[key][move_key] = [0, 0]
        self.data[key][move_key][0] += outcome
        self.data[key][move_key][1] += 1

    def query(self, state):
        """Return {move: (wins, total)} for a given state, or None."""
        key = self._state_key(state)
        if key is None or key not in self.data:
            return None
        # Data is already {(r,c): [wins, total]}
        return {move: tuple(v) for move, v in self.data[key].items()}

    def best_move(self, state, min_samples=2):
        """Return the best move by win rate, or None if insufficient data."""
        moves = self.query(state)
        if not moves:
            return None
        best = None
        best_rate = -1
        for move, (wins, total) in moves.items():
            if total < min_samples:
                continue
            rate = wins / total if total > 0 else 0
            if rate > best_rate:
                best_rate = rate
                best = move
        return best

    def save(self):
        """Persist to JSON. Converts tuple move keys to 'r,c' strings."""
        out = {}
        for k, moves in self.data.items():
            out[k] = {f'{r},{c}': v for (r, c), v in moves.items()}
        with open(self.path, 'w') as f:
            json.dump(out, f)


# ═══════════════════════════ Weight Mutation ═══════════════════════════

def mutate_weights(weights, rate=0.1, scale=0.2):
    """Return a copy of weights with random mutations.

    rate: probability each weight mutates
    scale: max relative change (0.2 = ±20%)
    """
    mutated = {}
    for k, v in weights.items():
        if random.random() < rate:
            factor = 1.0 + random.uniform(-scale, scale)
            mutated[k] = round(max(v * 0.5, min(v * 2.0, v * factor)), 4)
        else:
            mutated[k] = v
    return mutated


# ═══════════════════════════ Self-Play ═══════════════════════════

class SelfPlayTrainer:
    """Orchestrates self-play training batches."""

    def __init__(self, games_per_batch=10):
        self.games_per_batch = games_per_batch
        self.games_played = 0
        self.results = []

    def train_batch(self, weights_a, weights_b, depth=2):
        """Run a batch of games between two weight configurations."""
        batch_results = []
        for i in range(self.games_per_batch):
            # Alternate colors for fairness
            if i % 2 == 0:
                result = simulate_game(weights_a, weights_b, depth=depth)
                result['black_weights'] = 'A'
                result['white_weights'] = 'B'
            else:
                result = simulate_game(weights_b, weights_a, depth=depth)
                result['black_weights'] = 'B'
                result['white_weights'] = 'A'
            batch_results.append(result)
            self.games_played += 1
        self.results.extend(batch_results)
        return batch_results


def simulate_game(black_weights, white_weights, depth=2):
    """Simulate a full AI-vs-AI game. Returns stats dict."""
    from .ai import GomokuAI

    black_ai = _make_weighted_ai(BLACK, black_weights, depth)
    white_ai = _make_weighted_ai(WHITE, white_weights, depth)

    board = new_board()
    current = BLACK
    moves = 0
    t0 = time.time()

    while moves < SIZE * SIZE:
        ai = black_ai if current == BLACK else white_ai
        move = ai.get_move([r[:] for r in board], time_limit=10)
        if move is None:
            return {'winner': 'draw', 'moves': moves, 'reason': 'no_move',
                    'time': time.time() - t0}
        r, c = move
        if board[r][c] != EMPTY:
            return {'winner': 'draw', 'moves': moves, 'reason': 'occupied',
                    'time': time.time() - t0}
        board[r][c] = current
        moves += 1
        wc = find_win(board, r, c)
        if wc:
            winner = 'black' if current == BLACK else 'white'
            return {'winner': winner, 'moves': moves, 'reason': 'win',
                    'time': time.time() - t0}
        if is_full(board):
            return {'winner': 'draw', 'moves': moves, 'reason': 'full',
                    'time': time.time() - t0}
        current = WHITE if current == BLACK else BLACK

    return {'winner': 'draw', 'moves': moves, 'reason': 'max_moves',
            'time': time.time() - t0}


def _make_weighted_ai(color, weights, depth):
    """Create an AI instance with custom evaluation weights."""
    from . import ai as ai_module
    ai = ai_module.GomokuAI(color, depth)

    # Store weights for the evaluation function
    ai._weights = weights
    # Override evaluation with weighted version
    original_eval = ai._evaluate

    def weighted_evaluate(board):
        w = weights
        my_score = 0
        opp_score = 0
        has = False
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] == ai.color:
                    has = True
                    for dr, dc in ai_module.DIRS:
                        cnt, oe = ai_module._count_run(board, r, c, dr, dc, ai.color)
                        my_score += _weighted_pattern_score(cnt, oe, w)
                elif board[r][c] == ai.opponent:
                    has = True
                    for dr, dc in ai_module.DIRS:
                        cnt, oe = ai_module._count_run(board, r, c, dr, dc, ai.opponent)
                        opp_score += _weighted_pattern_score(cnt, oe, w)
        if not has:
            return 0
        # Center bonus
        total = sum(1 for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY)
        if total < 6 and board[SIZE//2][SIZE//2] == ai.color:
            my_score += w['center_bonus']
        elif total < 6 and board[SIZE//2][SIZE//2] == ai.opponent:
            opp_score += w['center_bonus']
        return my_score - opp_score * w['defense_mult'] + random.randint(
            -w['noise_range'], w['noise_range']
        )

    ai._evaluate = weighted_evaluate
    return ai


def _weighted_pattern_score(count, open_ends, w):
    """Score using custom weights."""
    if count >= 5:
        return 100_000_000
    if count == 4:
        return w['live4_score'] if open_ends == 2 else (w['rush4_score'] if open_ends == 1 else 0)
    if count == 3:
        return w['live3_score'] if open_ends == 2 else (w['sleep3_score'] if open_ends == 1 else 0)
    if count == 2:
        return w['live2_score'] if open_ends == 2 else (w['sleep2_score'] if open_ends == 1 else 0)
    if count == 1:
        return 10 if open_ends >= 1 else 0
    return 0


# ═══════════════════════════ Tournament ═══════════════════════════

def run_tournament(population, games_per_match=2, depth=2):
    """Run a round-robin tournament between weight configurations.

    Args:
        population: {name: weights_dict}
        games_per_match: games per pairing
        depth: AI search depth

    Returns:
        {'winner': name, 'best_weights': name, 'scores': {name: score}, 'total_games': N}
    """
    names = list(population.keys())
    scores = {name: 0 for name in names}
    total_games = 0

    for i, name_a in enumerate(names):
        for j, name_b in enumerate(names):
            if i >= j:
                continue
            for g in range(games_per_match):
                if g % 2 == 0:
                    result = simulate_game(
                        population[name_a], population[name_b], depth=depth
                    )
                    if result['winner'] == 'black':
                        scores[name_a] += 1
                    elif result['winner'] == 'white':
                        scores[name_b] += 1
                    else:
                        scores[name_a] += 0.5
                        scores[name_b] += 0.5
                else:
                    result = simulate_game(
                        population[name_b], population[name_a], depth=depth
                    )
                    if result['winner'] == 'black':
                        scores[name_b] += 1
                    elif result['winner'] == 'white':
                        scores[name_a] += 1
                    else:
                        scores[name_a] += 0.5
                        scores[name_b] += 0.5
                total_games += 1

    # Find winner
    best_name = max(scores, key=scores.get)
    return {
        'winner': best_name,
        'best_weights': best_name,
        'scores': scores,
        'total_games': total_games,
    }
