"""Bounded CPU I/O prefetch and conservative, metadata-only split hints."""
from concurrent.futures import ThreadPoolExecutor
import math
from statistics import median


def staged_items(items, prepare):
    """One prepared successor at most; propagate errors and join on exit."""
    iterator = iter(items)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='window-io') as pool:
        current = next(iterator, None)
        if current is None:
            return
        future = pool.submit(prepare, current)
        while current is not None:
            result = future.result()
            successor = next(iterator, None)
            if successor is not None:
                future = pool.submit(prepare, successor)
            yield current, result
            current = successor


def split_window(rows, minimum=12, overlap=6):
    """Prefer a strong interior GPS-speed jump or texture dip; retain every frame."""
    n = len(rows)
    if n < 2 * minimum:
        raise ValueError('Window is too short to split')
    middle, reason = n // 2, 'balanced_midpoint'
    speeds = [float(row.get('baseline_m') or 0) / max(0.001,
              float(row['time_s']) - float(rows[i-1]['time_s']))
              for i, row in enumerate(rows) if i]
    positive = [v for v in speeds if math.isfinite(v) and v > 0]
    typical = median(positive) if positive else 0
    sharp = [float(row.get('sharpness') or 0) for row in rows]
    usual_sharp = median(sharp)
    hints = []
    for i in range(minimum, n - minimum + 1):
        if speeds[i-1] > max(30.0, 5 * typical):
            hints.append((speeds[i-1] / max(typical, 1), i, 'gps_speed_jump'))
        if usual_sharp > 0 and sharp[i] < 0.15 * usual_sharp:
            hints.append((usual_sharp / max(sharp[i], 1), i, 'sharpness_drop'))
    if hints:
        _, middle, reason = max(hints, key=lambda x: (x[0], -abs(x[1] - n/2)))
    band = min(overlap, max(2, n // 8), middle - 1, n - middle - 1)
    return rows[:middle + band], rows[middle - band:], reason
