"""Dynamic time control: allocates more time for complex positions."""


class TimeController:
    """Manages total game time budget with dynamic per-move allocation.

    Analogy: chess clock with increment.
    - Early moves (opening): low complexity → fast responses
    - Late moves (midgame): high complexity → more time available
    - If early moves used less time, the surplus banks for later
    - Hard cap prevents any single move from exhausting the budget
    """

    def __init__(self, total_budget=180, min_per_move=3, max_per_move=30, moves_estimate=36):
        self.total_budget = total_budget      # seconds for entire game
        self.min_per_move = min_per_move       # floor per move
        self.max_per_move = max_per_move       # ceiling per move
        self.moves_estimate = moves_estimate   # expected total moves per side
        self.used = 0.0                        # cumulative seconds used
        self.move_count = 0                    # moves played by this side
        self.move_times = []                   # history of individual move times

    def allocate(self, board_move_count):
        """Return the time limit for the next move.

        board_move_count: total pieces on the board (both colors)
        """
        remaining = self.total_budget - self.used
        moves_left = max(1, self.moves_estimate - self.move_count)

        # Base allocation: split remaining time evenly
        base = remaining / moves_left

        # Phase adjustment: midgame positions get more time
        # Opening (< 8 pieces): use ~60% of base
        # Midgame (8-40 pieces): use ~100% of base
        # Endgame (> 40 pieces): use ~80% of base (fewer options)
        if board_move_count < 8:
            phase_factor = 0.6
        elif board_move_count < 40:
            phase_factor = 1.0
        else:
            phase_factor = 0.8

        allocated = base * phase_factor

        # Clamp within bounds
        allocated = max(self.min_per_move, min(self.max_per_move, allocated))

        # Never exceed remaining budget (leave at least 1s for future)
        allocated = min(allocated, remaining - 1)

        return max(1.0, allocated)

    def record(self, elapsed):
        """Record the time spent on the last move."""
        self.used += elapsed
        self.move_count += 1
        self.move_times.append(elapsed)

    @property
    def remaining(self):
        return max(0, self.total_budget - self.used)

    @property
    def avg_time(self):
        if not self.move_times:
            return 0
        return sum(self.move_times) / len(self.move_times)

    def stats(self):
        return (
            f'time: {self.used:.1f}/{self.total_budget:.0f}s  '
            f'avg: {self.avg_time:.1f}s  '
            f'moves: {self.move_count}'
        )
