"""Tests for the shared analysis helpers.

Covers the two defects fixed in analysis_helpers.py:

* ``collect_warnings`` used ``warnings.catch_warnings(record=True)`` with no
  serialization, so two concurrent captures (every route dispatches through
  ``asyncio.to_thread``) could swap sinks and permanently corrupt the
  process-global warning hooks.
* ``overlap_error`` read ``time[0]``/``time[-1]`` as the span, which is wrong
  for an unsorted event list.
"""

import os
import subprocess
import sys
import threading
import warnings
from pathlib import Path

import numpy as np
import pytest

from services import analysis_helpers
from services.analysis_helpers import collect_warnings, overlap_error

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Child processes select their warnings mode with -X only, so the mode is never
# inherited from however this suite itself happens to have been launched.
CHILD_ENV = {k: v for k, v in os.environ.items()
             if k != "PYTHON_CONTEXT_AWARE_WARNINGS"}


class FakeEvents:
    """Minimal stand-in for an EventList: overlap_error only touches ``.time``."""

    def __init__(self, time):
        self.time = np.asarray(time, dtype=float)


# --------------------------------------------------------------------------
# collect_warnings thread safety
# --------------------------------------------------------------------------


# Every wait below is bounded: under the lock-based fallback the two blocks
# genuinely cannot overlap, so an unbounded wait would deadlock the suite.
_RENDEZVOUS_TIMEOUT = 0.5


