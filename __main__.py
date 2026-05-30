"""Entry point: python -m gomoku  or  python gomoku.py"""

import curses
import os
import json
import time

from .constants import BLACK, WHITE
from .constants import CP_BOARD, CP_BLACK, CP_WHITE, CP_CURSOR, CP_BUTTON, CP_WIN, CP_MENU
from .ui import show_menu, show_message
from .modes import run_local, run_pve, run_eve, run_shared
from .network import run_host, run_join
from .kifu import run_replay


def main(stdscr):
    # Color setup
    curses.start_color()
    curses.use_default_colors()
    curses.curs_set(0)
    stdscr.nodelay(0)
    stdscr.keypad(1)

    curses.init_pair(CP_BOARD, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_BLACK, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(CP_WHITE, curses.COLOR_WHITE, curses.COLOR_YELLOW)
    curses.init_pair(CP_CURSOR, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(CP_BUTTON, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(CP_WIN, curses.COLOR_BLACK, curses.COLOR_RED)
    curses.init_pair(CP_MENU, curses.COLOR_WHITE, curses.COLOR_BLUE)

    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
    except Exception:
        pass

    while True:
        choice = show_menu(stdscr)
        if choice == 'local':
            run_local(stdscr)
        elif choice == 'host':
            run_host(stdscr)
        elif choice == 'join':
            run_join(stdscr)
        elif choice == 'shared':
            run_shared(stdscr)
        elif choice == 'pve':
            run_pve(stdscr)
        elif choice == 'eve':
            run_eve(stdscr)
        elif choice == 'replay':
            run_replay(stdscr)
        elif choice == 'load':
            from .constants import SAVE_FILE
            if os.path.exists(SAVE_FILE):
                with open(SAVE_FILE) as f:
                    data = json.load(f)
                run_local(stdscr, initial=data)
            else:
                show_message(stdscr, 'No saved game found.')
        elif choice == 'quit':
            break


if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'Error: {e}')
        raise
