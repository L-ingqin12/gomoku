"""Tests for board logic and win detection."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gomoku.game import find_win, is_full, new_board, in_bounds, screen_to_board, screen_to_button
from gomoku.constants import SIZE, EMPTY, BLACK, WHITE, CELL_W, LABEL_W


class TestBoardLogic(unittest.TestCase):

    def test_new_board_empty(self):
        b = new_board()
        self.assertEqual(len(b), SIZE)
        self.assertTrue(all(b[r][c] == EMPTY for r in range(SIZE) for c in range(SIZE)))

    def test_in_bounds(self):
        self.assertTrue(in_bounds(0, 0))
        self.assertTrue(in_bounds(SIZE - 1, SIZE - 1))
        self.assertFalse(in_bounds(-1, 0))
        self.assertFalse(in_bounds(0, SIZE))
        self.assertFalse(in_bounds(SIZE, SIZE))

    def test_is_full_empty(self):
        b = new_board()
        self.assertFalse(is_full(b))

    def test_is_full_true(self):
        b = new_board()
        for r in range(SIZE):
            for c in range(SIZE):
                b[r][c] = BLACK
        self.assertTrue(is_full(b))


class TestWinDetection(unittest.TestCase):

    def test_horizontal_win(self):
        b = new_board()
        for c in range(5):
            b[7][c] = BLACK
        w = find_win(b, 7, 2)
        self.assertIsNotNone(w)
        self.assertEqual(len(w), 5)
        self.assertIn((7, 0), w)
        self.assertIn((7, 4), w)

    def test_vertical_win(self):
        b = new_board()
        for r in range(5):
            b[r][3] = WHITE
        w = find_win(b, 2, 3)
        self.assertIsNotNone(w)
        self.assertEqual(len(w), 5)

    def test_diagonal_win(self):
        b = new_board()
        for i in range(5):
            b[i][i] = BLACK
        w = find_win(b, 2, 2)
        self.assertIsNotNone(w)
        self.assertEqual(len(w), 5)

    def test_anti_diagonal_win(self):
        b = new_board()
        for i in range(5):
            b[i][SIZE - 1 - i] = WHITE
        w = find_win(b, 2, SIZE - 3)
        self.assertIsNotNone(w)
        self.assertEqual(len(w), 5)

    def test_six_in_row(self):
        b = new_board()
        for c in range(6):
            b[5][c] = BLACK
        w = find_win(b, 5, 3)
        self.assertIsNotNone(w)
        self.assertGreaterEqual(len(w), 5)

    def test_no_win_four(self):
        b = new_board()
        for c in range(4):
            b[0][c] = BLACK
        w = find_win(b, 0, 1)
        self.assertIsNone(w)

    def test_no_win_mixed(self):
        b = new_board()
        b[7][0] = BLACK
        b[7][1] = BLACK
        b[7][2] = WHITE
        b[7][3] = BLACK
        b[7][4] = BLACK
        w = find_win(b, 7, 0)
        self.assertIsNone(w)

    def test_win_at_edge(self):
        b = new_board()
        for c in range(5):
            b[0][c] = BLACK
        w = find_win(b, 0, 0)
        self.assertIsNotNone(w)
        w2 = find_win(b, 0, 4)
        self.assertIsNotNone(w2)

    def test_win_found_at_last_piece_only(self):
        """Win should only be detected when the last piece completes 5."""
        b = new_board()
        for c in range(5):
            b[3][c] = BLACK
        # All 5 cells show as winning
        for c in range(5):
            w = find_win(b, 3, c)
            self.assertIsNotNone(w)


class TestCoordMapping(unittest.TestCase):

    def test_screen_to_board_valid(self):
        # board_top=4, cell 0 at LABEL_W + 0*CELL_W = 2
        result = screen_to_board(4, LABEL_W, 4)  # row 0, first cell
        self.assertEqual(result, (0, 0))

    def test_screen_to_board_outside(self):
        self.assertIsNone(screen_to_board(0, 0, 4))
        self.assertIsNone(screen_to_board(4, 0, 4))  # before label

    def test_screen_to_board_last_cell(self):
        col = LABEL_W + (SIZE - 1) * CELL_W
        result = screen_to_board(4 + SIZE - 1, col, 4)
        self.assertEqual(result, (SIZE - 1, SIZE - 1))

    def test_screen_to_button_quit(self):
        r = screen_to_button(20, 3, 20)
        self.assertEqual(r, 'quit')

    def test_screen_to_button_outside(self):
        r = screen_to_button(15, 100, 20)
        self.assertIsNone(r)

    def test_screen_to_button_row_tolerance(self):
        """±1 row tolerance."""
        r = screen_to_button(19, 3, 20)
        self.assertEqual(r, 'quit')
        r2 = screen_to_button(21, 3, 20)
        self.assertEqual(r2, 'quit')


if __name__ == '__main__':
    unittest.main()
