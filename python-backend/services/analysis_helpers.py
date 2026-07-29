"""
Shared helpers for analysis services.

These mirror the module-private helpers duplicated in timing_service.py and
spectrum_service.py; new services import from here instead of adding a third
copy. (Migrating the two older services to these is a separate cleanup.)
"""

import warnings as _warnings
from contextlib import contextmanager
from typing import Iterator, List, Optional

import numpy as np


def finite_list(arr) -> list:
    """Convert a float array to a list, replacing non-finite values with None."""
    values = np.asarray(arr, dtype=float)
    if np.isfinite(values).all():
        return values.tolist()
    return [float(v) if np.isfinite(v) else None for v in values]


def segment_size_error(segment_size: float, dt: float) -> Optional[str]:
    """Human-readable rejection for segment sizes that stingray fails on cryptically.

    Needs at least 3 time bins per segment to produce a non-empty spectrum.
    """
    if segment_size / dt < 3:
        return (
            f"segment_size ({segment_size}s) must be at least 3x dt ({dt}s) "
            "to produce a non-empty spectrum"
        )
    return None


def overlap_error(
    events1, events2, segment_size: Optional[float] = None
) -> Optional[str]:
    """Readable rejection when two event lists share no time overlap.

    Optional segment_size check: if provided and the overlap is shorter than
    one segment, stingray will produce zero segments (cryptic error), so we
    reject early with a human-readable message.
    """
    if len(events1.time) == 0 or len(events2.time) == 0:
        return "one of the event lists contains no events"
    start = max(float(events1.time[0]), float(events2.time[0]))
    stop = min(float(events1.time[-1]), float(events2.time[-1]))
    if stop <= start:
        return (
            "the two event lists have no overlapping time range "
            f"({events1.time[0]:.1f}-{events1.time[-1]:.1f}s vs "
            f"{events2.time[0]:.1f}-{events2.time[-1]:.1f}s)"
        )
    if segment_size is not None and (stop - start) < segment_size:
        return (
            f"the overlapping time range ({stop - start:.1f}s) is shorter than "
            f"the segment size ({segment_size}s)"
        )
    return None


@contextmanager
def collect_warnings(sink: List[str]) -> Iterator[None]:
    """Capture warnings raised inside the block into `sink` (deduplicated).

    Lets services surface stingray's low-count / NaN advisories to the UI
    instead of losing them to the server log.
    """
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        yield
    for w in caught:
        text = str(w.message)
        if text not in sink:
            sink.append(text)
