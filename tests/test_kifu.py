"""Tests for kifu save/load."""

import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gomoku.constants import BLACK, WHITE, KIFU_DIR
from gomoku.kifu import Kifu


class TestKifu(unittest.TestCase):

    def setUp(self):
        os.makedirs(KIFU_DIR, exist_ok=True)

    def test_record_and_save(self):
        k = Kifu('test', 'unit test game')
        k.record(7, 7, BLACK)
        k.record(7, 8, WHITE)
        k.result = 'Black wins'
        k.score = {BLACK: 1, WHITE: 0}
        fname = k.save()

        self.assertTrue(os.path.exists(fname))
        with open(fname) as f:
            data = json.load(f)
        self.assertEqual(len(data['moves']), 2)
        self.assertEqual(data['result'], 'Black wins')
        self.assertEqual(data['mode'], 'test')

        os.remove(fname)

    def test_load(self):
        k = Kifu('load_test', 'load test')
        k.record(0, 0, BLACK)
        k.record(0, 1, WHITE)
        k.record(0, 2, BLACK)
        fname = k.save()

        loaded = Kifu.load(fname)
        self.assertEqual(len(loaded.moves), 3)
        self.assertEqual(tuple(loaded.moves[0][:3]), (0, 0, BLACK))
        self.assertEqual(tuple(loaded.moves[1][:3]), (0, 1, WHITE))
        self.assertEqual(loaded.mode, 'load_test')

        os.remove(fname)

    def test_empty_save(self):
        k = Kifu()
        fname = k.save()
        loaded = Kifu.load(fname)
        self.assertEqual(len(loaded.moves), 0)
        self.assertEqual(loaded.result, '')
        os.remove(fname)

    def test_list_files(self):
        files_before = Kifu.list_files()
        k = Kifu('list_test')
        fname = k.save()
        files_after = Kifu.list_files()
        self.assertGreaterEqual(len(files_after), len(files_before))
        self.assertIn(fname, files_after)
        os.remove(fname)


if __name__ == '__main__':
    unittest.main()
