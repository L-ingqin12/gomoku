"""Board logic and coordinate mapping."""

from .constants import SIZE, EMPTY, BLACK, WHITE, DIRS, CELL_W, LABEL_W, BTN_MAP


def in_bounds(r, c):
    return 0 <= r < SIZE and 0 <= c < SIZE


def find_win(board, r, c):
    """Return sorted list of (r,c) forming a winning line, or None."""
    p = board[r][c]
    for dr, dc in DIRS:
        cells = [(r, c)]
        for s in (1, -1):
            step = 1
            while True:
                nr, nc = r + dr * step * s, c + dc * step * s
                if in_bounds(nr, nc) and board[nr][nc] == p:
                    cells.append((nr, nc))
                    step += 1
                else:
                    break
        if len(cells) >= 5:
            cells.sort()
            return cells
    return None


def is_full(board):
    for row in board:
        if EMPTY in row:
            return False
    return True


def new_board():
    return [[EMPTY] * SIZE for _ in range(SIZE)]


# ── coordinate mapping ──────────────────────────────────────────────────

def screen_to_board(scr_row, scr_col, board_top):
    r = scr_row - board_top
    if not (0 <= r < SIZE):
        return None
    for c in range(SIZE):
        left = LABEL_W + c * CELL_W
        right = left + 1
        if left <= scr_col <= right:
            return (r, c)
    return None


def screen_to_button(scr_row, scr_col, btn_row):
    if abs(scr_row - btn_row) > 1:
        return None
    for name, (lx, rx) in BTN_MAP.items():
        if lx <= scr_col <= rx:
            return name
    return None
