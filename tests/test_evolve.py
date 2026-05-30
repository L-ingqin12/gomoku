"""TDD tests for AI self-evolution: opening book + self-play training."""

import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gomoku.constants import SIZE, EMPTY, BLACK, WHITE
from gomoku.game import new_board


# ── Opening Book tests ──────────────────────────────────────────────────

class TestOpeningBook(unittest.TestCase):
    """Tests for the opening book: record, query, persist, merge."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        self.tmp.close()

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def _make_book(self):
        from gomoku.evolve import OpeningBook
        return OpeningBook(self.tmp.name)

    def test_empty_book_returns_none(self):
        book = self._make_book()
        self.assertIsNone(book.query(tuple([EMPTY]*SIZE*SIZE)))

    def test_record_and_query(self):
        book = self._make_book()
        # Record a board state
        state = tuple([EMPTY] * SIZE * SIZE)
        book.record(state, (7, 7), 1.0)  # move (7,7) with win score 1.0
        result = book.query(state)
        self.assertIsNotNone(result)
        self.assertIn((7, 7), result)

    def test_best_move_by_win_rate(self):
        book = self._make_book()
        state = tuple([EMPTY] * SIZE * SIZE)
        # Record move A with 30% win rate, move B with 70%
        book.record(state, (7, 7), 0.3)
        book.record(state, (7, 7), 0.3)
        book.record(state, (7, 7), 0.3)
        book.record(state, (8, 8), 0.7)
        book.record(state, (8, 8), 0.7)
        book.record(state, (8, 8), 0.7)
        # Best move should be (8,8) with higher win rate
        best = book.best_move(state)
        self.assertEqual(best, (8, 8))

    def test_persist_and_reload(self):
        book = self._make_book()
        state = tuple([EMPTY] * SIZE * SIZE)
        book.record(state, (7, 7), 0.5)
        book.save()

        # Reload
        book2 = self._make_book()
        result = book2.query(state)
        self.assertIsNotNone(result)
        self.assertIn((7, 7), result)

    def test_default_response(self):
        """Default response when book has no entry: should fall back."""
        book = self._make_book()
        state = tuple([EMPTY] * SIZE * SIZE)
        move = book.best_move(state)
        self.assertIsNone(move)  # no entry yet

    def test_min_samples_threshold(self):
        """Moves with too few samples should not be recommended."""
        book = self._make_book()
        state = tuple([EMPTY] * SIZE * SIZE)
        book.record(state, (7, 7), 1.0)  # only 1 sample
        move = book.best_move(state, min_samples=3)
        self.assertIsNone(move)  # below threshold


# ── Self-play training tests ────────────────────────────────────────────

class TestSelfPlay(unittest.TestCase):
    """Tests for self-play training utilities."""

    def test_game_outcome_tracking(self):
        from gomoku.evolve import SelfPlayTrainer
        trainer = SelfPlayTrainer(games_per_batch=1)
        self.assertEqual(trainer.games_played, 0)

    def test_weight_mutation(self):
        """Weights should mutate within [0.5x, 2.0x] proportional bounds."""
        from gomoku.evolve import mutate_weights, DEFAULT_WEIGHTS
        mutated = mutate_weights(DEFAULT_WEIGHTS, rate=0.1, scale=0.2)
        self.assertEqual(set(mutated.keys()), set(DEFAULT_WEIGHTS.keys()))
        # Clamped within [0.5x, 2.0x] of original
        for k, v in mutated.items():
            orig = DEFAULT_WEIGHTS[k]
            self.assertGreaterEqual(v, orig * 0.5, f'{k}: {v} < {orig * 0.5}')
            self.assertLessEqual(v, orig * 2.0, f'{k}: {v} > {orig * 2.0}')

    def test_weight_mutation_rate_zero(self):
        """Zero mutation rate should return identical weights."""
        from gomoku.evolve import mutate_weights, DEFAULT_WEIGHTS
        mutated = mutate_weights(DEFAULT_WEIGHTS, rate=0.0, scale=0.2)
        for k in DEFAULT_WEIGHTS:
            self.assertEqual(mutated[k], DEFAULT_WEIGHTS[k])

    def test_simulate_game_completes(self):
        """A simulated game between two AIs should complete with a result."""
        from gomoku.evolve import simulate_game, DEFAULT_WEIGHTS
        result = simulate_game(DEFAULT_WEIGHTS, DEFAULT_WEIGHTS, depth=2)
        self.assertIn(result['winner'], ['black', 'white', 'draw'])
        self.assertGreater(result['moves'], 0)
        self.assertLessEqual(result['moves'], SIZE * SIZE)

    def test_simulate_game_depth_2_fast(self):
        """A depth-2 game should be fast (< 10 seconds)."""
        import time
        from gomoku.evolve import simulate_game, DEFAULT_WEIGHTS
        t0 = time.time()
        result = simulate_game(DEFAULT_WEIGHTS, DEFAULT_WEIGHTS, depth=2)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 10.0, f'Game took {elapsed:.1f}s')
        self.assertGreater(result['moves'], 0)


# ── Tournament tests ────────────────────────────────────────────────────

class TestTournament(unittest.TestCase):
    """Tests for tournament-based weight evolution."""

    def test_tournament_produces_winner(self):
        from gomoku.evolve import run_tournament, DEFAULT_WEIGHTS
        # Single round: compare default vs slightly mutated
        from gomoku.evolve import mutate_weights
        challenger = mutate_weights(DEFAULT_WEIGHTS, rate=0.1, scale=0.05)
        result = run_tournament(
            {'default': DEFAULT_WEIGHTS, 'mutant': challenger},
            games_per_match=2, depth=2
        )
        self.assertIn('winner', result)
        self.assertGreater(result['total_games'], 0)

    def test_best_weights_saved(self):
        """After tournament, best weights should be retrievable."""
        from gomoku.evolve import run_tournament, DEFAULT_WEIGHTS
        from gomoku.evolve import mutate_weights

        pop = {
            'w1': DEFAULT_WEIGHTS,
            'w2': mutate_weights(DEFAULT_WEIGHTS, rate=0.3, scale=0.1),
        }
        result = run_tournament(pop, games_per_match=2, depth=2)
        best = result['best_weights']
        self.assertIn(best, pop)
        self.assertIn('scores', result)
        self.assertIn(best, result['scores'])


class TestCoevolution(unittest.TestCase):
    """Tests for co-evolution: blend_weights, CoevolutionPool."""

    def test_blend_weights_ratio_zero(self):
        from gomoku.evolve import blend_weights, DEFAULT_WEIGHTS
        result = blend_weights(DEFAULT_WEIGHTS, DEFAULT_WEIGHTS, ratio=0.0)
        for k in DEFAULT_WEIGHTS:
            self.assertEqual(result[k], DEFAULT_WEIGHTS[k])

    def test_blend_weights_ratio_half(self):
        from gomoku.evolve import blend_weights
        a = {'x': 10.0, 'y': 20.0}
        b = {'x': 20.0, 'y': 10.0}
        result = blend_weights(a, b, ratio=0.5)
        self.assertAlmostEqual(result['x'], 15.0)
        self.assertAlmostEqual(result['y'], 15.0)

    def test_blend_weights_ratio_learn(self):
        """Loser learns 25% from winner."""
        from gomoku.evolve import blend_weights
        loser = {'defense_mult': 1.0}
        winner = {'defense_mult': 2.0}
        result = blend_weights(loser, winner, ratio=0.25)
        self.assertAlmostEqual(result['defense_mult'], 1.25)

    def test_pool_initialization(self):
        from gomoku.evolve import CoevolutionPool
        pool = CoevolutionPool(population_size=4)
        self.assertGreaterEqual(len(pool.population), 2)
        self.assertEqual(pool.generation, 0)
        for name in pool.population:
            self.assertIn(name, pool.elo)
            self.assertEqual(pool.elo[name], 1000)

    def test_pool_get_pair(self):
        from gomoku.evolve import CoevolutionPool
        pool = CoevolutionPool(population_size=4)
        a_name, a_w, b_name, b_w = pool.get_pair()
        self.assertNotEqual(a_name, b_name)
        self.assertIsInstance(a_w, dict)
        self.assertIsInstance(b_w, dict)

    def test_pool_update_black_wins(self):
        from gomoku.evolve import CoevolutionPool
        pool = CoevolutionPool(population_size=4)
        a_name, a_w, b_name, b_w = pool.get_pair()
        old_b = dict(pool.population[b_name])
        pool.update(a_name, b_name, 'black')
        # b (loser) weights should have changed
        new_b = pool.population[b_name]
        self.assertNotEqual(old_b, new_b)

    def test_pool_best_returns_name(self):
        from gomoku.evolve import CoevolutionPool
        pool = CoevolutionPool(population_size=4)
        best = pool.best()
        self.assertIn(best, pool.population)

    def test_pool_generation_increments(self):
        from gomoku.evolve import CoevolutionPool
        pool = CoevolutionPool(population_size=4)
        a, aw, b, bw = pool.get_pair()
        self.assertEqual(pool.generation, 0)
        pool.update(a, b, 'black')
        self.assertEqual(pool.generation, 1)

    def test_pool_save_load(self):
        import tempfile, os
        from gomoku.evolve import CoevolutionPool
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        tmp.close()
        try:
            pool = CoevolutionPool(population_size=3, save_path=tmp.name)
            a, aw, b, bw = pool.get_pair()
            pool.update(a, b, 'black')
            pool.save()

            pool2 = CoevolutionPool(population_size=3, save_path=tmp.name)
            self.assertGreater(pool2.generation, 0)
        finally:
            os.unlink(tmp.name)


if __name__ == '__main__':
    unittest.main()
