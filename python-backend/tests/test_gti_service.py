"""Tests for the Utilities GTI service and its asynchronous route boundary."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import pytest
import services.gti_service as gti_module
import stingray
from fastapi import FastAPI
from routes import gti_routes
from services.gti_service import GTIService
from services.state_manager import StateManager
from stingray import EventList
from stingray.gti import (
    append_gtis,
    create_gti_mask,
    cross_two_gtis,
    get_btis,
    merge_gtis,
    split_gtis_by_exposure,
    time_intervals_from_gtis,
)


def _result_gtis(result: dict, key: str = "intervals") -> np.ndarray:
    rows = result["data"][key]
    if not rows:
        return np.empty((0, 2))
    return np.asarray([[row["start"], row["stop"]] for row in rows])


def _state_with_events() -> tuple[StateManager, EventList]:
    state = StateManager()
    events = EventList(
        time=np.arange(0.5, 10.0, 1.0),
        energy=np.linspace(1.0, 10.0, 10),
        pi=np.arange(10),
        gti=np.asarray([[0.0, 4.0], [6.0, 10.0]]),
        dt=0,
        mjdref=59000.0,
    )
    state.add_event_data("source", events)
    return state, events


def test_inspect_reports_all_intervals_and_scientific_summary():
    state, _ = _state_with_events()

    result = GTIService(state).inspect("source")

    assert result["success"] is True
    assert result["data"]["gti_status"] == "available"
    assert result["data"]["interval_count"] == 2
    assert result["data"]["lengths_s"] == [4.0, 4.0]
    assert result["data"]["separations_s"] == [2.0]
    assert result["data"]["total_exposure_s"] == 8.0
    assert result["data"]["overall_time_span_s"] == 10.0
    assert result["data"]["duty_cycle"] == pytest.approx(0.8)
    assert result["data"]["mjdref"] == 59000.0
    assert result["data"]["provenance"]["stingray_version"] == stingray.__version__


def test_inspect_handles_missing_and_empty_gtis_without_mutating_source():
    state = StateManager()
    missing = EventList()
    empty = EventList(time=[1.0, 2.0], gti=np.empty((0, 2)))
    inferred = EventList(time=[1.0, 2.0, 3.0])
    state.add_event_data("missing", missing)
    state.add_event_data("empty", empty)
    state.add_event_data("inferred", inferred)

    missing_result = GTIService(state).inspect("missing")
    empty_result = GTIService(state).inspect("empty")
    inferred_result = GTIService(state).inspect("inferred")

    assert missing_result["data"]["gti_status"] == "missing"
    assert empty_result["data"]["gti_status"] == "empty"
    assert empty_result["data"]["total_exposure_s"] == 0.0
    assert inferred_result["data"]["gti_status"] == "missing"
    assert inferred_result["data"]["intervals"] == []
    assert any(
        "no effective GTI" in warning for warning in inferred_result["data"]["warnings"]
    )
    # EventList.gti would synthesize [time[0], time[-1]] in Stingray 2.2.10.
    # Inspection deliberately avoids that property so missing metadata remains
    # explicit and consistent with the renderer's no-synthesis explanation.
    assert inferred._gti is None


def test_inspect_rejects_missing_name():
    result = GTIService(StateManager()).inspect("unknown")

    assert result["success"] is False
    assert "not found" in result["message"]


@pytest.mark.parametrize(
    ("gtis", "message_fragment"),
    [
        ([[0.0]], "exactly [start, stop]"),
        ([[0.0, np.nan]], "interval 1 stop must be finite"),
        ([[0.0, "1"]], "interval 1 stop must be a finite number"),
        ([[False, 1.0]], "interval 1 start must be a finite number"),
        ([[1.0, 1.0]], "interval 1 must have positive length"),
        ([[2.0, 3.0], [0.0, 1.0]], "interval 2 starts"),
        ([[0.0, 2.0], [1.0, 3.0]], "interval 2 starts at 1.0 and overlaps"),
    ],
)
def test_validate_rejects_malformed_nonfinite_zero_unsorted_and_overlap(
    gtis, message_fragment
):
    result = GTIService(StateManager()).validate(gtis)

    assert result["success"] is False
    assert message_fragment in result["message"]


def test_validate_caps_gti_and_row_generators_before_unbounded_materialization():
    consumed_rows: list[int] = []

    def oversized_gtis():
        for index in range(100):
            consumed_rows.append(index)
            yield [float(index * 2), float(index * 2 + 1)]

    array, error = gti_module._validate_gti_array(oversized_gtis(), max_rows=2)

    assert array is None
    assert error == "GTIs contain at least 3 rows; the cap is 2"
    assert consumed_rows == [0, 1, 2]

    consumed_values: list[int] = []

    def oversized_row():
        for value in range(100):
            consumed_values.append(value)
            yield float(value)

    array, error = gti_module._validate_gti_array([oversized_row()])

    assert array is None
    assert error == (
        "GTIs interval 1 has at least 3 value(s); exactly [start, stop] is required"
    )
    assert consumed_values == [0, 1, 2]


@pytest.mark.parametrize("gtis", ["0,1", {0: [0.0, 1.0]}, True])
def test_validate_rejects_non_array_gti_containers(gtis):
    result = GTIService(StateManager()).validate(gtis)

    assert result["success"] is False
    assert "array of [start, stop] rows" in result["message"]


@pytest.mark.parametrize(
    ("operation", "upstream"),
    [
        ("intersection", lambda left, right: cross_two_gtis(left, right)),
        ("union", lambda left, right: merge_gtis([left, right], "union")),
        ("append", lambda left, right: append_gtis(left, right)),
    ],
)
def test_set_operations_match_direct_stingray(operation, upstream):
    if operation == "append":
        left = np.asarray([[0.0, 1.0], [4.0, 5.0]])
        right = np.asarray([[2.0, 3.0], [6.0, 7.0]])
    else:
        left = np.asarray([[0.0, 3.0], [5.0, 8.0]])
        right = np.asarray([[2.0, 6.0], [7.0, 9.0]])

    result = GTIService(StateManager()).set_operation(left, right, operation)

    assert result["success"] is True
    np.testing.assert_allclose(_result_gtis(result), upstream(left, right))


def test_intersection_guards_stingray_empty_shape_and_append_checks_precondition():
    service = GTIService(StateManager())

    empty = service.set_operation([[0.0, 1.0]], [[2.0, 3.0]], "intersection")
    invalid_append = service.set_operation([[0.0, 2.0]], [[1.0, 3.0]], "append")

    assert empty["success"] is True
    assert _result_gtis(empty).shape == (0, 2)
    assert "no shared" in empty["data"]["warnings"][0]
    assert invalid_append["success"] is False
    assert "mutually exclusive" in invalid_append["message"]


def test_union_cap_is_checked_before_stingray_allocation(monkeypatch):
    monkeypatch.setattr(gti_module, "MAX_GTI_ROWS", 2)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Stingray must not run after the cap fails")

    monkeypatch.setattr(gti_module, "merge_gtis", must_not_run)
    result = GTIService(StateManager()).set_operation(
        [[0.0, 1.0], [2.0, 3.0]], [[4.0, 5.0]], "union"
    )

    assert result["success"] is False
    assert "cap" in result["message"]


def test_bad_time_intervals_match_direct_stingray_and_allow_empty_gti():
    service = GTIService(StateManager())
    gtis = np.asarray([[1.0, 2.0], [4.0, 5.0]])

    result = service.bad_time_intervals(gtis, 0.0, 6.0)
    empty = service.bad_time_intervals([], 0.0, 6.0)

    assert result["success"] is True
    np.testing.assert_allclose(
        _result_gtis(result), get_btis(gtis, start_time=0.0, stop_time=6.0)
    )
    np.testing.assert_allclose(_result_gtis(empty), [[0.0, 6.0]])


def test_bad_time_intervals_omit_stingray_zero_duration_touch_boundary():
    result = GTIService(StateManager()).bad_time_intervals(
        [[0.0, 1.0], [1.0, 2.0]], 0.0, 2.0
    )

    assert result["success"] is True
    assert result["data"]["intervals"] == []
    assert "zero-duration" in result["data"]["warnings"][0]


def test_bad_time_interval_cap_is_checked_before_stingray(monkeypatch):
    monkeypatch.setattr(gti_module, "MAX_GTI_ROWS", 2)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Stingray must not run after the cap fails")

    monkeypatch.setattr(gti_module, "get_btis", must_not_run)
    result = GTIService(StateManager()).bad_time_intervals(
        [[1.0, 2.0], [3.0, 4.0]], 0.0, 5.0
    )

    assert result["success"] is False
    assert "cap" in result["message"]


@pytest.mark.parametrize(
    ("start", "stop", "fragment"),
    [
        (1.0, 1.0, "greater than"),
        (np.nan, 3.0, "start_time must be finite"),
        (1.0, np.inf, "stop_time must be finite"),
    ],
)
def test_bad_time_intervals_reject_invalid_range(start, stop, fragment):
    result = GTIService(StateManager()).bad_time_intervals([], start, stop)

    assert result["success"] is False
    assert fragment in result["message"]


def test_mask_preview_matches_stingray_and_intersects_source_exposure():
    state, source = _state_with_events()
    requested = np.asarray([[1.0, 3.0], [7.0, 12.0]])
    effective = cross_two_gtis(source.gti, requested)
    expected_mask = create_gti_mask(source.time, effective, dt=source.dt)

    result = GTIService(state).mask_preview("source", requested)

    assert result["success"] is True
    assert result["data"]["retained_event_count"] == int(
        np.count_nonzero(expected_mask)
    )
    assert result["data"]["rejected_event_count"] == int(
        len(source.time) - np.count_nonzero(expected_mask)
    )
    assert result["data"]["retained_exposure_s"] == pytest.approx(5.0)
    assert result["data"]["time_unit"] == "s"
    assert result["data"]["time_reference"] == "absolute_mission_time"
    applied_rows = result["data"]["applied_gtis"]["intervals"]
    applied = np.asarray([[row["start"], row["stop"]] for row in applied_rows])
    np.testing.assert_allclose(applied, effective)
    assert any("clipped" in warning for warning in result["data"]["warnings"])


def test_mask_preview_is_bounded_and_json_safe(monkeypatch):
    state = StateManager()
    time_values = np.linspace(0.0, 10.0, 6001)
    state.add_event_data("large", EventList(time=time_values, gti=[[0.0, 10.0]], dt=0))
    monkeypatch.setattr(gti_module, "MAX_EXACT_OUTPUT", 3)

    result = GTIService(state).mask_preview("large", [[1.0, 9.0]])

    assert result["success"] is True
    assert result["data"]["mask_preview"]["shown"] == 3
    assert result["data"]["mask_preview"]["truncated"] is True
    assert len(result["data"]["plot"]["time"]) <= 5000
    json.dumps(result, allow_nan=False)


def test_mask_event_cap_prevents_mask_allocation(monkeypatch):
    state, _ = _state_with_events()
    monkeypatch.setattr(gti_module, "MAX_MASK_EVENTS", 3)

    result = GTIService(state).mask_preview("source", [[0.0, 1.0]])

    assert result["success"] is False
    assert "cap" in result["message"]


def test_mask_rejects_event_list_without_explicit_gti_instead_of_synthesizing():
    state = StateManager()
    source = EventList(time=[1.0, 2.0, 3.0], dt=0)
    state.add_event_data("missing-gti", source)

    preview = GTIService(state).mask_preview("missing-gti", [[1.0, 2.0]])
    saved = GTIService(state).save_masked("missing-gti", [[1.0, 2.0]], "must-not-exist")

    assert preview["success"] is False
    assert saved["success"] is False
    assert "no effective GTI" in preview["message"]
    assert "no effective GTI" in saved["message"]
    assert source._gti is None
    assert not state.has_event_data("must-not-exist")


def test_save_masked_preserves_source_and_owns_all_arrays():
    state, source = _state_with_events()
    source_time = source.time.copy()
    source_energy = source.energy.copy()
    source_pi = source.pi.copy()
    source_gti = source.gti.copy()

    service = GTIService(state)
    requested = [[1.0, 3.0], [7.0, 9.0]]
    preview = service.mask_preview("source", requested)
    result = service.save_masked("source", requested, "derived")
    derived = state.get_event_data("derived")

    assert result["success"] is True
    np.testing.assert_array_equal(source.time, source_time)
    np.testing.assert_array_equal(source.energy, source_energy)
    np.testing.assert_array_equal(source.pi, source_pi)
    np.testing.assert_array_equal(source.gti, source_gti)
    np.testing.assert_allclose(derived.gti, [[1.0, 3.0], [7.0, 9.0]])
    preview_time = np.asarray(preview["data"]["mask_preview"]["time"])
    preview_mask = np.asarray(preview["data"]["mask_preview"]["retained"])
    np.testing.assert_allclose(derived.time, preview_time[preview_mask])
    assert not np.shares_memory(source.time, derived.time)
    assert not np.shares_memory(source.energy, derived.energy)
    assert not np.shares_memory(source.pi, derived.pi)
    assert not np.shares_memory(source.gti, derived.gti)


def test_save_masked_guards_empty_gti_case():
    state, _ = _state_with_events()

    result = GTIService(state).save_masked("source", [[20.0, 30.0]], "empty")
    derived = state.get_event_data("empty")

    assert result["success"] is True
    assert len(derived.time) == 0
    assert derived.gti.shape == (0, 2)
    assert result["data"]["retained_exposure_s"] == 0.0


def test_save_masked_rejects_duplicate_and_invalid_destination():
    state, _ = _state_with_events()
    state.add_event_data("duplicate", EventList(time=[1.0], gti=[[0.0, 2.0]]))
    service = GTIService(state)

    duplicate = service.save_masked("source", [[0.0, 1.0]], "duplicate")
    invalid = service.save_masked("source", [[0.0, 1.0]], " bad")

    assert duplicate["success"] is False
    assert "already exists" in duplicate["message"]
    assert invalid["success"] is False
    assert "whitespace" in invalid["message"]


def test_concurrent_save_is_atomic(monkeypatch):
    state, _ = _state_with_events()
    original_has_event_data = state.has_event_data
    start_barrier = threading.Barrier(2)

    def ignore_preflight_for_destination(name):
        if name == "race":
            start_barrier.wait(timeout=5)
            return False
        return original_has_event_data(name)

    monkeypatch.setattr(state, "has_event_data", ignore_preflight_for_destination)
    services = [GTIService(state), GTIService(state)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                service.save_masked,
                "source",
                [[1.0, 3.0]],
                "race",
            )
            for service in services
        ]
    results = [future.result() for future in futures]

    assert sorted(result["success"] for result in results) == [False, True]
    assert state.list_event_names().count("race") == 1
    assert any(
        "concurrently" in result["message"]
        for result in results
        if not result["success"]
    )


def test_fixed_segments_match_direct_stingray():
    gtis = np.asarray([[0.0, 5.0], [7.0, 12.0]])
    starts, stops = time_intervals_from_gtis(gtis, 2.0)

    result = GTIService(StateManager()).fixed_segments(gtis, 2.0)

    assert result["success"] is True
    np.testing.assert_allclose(_result_gtis(result), np.column_stack((starts, stops)))
    assert result["data"]["unused_exposure_s"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("gtis", "segment_size", "expected_count"),
    [
        ([[0.0, 37.0]], 3.7, 10),
        ([[50_000.0, 50_001.8]], 0.3, 6),
        ([[0.0, 30.0]], 0.3, 100),
        ([[50_000.0, 50_000.1]], 0.1, 1),
        ([[50_000.0, 50_000.2]], 0.1, 2),
        ([[100_000_000.0, 100_000_000.3]], 0.3, 1),
        ([[1_000_000_000_000.0, 1_000_000_000_000.1]], 0.1, 1),
    ],
)
def test_fixed_segments_normalize_only_ulp_scale_endpoint_drift(
    gtis, segment_size, expected_count
):
    result = GTIService(StateManager()).fixed_segments(gtis, segment_size)

    assert result["success"] is True, result
    assert result["data"]["interval_count"] == expected_count
    intervals = _result_gtis(result)
    assert intervals[0, 0] == gtis[0][0]
    assert intervals[-1, 1] == gtis[0][1]
    assert np.all(intervals[1:, 0] == intervals[:-1, 1])
    assert result["data"]["segmented_exposure_s"] == pytest.approx(
        result["data"]["source_exposure_s"]
    )
    assert result["data"]["unused_exposure_s"] == pytest.approx(0.0)


@pytest.mark.parametrize("segment_size", [0.0, -1.0, np.nan, np.inf])
def test_fixed_segments_reject_invalid_size(segment_size):
    result = GTIService(StateManager()).fixed_segments([[0.0, 5.0]], segment_size)

    assert result["success"] is False


def test_fixed_segments_rejects_no_fit_and_allocation_cap(monkeypatch):
    service = GTIService(StateManager())
    no_fit = service.fixed_segments([[0.0, 1.0]], 2.0)
    monkeypatch.setattr(gti_module, "MAX_GTI_ROWS", 2)
    over_cap = service.fixed_segments([[0.0, 10.0]], 1.0)

    assert no_fit["success"] is False
    assert "No GTI" in no_fit["message"]
    assert over_cap["success"] is False
    assert "cap" in over_cap["message"]


@pytest.mark.parametrize("segment_size", [1.000001, 1.000005])
def test_fixed_segments_reject_upstream_epsilon_escape(segment_size):
    result = GTIService(StateManager()).fixed_segments([[0.0, 1.0]], segment_size)

    assert result["success"] is False
    assert "fully contains" in result["message"]


def test_fixed_segments_omit_partial_remainder_that_upstream_extends_past_gti():
    result = GTIService(StateManager()).fixed_segments([[0.0, 1.0]], 0.333334)

    assert result["success"] is True
    intervals = _result_gtis(result)
    np.testing.assert_allclose(intervals, [[0.0, 0.333334], [0.333334, 0.666668]])
    assert np.all(intervals[:, 0] >= 0.0)
    assert np.all(intervals[:, 1] <= 1.0)
    assert result["data"]["segmented_exposure_s"] <= result["data"]["source_exposure_s"]
    assert result["data"]["unused_exposure_s"] == pytest.approx(0.333332)
    assert any(
        "exceeded a source GTI boundary" in warning
        for warning in result["data"]["warnings"]
    )


@pytest.mark.parametrize(
    ("gtis", "segment_size"),
    [
        ([[1_000_000_000_000_000.0, 1_000_000_000_000_001.0]], 0.1),
        ([[100_000_000_000_000.0, 100_000_000_000_001.0]], 0.01),
    ],
)
def test_fixed_segments_reject_unrepresentable_absolute_timestamp_step(
    gtis, segment_size
):
    result = GTIService(StateManager()).fixed_segments(gtis, segment_size)

    assert result["success"] is False
    assert result["error"] is None
    assert "binary64 timestamp resolution" in result["message"]
    assert "relative-second GTIs" in result["message"]


def test_pathologically_small_segment_requests_fail_before_upstream(monkeypatch):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Stingray must not run after the cap fails")

    service = GTIService(StateManager())
    monkeypatch.setattr(gti_module, "time_intervals_from_gtis", must_not_run)
    fixed = service.fixed_segments([[0.0, 1.0]], np.nextafter(0.0, 1.0))
    monkeypatch.setattr(gti_module, "split_gtis_by_exposure", must_not_run)
    split = service.split_by_exposure([[0.0, 1.0]], np.nextafter(0.0, 1.0))

    assert fixed["success"] is False
    assert "cap" in fixed["message"]
    assert split["success"] is False
    assert "cap" in split["message"]


def test_split_by_exposure_matches_direct_stingray_and_preserves_exposure():
    gtis = np.asarray([[0.0, 30.0], [40.0, 70.0], [90.0, 120.0], [130.0, 160.0]])
    expected = split_gtis_by_exposure(gtis, 60.0)

    result = GTIService(StateManager()).split_by_exposure(gtis, 60.0)

    assert result["success"] is True
    assert result["data"]["chunk_count"] == len(expected)
    for result_chunk, expected_chunk in zip(result["data"]["chunks"], expected):
        rows = np.asarray(
            [[row["start"], row["stop"]] for row in result_chunk["intervals"]]
        )
        np.testing.assert_allclose(rows, expected_chunk)
    assert result["data"]["source_exposure_s"] == pytest.approx(
        result["data"]["output_exposure_s"]
    )
    assert "approximate" in result["data"]["warnings"][0]


@pytest.mark.parametrize(
    ("gtis", "threshold"),
    [
        ([[0.0, 15.0]], 0.5),
        ([[0.0, 15.0]], 10.0),
        ([[0.0, 5.0], [6.0, 10.0]], 2.0),
        ([[0.0, 5.0], [6.0, 10.0]], 10.0),
    ],
)
def test_split_by_exposure_treats_threshold_without_qualifying_gap_as_noop(
    gtis, threshold
):
    ordinary = GTIService(StateManager()).split_by_exposure(gtis, 1.0)

    result = GTIService(StateManager()).split_by_exposure(
        gtis,
        1.0,
        new_interval_if_gti_sep=threshold,
    )

    assert ordinary["success"] is True, ordinary
    assert result["success"] is True, result
    assert result["data"]["chunk_count"] == ordinary["data"]["chunk_count"]
    assert result["data"]["chunks"] == ordinary["data"]["chunks"]


def test_split_by_exposure_preserves_qualifying_gap_threshold_behavior():
    gtis = np.asarray([[0.0, 5.0], [6.0, 10.0]])
    expected = split_gtis_by_exposure(
        gtis,
        1.0,
        new_interval_if_gti_sep=0.5,
    )

    result = GTIService(StateManager()).split_by_exposure(
        gtis,
        1.0,
        new_interval_if_gti_sep=0.5,
    )

    assert result["success"] is True, result
    assert result["data"]["chunk_count"] == len(expected)
    for result_chunk, expected_chunk in zip(result["data"]["chunks"], expected):
        rows = np.asarray(
            [[row["start"], row["stop"]] for row in result_chunk["intervals"]]
        )
        np.testing.assert_allclose(rows, expected_chunk)


@pytest.mark.parametrize(
    ("gtis", "exposure", "expected_chunks", "expected_rows"),
    [
        ([[50_000.0, 50_003.0], [50_003.6, 50_004.5]], 0.3, 13, 13),
        (
            [
                [100_000_000.0, 100_000_000.0 + 3 * 3.7],
                [100_000_000.0 + 5 * 3.7, 100_000_000.0 + 11 * 3.7],
            ],
            3.7,
            8,
            9,
        ),
    ],
)
def test_split_by_exposure_avoids_tiny_roundoff_rows_across_multiple_gtis(
    gtis, exposure, expected_chunks, expected_rows
):
    result = GTIService(StateManager()).split_by_exposure(gtis, exposure)

    assert result["success"] is True, result
    assert result["data"]["chunk_count"] == expected_chunks
    rows = [row for chunk in result["data"]["chunks"] for row in chunk["intervals"]]
    assert len(rows) == expected_rows
    assert all(row["stop"] > row["start"] for row in rows)
    assert result["data"]["source_exposure_s"] == pytest.approx(
        result["data"]["output_exposure_s"]
    )


@pytest.mark.parametrize(
    ("gtis", "exposure"),
    [
        ([[0.0, 0.3]], 0.1),
        ([[0.0, 0.6]], 0.1),
        ([[0.0, 11.1]], 3.7),
    ],
)
def test_split_by_exposure_preserves_direct_small_origin_grouping(gtis, exposure):
    expected = split_gtis_by_exposure(np.asarray(gtis), exposure)

    result = GTIService(StateManager()).split_by_exposure(gtis, exposure)

    assert result["success"] is True, result
    assert result["data"]["chunk_count"] == len(expected)
    for result_chunk, expected_chunk in zip(result["data"]["chunks"], expected):
        rows = np.asarray(
            [[row["start"], row["stop"]] for row in result_chunk["intervals"]]
        )
        np.testing.assert_allclose(rows, expected_chunk, rtol=0, atol=0)


@pytest.mark.parametrize(
    ("gtis", "exposure", "expected_chunks"),
    [
        ([[50_000.0, 50_001.8]], 0.3, 6),
        ([[100_000_000.0, 100_000_030.0]], 0.3, 100),
        ([[50_000.0, 50_000.3]], 0.1, 3),
        ([[1_000_000_000_000.0, 1_000_000_000_000.0 + 0.3]], 0.1, 3),
        ([[100_000_000.0, 100_000_000.0 + 22.2]], 3.7, 6),
    ],
)
def test_split_by_exposure_is_stable_at_large_absolute_epochs(
    gtis, exposure, expected_chunks
):
    result = GTIService(StateManager()).split_by_exposure(gtis, exposure)

    assert result["success"] is True, result
    assert result["data"]["chunk_count"] == expected_chunks
    assert result["data"]["source_exposure_s"] == pytest.approx(
        result["data"]["output_exposure_s"], rel=1e-12, abs=1e-12
    )
    intervals = np.asarray(
        [
            [row["start"], row["stop"]]
            for chunk in result["data"]["chunks"]
            for row in chunk["intervals"]
        ]
    )
    assert intervals[0, 0] == gtis[0][0]
    assert intervals[-1, 1] == gtis[0][1]
    assert np.all(intervals[:, 1] > intervals[:, 0])


@pytest.mark.parametrize("exposure", [0.01, 0.001])
def test_split_by_exposure_rejects_collapsing_absolute_timestamp_step(exposure):
    result = GTIService(StateManager()).split_by_exposure(
        [[1_000_000_000_000_000.0, 1_000_000_000_000_001.0]],
        exposure,
    )

    assert result["success"] is False
    assert result["error"] is None
    assert "binary64 timestamp resolution" in result["message"]
    assert "relative-second GTIs" in result["message"]


@pytest.mark.parametrize(
    "gtis",
    [
        [[100_000_000.0, 100_000_000.0 + 1.0000000149011612]],
        [[1_000_000_000_000.0, 1_000_000_000_000.0 + 1.0001220703125]],
        [[-1_000_000_000_000.0, -1_000_000_000_000.0 + 1.0001220703125]],
    ],
)
def test_split_by_exposure_preserves_representable_one_ulp_remainder(gtis):
    result = GTIService(StateManager()).split_by_exposure(gtis, 0.1)

    assert result["success"] is True, result
    assert result["data"]["chunk_count"] == 10
    assert result["data"]["interval_count"] == 11
    assert result["data"]["output_exposure_s"] == result["data"]["source_exposure_s"]
    final_row = result["data"]["chunks"][-1]["intervals"][-1]
    assert final_row["stop"] > final_row["start"]


@pytest.mark.parametrize(
    ("gtis", "exposure", "separation"),
    [([], 1.0, None), ([[0.0, 1.0]], 0.0, None), ([[0.0, 1.0]], 1.0, 0.0)],
)
def test_split_by_exposure_rejects_empty_and_invalid_parameters(
    gtis, exposure, separation
):
    result = GTIService(StateManager()).split_by_exposure(
        gtis, exposure, new_interval_if_gti_sep=separation
    )

    assert result["success"] is False


@pytest.mark.parametrize(
    ("gtis", "message_fragment"),
    [
        ([[-1e308, 1e308]], "interval 1"),
        ([[-1e308, -1e307], [1e307, 1e308]], "Total GTI exposure"),
    ],
)
def test_split_by_exposure_rejects_unrepresentable_finite_exposure_before_upstream(
    monkeypatch, gtis, message_fragment
):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Stingray must not run after derived exposure validation")

    monkeypatch.setattr(gti_module, "split_gtis_by_exposure", must_not_run)

    result = GTIService(StateManager()).split_by_exposure(gtis, 1e308)

    assert result["success"] is False
    assert result["error"] is None
    assert message_fragment in result["message"]
    assert "finite seconds" in result["message"]


def test_validation_rejects_unrepresentable_finite_interval_arithmetic():
    result = GTIService(StateManager()).validate([[-1e308, 1e308]])

    assert result["success"] is False
    assert result["error"] is None
    assert "interval 1" in result["message"]
    assert "finite seconds" in result["message"]


@pytest.mark.parametrize("times", [[5.0], [0.1, 9.9], [1.0, 2.0, 9.0]])
def test_mask_without_dt_treats_events_as_point_timestamps(state_manager, times):
    source = EventList(time=np.asarray(times), gti=np.asarray([[0.0, 10.0]]))
    source.dt = None
    state_manager.add_event_data("point-events", source)

    result = GTIService(state_manager).mask_preview("point-events", [[0.0, 10.0]])

    assert result["success"], result
    assert result["data"]["retained_event_count"] == len(times)
    assert result["data"]["rejected_event_count"] == 0
    assert any("point timestamps" in warning for warning in result["data"]["warnings"])


def _route_app() -> FastAPI:
    app = FastAPI()
    app.include_router(gti_routes.router, prefix="/api/utilities/gti")
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    return app


@pytest.mark.asyncio
async def test_routes_return_strict_json_and_reject_nonfinite_payload():
    app = _route_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/utilities/gti/validate",
            json={"gtis": [[0.0, 1.0]], "time_reference": "relative_seconds"},
        )
        nonfinite = await client.post(
            "/api/utilities/gti/validate",
            json={"gtis": [[0.0, "NaN"]]},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    json.dumps(response.json(), allow_nan=False)
    assert nonfinite.status_code == 422


@pytest.mark.asyncio
async def test_inspect_route_offloads_blocking_service(monkeypatch):
    def slow_inspect(self, event_list_name):
        del self, event_list_name
        time.sleep(0.6)
        return {"success": True, "data": None, "message": "ok", "error": None}

    monkeypatch.setattr(gti_module.GTIService, "inspect", slow_inspect)
    app = _route_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        slow_task = asyncio.create_task(
            client.post(
                "/api/utilities/gti/inspect", json={"event_list_name": "source"}
            )
        )
        start = time.monotonic()
        await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        elapsed = time.monotonic() - start
        response = await slow_task

    assert response.status_code == 200
    assert elapsed < 0.4, f"event loop was blocked for {elapsed:.2f}s"


def test_every_route_uses_asyncio_to_thread():
    route_functions = [
        gti_routes.inspect,
        gti_routes.validate,
        gti_routes.set_operation,
        gti_routes.bad_time_intervals,
        gti_routes.mask_preview,
        gti_routes.mask_save,
        gti_routes.fixed_segments,
        gti_routes.exposure_segments,
    ]

    assert all(
        "asyncio.to_thread" in inspect.getsource(route) for route in route_functions
    )
