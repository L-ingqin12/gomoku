#!/usr/bin/env python3
"""
Gomoku (五子棋) — terminal curses game.
Modes: Local / Network / Shared / PvE AI / EvE AI / Replay

Usage: python gomoku.py   or   python -m gomoku
"""

# Redirect to the package entry point
if __name__ == '__main__':
    import sys, os
    # Ensure the parent directory is on sys.path so 'gomoku' package is found
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _parent_dir = os.path.dirname(_script_dir)
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    # Also add the script directory for direct imports within the package
    if _script_dir not in sys.path:
        sys.path.insert(0, _script_dir)

    from gomoku.__main__ import main
    import curses
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'Error: {e}')
        raise
