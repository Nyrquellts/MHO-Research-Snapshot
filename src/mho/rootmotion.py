"""Resample caller-provided root-motion tracks while retaining original key times."""
from __future__ import annotations

import math
from collections.abc import Sequence

KeyTrack = Sequence[tuple[float, float]]


def _sample(keys: KeyTrack, time: float) -> float:
    if not keys:
        return 0.0
    if time <= keys[0][0]:
        return keys[0][1]
    for (start_time, start_value), (end_time, end_value) in zip(keys, keys[1:]):
        if time <= end_time:
            fraction = (time - start_time) / (end_time - start_time) if end_time > start_time else 1.0
            return start_value + (end_value - start_value) * fraction
    return keys[-1][1]


def resample_root_motion(
    duration: float,
    *,
    step: float = 1 / 15,
    x: KeyTrack = (),
    y: KeyTrack = (),
    z: KeyTrack = (),
    yaw: KeyTrack = (),
) -> dict[str, list[list[float]]]:
    """Return position and yaw samples for tracks whose values change over the clip.

    Position rows contain time, x, y, and z. Yaw rows contain time and angle.
    Original key times inside the clip are retained alongside the regular grid.
    """
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("duration must be finite and nonnegative")
    if not math.isfinite(step) or step <= 0:
        raise ValueError("step must be finite and positive")

    px, py, pz, rz = (sorted(track) for track in (x, y, z, yaw))
    sample_count = max(1, int(round(duration / step)))
    candidates = sorted({
        0.0, duration,
        *(min(duration, index * step) for index in range(sample_count + 1)),
        *(time for keys in (px, py, pz, rz) for time, _ in keys if 0.0 <= time <= duration),
    })
    times: list[float] = []
    for time in candidates:
        if times and time - times[-1] <= max(1e-5, abs(time) * 1e-7):
            times[-1] = time
        else:
            times.append(time)

    result: dict[str, list[list[float]]] = {}
    if any(abs(_sample(keys, time) - _sample(keys, 0)) > 1e-3 for keys in (px, py, pz) for time in times):
        result["pos"] = [
            [time, round(_sample(px, time), 3), round(_sample(py, time), 3), round(_sample(pz, time), 3)]
            for time in times
        ]
    if any(abs(_sample(rz, time) - _sample(rz, 0)) > 1e-2 for time in times):
        result["yaw"] = [[time, round(_sample(rz, time), 2)] for time in times]
    return result
