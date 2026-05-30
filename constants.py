"""Shared constants for the Gomoku game."""

SIZE = 15
EMPTY = 0
BLACK = 1
WHITE = 2

PIECE_CH = {EMPTY: '┼', BLACK: '●', WHITE: '○'}
HLINE = '─'
DIRS = [(0, 1), (1, 0), (1, 1), (1, -1)]

# Layout
CELL_W = 2
LABEL_W = 2

# Color pair IDs
CP_BOARD = 1
CP_BLACK = 2
CP_WHITE = 3
CP_CURSOR = 4
CP_BUTTON = 5
CP_WIN = 6
CP_MENU = 7

# Button definitions
BTN_TEXT = ' [Quit]  [Restart]  [Undo]  [Save]'
BTN_MAP = {'quit': (1, 6), 'restart': (9, 18), 'undo': (21, 27), 'save': (30, 36)}

# Files — stored in project workspace
import os as _os
_PROJECT_DIR = _os.path.dirname(_os.path.abspath(__file__))
SAVE_FILE = _os.path.join(_PROJECT_DIR, 'save.json')
KIFU_DIR = _os.path.join(_PROJECT_DIR, 'kifu')
SHARED_FILE = '/tmp/gomoku_shared.json'
DEFAULT_PORT = 9999

# AI pattern scores
WIN_SCORE = 100_000_000
FOUR_SCORE = 10_000_000
THREE_SCORE = 100_000
TWO_SCORE = 1_000
