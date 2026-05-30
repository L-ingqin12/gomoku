"""TDD tests for dynamic time control."""

import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gomoku.timectrl import TimeController


class TestTimeController(unittest.TestCase):

    def test_initial_allocate(self):
        tc = TimeController(total_budget=180)
        t = tc.allocate(board_move_count=0)
        # Opening: 180/36 * 0.6 = 3.0, clamped to min 3
        self.assertGreaterEqual(t, 3.0)
        self.assertLessEqual(t, 30.0)

    def test_allocate_midgame_higher(self):
        tc = TimeController(total_budget=180)
        t_open = tc.allocate(board_move_count=2)
        t_mid = tc.allocate(board_move_count=20)
        # Midgame should get higher phase factor than opening
        # Both use same base budget since no time consumed
        self.assertGreaterEqual(t_mid, t_open * 0.9)

    def test_record_reduces_budget(self):
        tc = TimeController(total_budget=180)
        before = tc.remaining
        tc.record(10.0)
        self.assertEqual(tc.remaining, before - 10.0)
        self.assertEqual(tc.move_count, 1)

    def test_used_time_reduces_future_allocation(self):
        tc = TimeController(total_budget=120, min_per_move=1)
        # Use half the budget
        tc.record(60.0)
        tc.move_count = 10
        t = tc.allocate(board_move_count=20)
        # Remaining: 60s, moves left: 36-10=26
        # base = 60/26 = 2.3, phase 1.0 = 2.3
        self.assertLess(t, 5.0)

    def test_never_exceed_remaining(self):
        tc = TimeController(total_budget=30, min_per_move=1, max_per_move=60)
        tc.record(28.0)
        tc.move_count = 35  # near end
        t = tc.allocate(board_move_count=40)
        # remaining = 2s, moves_left = 36-35=1
        # base = 2/1 = 2, phase=0.8, allocated=1.6
        # clamp: max(1, min(60, 1.6)) = 1.6
        # never exceed: min(1.6, 1) = 1.0
        self.assertLessEqual(t, tc.remaining)

    def test_hard_cap(self):
        tc = TimeController(total_budget=600, max_per_move=30)
        t = tc.allocate(board_move_count=1)
        self.assertLessEqual(t, 30.0)

    def test_floor(self):
        tc = TimeController(total_budget=30, min_per_move=3)
        tc.record(29.0)
        tc.move_count = 35
        t = tc.allocate(board_move_count=40)
        # Should hit the floor of 3, but also never exceed remaining
        self.assertGreaterEqual(t, 1.0)  # at least 1s always

    def test_avg_time_tracks_history(self):
        tc = TimeController()
        tc.record(5.0)
        tc.record(15.0)
        self.assertAlmostEqual(tc.avg_time, 10.0)

    def test_stats_string(self):
        tc = TimeController(total_budget=180)
        tc.record(3.5)
        s = tc.stats()
        self.assertIn('time:', s)
        self.assertIn('avg:', s)
        self.assertIn('moves:', s)


if __name__ == '__main__':
    unittest.main()
