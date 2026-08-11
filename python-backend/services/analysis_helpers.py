"""
Shared helpers for analysis services.

These mirror the module-private helpers duplicated in timing_service.py and
spectrum_service.py; new services import from here instead of adding a third
copy. (Migrating the two older services to these is a separate cleanup.)
"""

import sys as _sys
import threading as _threading
import warnings as _warnings
from contextlib import contextmanager
from typing import Iterator, List, Optional

import numpy as np

# CPython 3.14 added "context-aware warnings": when enabled, catch_warnings
# stores its saved state in a contextvars.ContextVar instead of module globals,
# which makes concurrent captures genuinely isolated (asyncio.to_thread copies
# the caller's context per call, and a plain threading.Thread starts with its
# own context, so neither can see another block's saved state).
#
# The flag is off by default. It can be turned on with -X context_aware_warnings=1
# or PYTHON_CONTEXT_AWARE_WARNINGS=1; electron/pythonManager.ts and the
# `python:dev` npm script set it so real launches get the fast path.
# getattr() keeps this importable on Python < 3.14, where the flag does not exist.
#
# Caveat that mode carries: the legacy catch_warnings(record=True) resets
# warnings.showwarning to the default on entry so recording cannot be bypassed,
# but the context-aware path does not. So in that mode anything which replaces
# the global warnings.showwarning must chain to the handler it displaced, or
# capture here silently yields an empty list. utils/log_stream.py (installed for
# the whole process by main.py's lifespan) does chain - see its _capture_warning
# - and tests/test_analysis_helpers.py pins that down in both modes.
CONTEXT_AWARE_WARNINGS = bool(getattr(_sys.flags, "context_aware_warnings", 0))

# Fallback for interpreters without that mode: serialize warning capture.
#
# warnings.catch_warnings(record=True) mutates PROCESS-GLOBAL state
# (warnings.filters, warnings.showwarning, warnings._showwarnmsg_impl) on entry
# and restores whatever it saw on exit. Every analysis service runs its stingray
# call inside collect_warnings, and every route dispatches through
# asyncio.to_thread onto the default multi-worker executor, so two in-flight
# requests really do execute these blocks concurrently. Without serialization
# that produces two verified failure modes:
#
#   1. Misattribution - if block B enters while block A is still open, A's
#      warnings are recorded into B's sink and A's sink comes back empty. A
#      stingray advisory about one request's data is then rendered in another
#      request's warning Alert, and dropped from the response it belongs to.
#   2. Permanent global corruption - with a non-LIFO interleave (A enters, B
#      enters, A exits, B exits), B's __exit__ restores the _showwarnmsg_impl it
#      captured on entry, which is A's now-orphaned record list. Every warning
#      raised anywhere in the process afterwards is silently appended to that
#      dead list instead of reaching stderr/the server log, for the lifetime of
#      the backend.
#
# An RLock (not a plain Lock) so that a future nested collect_warnings on the
# same thread cannot deadlock; nesting within a single thread is already safe
# because catch_warnings restores in LIFO order there.
_CAPTURE_LOCK = None if CONTEXT_AWARE_WARNINGS else _threading.RLock()


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
    # min/max rather than time[0]/time[-1]: event times are not guaranteed to be
    # sorted (stingray only sorts when skip_checks is False, and EventList.read
    # bypasses that path entirely), and an unsorted list would otherwise report a
    # sliver of its true span - falsely rejecting two simultaneous observations.
    first1, last1 = float(np.min(events1.time)), float(np.max(events1.time))
    first2, last2 = float(np.min(events2.time)), float(np.max(events2.time))
    start = max(first1, first2)
    stop = min(last1, last2)
    if stop <= start:
        return (
            "the two event lists have no overlapping time range "
            f"({first1:.1f}-{last1:.1f}s vs "
            f"{first2:.1f}-{last2:.1f}s)"
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

    Thread safety: catch_warnings is only safe to run concurrently when the
    interpreter has context-aware warnings enabled (see CONTEXT_AWARE_WARNINGS
    above). When it does not, the capture is serialized on _CAPTURE_LOCK, which
    is held for the whole block so that entry and exit are strictly LIFO across
    threads. That costs concurrency on the analysis call inside, but it is the
    only way to stop concurrent requests from stealing each other's warnings and
    from permanently corrupting the process-global warning hooks.
    """
    if _CAPTURE_LOCK is None:
        with _capture_warnings(sink):
            yield
    else:
        with _CAPTURE_LOCK:
            with _capture_warnings(sink):
                yield


@contextmanager
def _capture_warnings(sink: List[str]) -> Iterator[None]:
    """The raw catch_warnings capture, without any locking."""
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        yield
    for w in caught:
        text = str(w.message)
        if text not in sink:
            sink.append(text)
