#!/usr/bin/env python3
"""
Gomoku (五子棋) — terminal curses game.
Modes: Local / Network / Shared / PvE AI / EvE AI / Replay

Usage: python gomoku.py   or   python -m gomoku
"""

# Redirect to the package entry point
if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gomoku.__main__ import main
    import curses
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'Error: {e}')
        raise