def _run_interleaved_capture():
    """Drive two collect_warnings blocks through the worst-case interleave and
    return ``(sink_a, sink_b, errors)``.

    The ordering is forced, not raced -- A enters, B enters, A warns, A exits,
    B exits. Against the original unsynchronized implementation that is exactly
    the sequence which (1) records A's warning into B's sink and (2) leaves the
    process-global hook pointing at A's finished list once B exits. A correct
    implementation must put A's warning in A's sink and leave B's sink empty.
    """
    sink_a: list = []
    sink_b: list = []
    errors: list = []
    a_inside = threading.Event()
    b_inside = threading.Event()
    a_exited = threading.Event()

    def worker_a():
        try:
            with collect_warnings(sink_a):
                a_inside.set()
                # Under the lock this times out (B is still waiting to acquire);
                # without it, B really is inside its own capture by now.
                b_inside.wait(timeout=_RENDEZVOUS_TIMEOUT)
                warnings.warn("FROM-A", UserWarning)
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)
        finally:
            a_exited.set()

    def worker_b():
        try:
            a_inside.wait(timeout=10)  # A must open its capture first
            with collect_warnings(sink_b):
                b_inside.set()
                # Stay open until A has exited, so the exit order is non-LIFO.
                a_exited.wait(timeout=_RENDEZVOUS_TIMEOUT)
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [
        threading.Thread(target=worker_a),
        threading.Thread(target=worker_b),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "collect_warnings deadlocked"
    return sink_a, sink_b, errors


def test_concurrent_collect_warnings_never_swaps_sinks():
    """The warning raised in thread A must land in A's sink, not B's."""
    sink_a, sink_b, errors = _run_interleaved_capture()

    assert errors == []
    assert sink_a == ["FROM-A"], f"thread A lost its own warning: {sink_a!r}"
    assert sink_b == [], f"thread B stole another request's warning: {sink_b!r}"


@pytest.mark.skipif(
    analysis_helpers.CONTEXT_AWARE_WARNINGS,
    reason=(
        "there is no module-global capture state to orphan in context-aware "
        "mode, and replacing _showwarnmsg_impl (this test's probe) bypasses "
        "context-local recording outright"
    ),
)
def test_concurrent_collect_warnings_leaves_global_state_intact():
    """A non-LIFO interleave must not orphan ``warnings._showwarnmsg_impl``.

    Before the fix, one bad interleave left the module-global hook pointing at a
    finished capture's list, silently swallowing every warning raised anywhere in
    the process afterwards.
    """
    # Stand in for the process-wide delivery hook (under pytest the real one is
    # the plugin's own recorder). If a capture orphans the global, this sentinel
    # is what gets clobbered, exactly as stderr delivery would be in production.
    delivered: list = []

    def sentinel(msg):
        delivered.append(str(msg.message))

    original_impl = warnings._showwarnmsg_impl
    saved_filters = warnings.filters[:]
    warnings._showwarnmsg_impl = sentinel
    try:
        _, _, errors = _run_interleaved_capture()
        assert errors == []

        # The hook must still be ours, not some finished capture's list.append.
        assert warnings._showwarnmsg_impl is sentinel, (
            "collect_warnings orphaned the global warning hook: "
            f"{warnings._showwarnmsg_impl!r}"
        )
        warnings.simplefilter("always")
        warnings.warn("AFTER-THE-FACT", UserWarning)
        assert delivered == ["AFTER-THE-FACT"], (
            "warnings raised outside any capture were swallowed: "
            f"{delivered!r}, hook={warnings._showwarnmsg_impl!r}"
        )
    finally:
        warnings._showwarnmsg_impl = original_impl
        warnings.filters[:] = saved_filters
        warnings._filters_mutated()


def test_lock_fallback_is_active_when_context_aware_warnings_is_off():
    """The two branches are chosen by the interpreter flag, not by luck."""
    if analysis_helpers.CONTEXT_AWARE_WARNINGS:
        assert analysis_helpers._CAPTURE_LOCK is None
    else:
        assert analysis_helpers._CAPTURE_LOCK is not None


# The context-aware branch cannot be toggled inside a running interpreter
# (sys.flags is read-only), so exercise it in a subprocess launched with the
# -X flag. Skipped automatically on interpreters that lack the mode.
_CONTEXT_AWARE_CHILD = r"""
import sys, threading, warnings
sys.path.insert(0, {backend!r})
from services import analysis_helpers
from services.analysis_helpers import collect_warnings

assert analysis_helpers.CONTEXT_AWARE_WARNINGS, "flag did not take effect"
assert analysis_helpers._CAPTURE_LOCK is None, "lock-free branch not selected"

sinks = {{"A": [], "B": []}}
a_inside = threading.Event()
b_inside = threading.Event()
a_exited = threading.Event()

original_impl = warnings._showwarnmsg_impl


def worker_a():
    with collect_warnings(sinks["A"]):
        a_inside.set()
        assert b_inside.wait(10), "B never entered its capture"
        warnings.warn("FROM-A", UserWarning)
    a_exited.set()


def worker_b():
    assert a_inside.wait(10), "A never entered its capture"
    with collect_warnings(sinks["B"]):
        b_inside.set()
        assert a_exited.wait(10), "A never exited its capture"


threads = [threading.Thread(target=worker_a), threading.Thread(target=worker_b)]
for t in threads:
    t.start()
for t in threads:
    t.join(20)
    assert not t.is_alive(), "deadlock"

assert sinks["A"] == ["FROM-A"], sinks
assert sinks["B"] == [], sinks
assert warnings._showwarnmsg_impl is original_impl, "global hook orphaned"
print("OK")
"""


@pytest.mark.skipif(
    not hasattr(sys.flags, "context_aware_warnings"),
    reason="interpreter has no context-aware warnings mode (needs Python 3.14+)",
)
def test_context_aware_branch_isolates_overlapping_captures():
    """With -X context_aware_warnings=1 the captures are isolated lock-free.

    This is the branch production/dev launches take (electron/pythonManager.ts
    sets PYTHON_CONTEXT_AWARE_WARNINGS=1, `npm run python:dev` passes -X), so it
    needs coverage even though the test suite itself runs in the default mode.
    """
    script = _CONTEXT_AWARE_CHILD.format(backend=str(BACKEND_ROOT))
    proc = subprocess.run(
        [sys.executable, "-X", "context_aware_warnings=1", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=CHILD_ENV,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


# The context-aware path does not reset warnings.showwarning on entry the way
# the legacy path does, so a global showwarning replacement that fails to chain
# would silently empty every `data.warnings` array. main.py's lifespan installs
# exactly such a replacement (utils/log_stream.py), so pin the real posture.
_LOG_STREAM_CHILD = r"""
import logging, sys, threading, warnings
sys.path.insert(0, {backend!r})
from services import analysis_helpers
from services.analysis_helpers import collect_warnings
from utils.log_stream import log_stream_manager

assert analysis_helpers.CONTEXT_AWARE_WARNINGS is {expect_context_aware!r}, (
    "wrong warnings mode: %r" % (analysis_helpers.CONTEXT_AWARE_WARNINGS,)
)

# Exactly what main.py's lifespan does before serving any request.
log_stream_manager.install(log_level=logging.CRITICAL)
assert warnings.showwarning is not warnings._showwarning_orig, "hook not installed"

sink = []


def run():
    with collect_warnings(sink):
        warnings.warn("SIMON says: Low count rate in the subject band", UserWarning)


t = threading.Thread(target=run)
t.start()
t.join(10)
assert not t.is_alive(), "deadlock"
assert sink == ["SIMON says: Low count rate in the subject band"], sink
print("OK")
"""


@pytest.mark.parametrize(
    "extra_args, expect_context_aware",
    [
        pytest.param([], False, id="lock-fallback"),
        pytest.param(
            ["-X", "context_aware_warnings=1"], True, id="context-aware"
        ),
    ],
)
def test_capture_survives_the_log_stream_showwarning_hook(
    extra_args, expect_context_aware
):
    """Warnings still reach the sink with the app's global hook installed."""
    if expect_context_aware and not hasattr(sys.flags, "context_aware_warnings"):
        pytest.skip("interpreter has no context-aware warnings mode")
    script = _LOG_STREAM_CHILD.format(
        backend=str(BACKEND_ROOT), expect_context_aware=expect_context_aware
    )
    proc = subprocess.run(
        [sys.executable, *extra_args, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=CHILD_ENV,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


def test_collect_warnings_deduplicates_and_releases_the_lock_on_error():
    """Sanity: the wrapper still dedupes, and an exception does not wedge it."""
    sink: list = []
    with collect_warnings(sink):
        warnings.warn("dupe", UserWarning)
        warnings.warn("dupe", UserWarning)
        warnings.warn("other", UserWarning)
    assert sink == ["dupe", "other"]

    with pytest.raises(RuntimeError):
        with collect_warnings([]):
            raise RuntimeError("boom")

    # The lock must have been released, so a later capture still works.
    after: list = []
    with collect_warnings(after):
        warnings.warn("after-error", UserWarning)
    assert after == ["after-error"]


# --------------------------------------------------------------------------
# overlap_error on unsorted event times
# --------------------------------------------------------------------------


def test_overlap_error_accepts_unsorted_lists_that_do_overlap():
    """Two fully simultaneous observations must not be rejected when unsorted.

    Permuting the times so that ``time[0] > time[-1]`` used to make
    ``stop <= start``, producing a bogus "no overlapping time range" rejection.
    """
    sorted_times = np.linspace(0.0, 100.0, 501)
    shuffled = sorted_times.copy()
    rng = np.random.default_rng(7)
    rng.shuffle(shuffled)
    assert shuffled[0] > shuffled[-1], "fixture is not exercising the bug"

    unsorted_events = FakeEvents(shuffled)
    sorted_events = FakeEvents(sorted_times)

    assert overlap_error(unsorted_events, sorted_events) is None
    assert overlap_error(sorted_events, unsorted_events) is None
    assert overlap_error(unsorted_events, unsorted_events) is None


def test_overlap_error_uses_true_span_for_the_segment_size_check():
    """The segment check must measure the real overlap, not the stored endpoints."""
    shuffled = np.array([50.0, 0.0, 100.0, 25.0, 49.0])
    events = FakeEvents(shuffled)
    other = FakeEvents(np.linspace(0.0, 100.0, 11))

    # True overlap is 100s: a 60s segment fits, a 120s segment does not.
    assert overlap_error(events, other, segment_size=60.0) is None
    message = overlap_error(events, other, segment_size=120.0)
    assert message is not None
    assert "100.0s" in message


def test_overlap_error_still_rejects_genuinely_disjoint_lists():
    """The min/max fix must not weaken the real rejection, and must report the
    true spans in the message."""
    early = FakeEvents([5.0, 1.0, 9.0, 3.0])
    late = FakeEvents([40.0, 20.0, 30.0])

    message = overlap_error(early, late)
    assert message is not None
    assert "no overlapping time range" in message
    assert "1.0-9.0s" in message
    assert "20.0-40.0s" in message


def test_overlap_error_rejects_empty_lists():
    assert (
        overlap_error(FakeEvents([]), FakeEvents([1.0, 2.0]))
        == "one of the event lists contains no events"
    )
