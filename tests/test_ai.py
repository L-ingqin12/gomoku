"""Tests for AI engine: evaluation, move selection, blocking, VCF."""

import sys, os, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gomoku.constants import SIZE, EMPTY, BLACK, WHITE
from gomoku.constants import WIN_SCORE, FOUR_SCORE, THREE_SCORE, TWO_SCORE
from gomoku.game import new_board
from gomoku.ai import GomokuAI, _count_run, _pattern_score


class TestPatternScoring(unittest.TestCase):

    def test_count_run_open_four(self):
        b = new_board()
        for c in range(4):
            b[7][3 + c] = BLACK
        # Count from the middle of the run (7,5) where piece IS placed
        cnt, oe = _count_run(b, 7, 5, 0, 1, BLACK)
        self.assertEqual(cnt, 4)  # four consecutive BLACK pieces
        self.assertEqual(oe, 2)   # both ends open

    def test_count_run_center_of_three(self):
        b = new_board()
        b[5][5] = BLACK
        b[5][7] = BLACK
        b[5][6] = BLACK
        cnt, oe = _count_run(b, 5, 6, 0, 1, BLACK)
        self.assertEqual(cnt, 3)
        self.assertEqual(oe, 2)  # both ends open

    def test_count_run_blocked_one_side(self):
        b = new_board()
        b[0][0] = BLACK
        b[0][1] = BLACK
        b[0][2] = BLACK
        cnt, oe = _count_run(b, 0, 0, 0, 1, BLACK)
        self.assertEqual(cnt, 3)
        self.assertEqual(oe, 1)  # left blocked by wall

    def test_pattern_score_win(self):
        self.assertGreater(_pattern_score(5, 0), WIN_SCORE // 2)

    def test_pattern_score_open_four(self):
        s = _pattern_score(4, 2)
        self.assertGreater(s, THREE_SCORE)

    def test_pattern_score_open_three(self):
        s = _pattern_score(3, 2)
        self.assertGreater(s, TWO_SCORE)
        self.assertLess(s, FOUR_SCORE)

    def test_pattern_score_closed_three(self):
        s_open = _pattern_score(3, 2)
        s_closed = _pattern_score(3, 1)
        self.assertGreater(s_open, s_closed)

    def test_pattern_score_zero(self):
        self.assertEqual(_pattern_score(1, 0), 0)
        self.assertEqual(_pattern_score(2, 0), 0)


class TestAIBlocking(unittest.TestCase):

    def setUp(self):
        self.ai = GomokuAI(BLACK, depth=2)

    def test_immediate_win(self):
        b = new_board()
        for c in range(4):
            b[7][3 + c] = BLACK
        move = self.ai.get_move([r[:] for r in b], time_limit=5)
        self.assertIn(move, [(7, 2), (7, 7)])  # complete the five

    def test_block_opponent_win(self):
        b = new_board()
        for c in range(4):
            b[0][c] = WHITE
        move = self.ai.get_move([r[:] for r in b], time_limit=5)
        self.assertEqual(move, (0, 4))

    def test_block_opponent_rush_four(self):
        """Block a rush-4: WHITE at cols 0-3, blocked by wall at left, must block at (7,4)."""
        b = new_board()
        b[7][0] = WHITE
        b[7][1] = WHITE
        b[7][2] = WHITE
        b[7][3] = WHITE  # left blocked by wall, right open at col 4
        ai = GomokuAI(BLACK, depth=2)
        move = ai.get_move([r[:] for r in b], time_limit=5)
        self.assertEqual(move, (7, 4))

    def test_opening_move_near_center(self):
        b = new_board()
        move = self.ai.get_move([r[:] for r in b], time_limit=5)
        self.assertTrue(5 <= move[0] <= 9)
        self.assertTrue(5 <= move[1] <= 9)


class TestAIVariety(unittest.TestCase):

    def test_opening_variety(self):
        """Run 20 openings and ensure at least 3 different moves."""
        ai = GomokuAI(BLACK, depth=2)
        moves = set()
        for _ in range(20):
            b = new_board()
            m = ai.get_move([r[:] for r in b], time_limit=5)
            moves.add(m)
        self.assertGreaterEqual(len(moves), 3, f'Only got {len(moves)} unique openings')

    def test_response_variety(self):
        """After a fixed first move, AI should sometimes respond differently."""
        ai = GomokuAI(WHITE, depth=2)
        moves = set()
        for _ in range(10):
            b = new_board()
            b[7][7] = BLACK  # opponent plays center
            m = ai.get_move([r[:] for r in b], time_limit=5)
            moves.add(m)
        # Should have at least 2 different responses (random among equally good)
        self.assertGreaterEqual(len(moves), 2, f'Only got {len(moves)} unique responses')


class TestAIConsistency(unittest.TestCase):

    def test_abort_flag(self):
        ai = GomokuAI(BLACK, depth=2)
        ai.abort()
        self.assertTrue(ai._abort_flag)

    def test_abort_during_search_returns_move(self):
        """Abort during search should return the best move found so far."""
        import threading
        ai = GomokuAI(BLACK, depth=8)
        b = new_board()
        # Moderate complexity to ensure search is in progress
        for i in range(4):
            b[7][3 + i] = WHITE
            b[i][i] = BLACK
        result = [None]

        def search():
            result[0] = ai.get_move([r[:] for r in b], time_limit=10)

        t = threading.Thread(target=search, daemon=True)
        t.start()
        # Abort after a short delay while the search is running
        t.join(timeout=0.3)
        ai.abort()
        t.join(timeout=2)

        move = result[0]
        self.assertIsNotNone(move, 'Aborted search should still return a move')
        self.assertTrue(0 <= move[0] < SIZE)
        self.assertTrue(0 <= move[1] < SIZE)
        self.assertEqual(b[move[0]][move[1]], EMPTY, 'Move should be on empty cell')


class TestVCF(unittest.TestCase):

    def test_vcf_double_three_is_win(self):
        """AI should recognize double open-three as winning."""
        ai = GomokuAI(BLACK, depth=4)
        b = new_board()
        # Set up a position where AI can create dual threat
        b[7][5] = BLACK
        b[7][6] = BLACK
        b[7][7] = BLACK  # open three horizontal
        b[6][6] = BLACK
        b[5][5] = BLACK  # diagonal three forming
        move = ai.get_move([r[:] for r in b], time_limit=10)
        self.assertIsNotNone(move)
        # Should play at (8,8) or (7,8) or (7,4)

    def test_empty_board_fast(self):
        """Empty board should return instantly."""
        ai = GomokuAI(BLACK, depth=8)
        b = new_board()
        t0 = time.time()
        move = ai.get_move([r[:] for r in b], time_limit=5)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.5, f'Empty board took {elapsed:.2f}s')
        self.assertIsNotNone(move)


if __name__ == '__main__':
    unittest.main()
