"""Scientific GTI inspection, set operations, masking, and segmentation.

The service deliberately validates GTIs before calling Stingray.  In
particular, it never sorts or merges renderer input merely to make an invalid
array acceptable: interval-specific errors are returned to the user instead.
"""

# Service boundaries intentionally translate unexpected scientific-library
# exceptions through the application's standardized ErrorHandler envelope.
# ruff: noqa: BLE001

from __future__ import annotations

import math
from collections.abc import Mapping, Sized
from decimal import Decimal, InvalidOperation
from itertools import islice
from typing import Any

import numpy as np
from stingray.gti import (
    append_gtis,
    check_gtis,
    check_separate,
    create_gti_mask,
    cross_two_gtis,
    find_large_bad_time_intervals,
    get_btis,
    merge_gtis,
    split_gtis_by_exposure,
    time_intervals_from_gtis,
)

from .analysis_helpers import collect_warnings
from .base_service import BaseService
from .utility_helpers import (
    MAX_EXACT_OUTPUT,
    MAX_EXPORT_ROWS,
    MAX_GTI_ROWS,
    MAX_STATE_SNAPSHOT_BYTES,
    MAX_STATE_SNAPSHOT_CELLS,
    bounded_plot_preview,
    finite_or_none,
    json_safe,
    operation_provenance,
    validate_derived_name,
)

GTI_TIME_REFERENCES = {"absolute_mission_time", "relative_seconds"}
# A boolean mask is comparatively small, but filtering an EventList also copies
# every event-aligned array.  Reuse the shared two-million-row safety ceiling.
MAX_MASK_EVENTS = MAX_EXPORT_ROWS


def _strict_finite_scalar(value: Any, label: str) -> tuple[float | None, str | None]:
    """Parse one renderer scalar without accepting booleans or numeric text."""
    if isinstance(value, (bool, np.bool_, str, bytes, bytearray, memoryview, Mapping)):
        return None, f"{label} must be a finite number"
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None, f"{label} must be a finite number"
    if not math.isfinite(result):
        return None, f"{label} must be finite"
    return result, None


def _validate_time_reference(time_reference: str) -> str | None:
    if time_reference not in GTI_TIME_REFERENCES:
        allowed = ", ".join(sorted(GTI_TIME_REFERENCES))
        return f"time_reference must be one of: {allowed}"
    return None


def _validate_gti_array(
    gtis: Any,
    *,
    label: str = "GTIs",
    allow_empty: bool = False,
    max_rows: int = MAX_GTI_ROWS,
) -> tuple[np.ndarray | None, str | None]:
    """Return a strict, ordered ``Nx2`` GTI array or a row-specific error."""
    if gtis is None:
        return None, f"{label} are missing"
    if isinstance(gtis, (bool, np.bool_, str, bytes, bytearray, memoryview, Mapping)):
        return None, f"{label} must be an array of [start, stop] rows"

    rows: Any
    row_count_is_lower_bound = False
    if type(gtis) is np.ndarray:
        if gtis.ndim == 0:
            return None, f"{label} must be an array of [start, stop] rows"
        row_count = int(gtis.shape[0])
        rows = gtis
    elif type(gtis) in (list, tuple):
        row_count = len(gtis)
        rows = gtis
    else:
        shape = getattr(gtis, "shape", None)
        if shape is not None:
            try:
                dimensions = tuple(shape)
            except TypeError:
                dimensions = ()
            if not dimensions:
                return None, f"{label} must be an array of [start, stop] rows"
            if isinstance(dimensions[0], (int, np.integer)):
                hinted_rows = int(dimensions[0])
                if hinted_rows > max_rows:
                    return None, (
                        f"{label} contain {hinted_rows:,} rows; the cap is {max_rows:,}"
                    )

        if isinstance(gtis, Sized):
            try:
                hinted_rows = len(gtis)
            except (TypeError, ValueError, OverflowError):
                hinted_rows = None
            if hinted_rows is not None and hinted_rows > max_rows:
                return None, (
                    f"{label} contain {hinted_rows:,} rows; the cap is {max_rows:,}"
                )

        try:
            rows = list(islice(iter(gtis), max_rows + 1))
        except (TypeError, ValueError):
            return None, f"{label} must be an array of [start, stop] rows"
        row_count = len(rows)
        row_count_is_lower_bound = row_count > max_rows

    if row_count > max_rows:
        qualifier = "at least " if row_count_is_lower_bound else ""
        return None, (
            f"{label} contain {qualifier}{row_count:,} rows; the cap is {max_rows:,}"
        )
    if row_count == 0:
        if allow_empty:
            return np.empty((0, 2), dtype=np.longdouble), None
        return None, f"{label} must contain at least one [start, stop] interval"

    parsed = np.empty((row_count, 2), dtype=np.longdouble)
    previous_start: np.longdouble | None = None
    previous_stop: np.longdouble | None = None

    for index, row in enumerate(rows):
        row_number = index + 1
        if isinstance(
            row, (bool, np.bool_, str, bytes, bytearray, memoryview, Mapping)
        ):
            return None, f"{label} interval {row_number} must be a [start, stop] row"

        values: Any
        value_count_is_lower_bound = False
        if type(row) is np.ndarray:
            if row.ndim != 1:
                return None, (
                    f"{label} interval {row_number} must be a [start, stop] row"
                )
            value_count = int(row.size)
            values = row
        elif type(row) in (list, tuple):
            value_count = len(row)
            values = row
        else:
            shape = getattr(row, "shape", None)
            if shape is not None:
                try:
                    dimensions = tuple(shape)
                except TypeError:
                    dimensions = ()
                if len(dimensions) != 1:
                    return None, (
                        f"{label} interval {row_number} must be a [start, stop] row"
                    )
                if (
                    isinstance(dimensions[0], (int, np.integer))
                    and int(dimensions[0]) != 2
                ):
                    return None, (
                        f"{label} interval {row_number} has {int(dimensions[0])} "
                        "value(s); exactly [start, stop] is required"
                    )

            if isinstance(row, Sized):
                try:
                    hinted_values = len(row)
                except (TypeError, ValueError, OverflowError):
                    hinted_values = None
                if hinted_values is not None and hinted_values != 2:
                    return None, (
                        f"{label} interval {row_number} has {hinted_values} value(s); "
                        "exactly [start, stop] is required"
                    )

            try:
                values = list(islice(iter(row), 3))
            except (TypeError, ValueError):
                return None, (
                    f"{label} interval {row_number} must be a [start, stop] row"
                )
            value_count = len(values)
            value_count_is_lower_bound = value_count > 2

        if value_count != 2:
            qualifier = "at least " if value_count_is_lower_bound else ""
            return None, (
                f"{label} interval {row_number} has {qualifier}{value_count} value(s); "
                "exactly [start, stop] is required"
            )

        start, start_error = _strict_finite_scalar(
            values[0], f"{label} interval {row_number} start"
        )
        if start_error:
            return None, start_error
        stop, stop_error = _strict_finite_scalar(
            values[1], f"{label} interval {row_number} stop"
        )
        if stop_error:
            return None, stop_error
        assert start is not None and stop is not None

        if stop <= start:
            return None, (
                f"{label} interval {row_number} must have positive length: "
                f"stop ({stop}) must be greater than start ({start})"
            )
        with np.errstate(over="ignore", invalid="ignore"):
            duration = stop - start
        if not np.isfinite(duration):
            return None, (
                f"{label} interval {row_number} has a duration that cannot be "
                "represented as finite seconds; use a narrower time range"
            )
        if previous_start is not None and start < previous_start:
            return None, (
                f"{label} interval {row_number} starts at {start}, before interval "
                f"{row_number - 1} starts at {float(previous_start)}; preserve time order"
            )
        if previous_stop is not None and start < previous_stop:
            return None, (
                f"{label} interval {row_number} starts at {start} and overlaps interval "
                f"{row_number - 1}, which stops at {float(previous_stop)}"
            )

        parsed[index] = (start, stop)
        previous_start = parsed[index, 0]
        previous_stop = parsed[index, 1]

    with np.errstate(over="ignore", invalid="ignore"):
        lengths = parsed[:, 1] - parsed[:, 0]
        exposure = np.sum(lengths, dtype=np.longdouble)
        span = parsed[-1, 1] - parsed[0, 0]
        separations = parsed[1:, 0] - parsed[:-1, 1]
    if not np.isfinite(exposure):
        return None, (
            f"Total {label.removesuffix('s')} exposure cannot be represented as finite "
            "seconds; use fewer intervals or a narrower time range"
        )
    if not np.isfinite(span):
        return None, (
            f"Overall {label.removesuffix('s')} span cannot be represented as finite "
            "seconds; use a narrower time range"
        )
    bad_separation = np.flatnonzero(~np.isfinite(separations))
    if bad_separation.size:
        interval_number = int(bad_separation[0]) + 2
        return None, (
            f"{label} separation before interval {interval_number} cannot be represented "
            "as finite seconds; use a narrower time range"
        )

    # Keep Stingray itself as the final scientific validator after the stricter
    # application checks (Stingray permits zero-duration intervals).
    try:
        check_gtis(parsed)
    except (
        TypeError,
        ValueError,
    ) as exc:  # pragma: no cover - defensive upstream guard
        return None, f"{label} failed Stingray validation: {exc}"
    return parsed, None


def _normalise_upstream_gtis(value: Any, *, label: str) -> np.ndarray:
    """Normalize only Stingray's inconsistent empty return shapes to ``(0, 2)``."""
    if value is None:
        return np.empty((0, 2), dtype=np.longdouble)
    result = np.asanyarray(value, dtype=np.longdouble)
    if result.size == 0:
        return np.empty((0, 2), dtype=np.longdouble)
    if result.ndim != 2 or result.shape[1] != 2:
        raise RuntimeError(
            f"Stingray returned malformed {label} with shape {result.shape}"
        )
    if len(result) > MAX_GTI_ROWS:
        raise RuntimeError(
            f"Stingray returned {len(result):,} {label} rows; the cap is {MAX_GTI_ROWS:,}"
        )
    return result


def _stored_event_list_gti(event_list: Any) -> Any:
    """Return only an explicitly stored EventList GTI.

    In Stingray 2.2.10, reading the public ``EventList.gti`` property lazily
    synthesizes ``[time[0], time[-1]]`` when event times exist but no GTI was
    supplied.  Utilities inspection and masking must distinguish that missing
    metadata from an explicit interval, so this boundary deliberately reads
    the backing value without invoking the synthesizing property.
    """
    return getattr(event_list, "_gti", None)


def _float64_ulp_tolerance(*values: Any, factor: float = 4.0) -> np.longdouble:
    """Return a small tolerance for arithmetic performed from JSON floats.

    Renderer numbers and Stingray's scalar parameters enter this boundary as
    binary64 values even though GTI arithmetic is promoted to ``longdouble``.
    Comparing an upstream endpoint with its source boundary therefore needs a
    few binary64 ULPs, not Stingray's much larger absolute epsilon.
    """
    largest_ulp = 0.0
    for value in values:
        numeric = abs(float(value))
        if not math.isfinite(numeric):
            continue
        if numeric == 0.0:
            ulp = np.nextafter(0.0, 1.0)
        else:
            next_value = np.nextafter(numeric, math.inf)
            if math.isfinite(float(next_value)):
                ulp = float(next_value - numeric)
            else:
                ulp = float(numeric - np.nextafter(numeric, 0.0))
        largest_ulp = max(largest_ulp, ulp)
    return np.longdouble(largest_ulp) * factor


def _step_resolution_error(
    source_gtis: np.ndarray,
    step: float,
    label: str,
) -> str | None:
    """Reject output steps that collapse when serialized as absolute floats."""
    timestamp_resolution = _float64_ulp_tolerance(*source_gtis.reshape(-1), factor=1.0)
    if np.longdouble(step) >= timestamp_resolution:
        return None
    return (
        f"{label} ({step:.12g} s) is smaller than the binary64 timestamp "
        f"resolution ({float(timestamp_resolution):.12g} s) at the supplied epoch; "
        "use a larger value or subtract a common epoch and provide relative-second GTIs"
    )


def _first_collapsed_binary64_interval(gtis: np.ndarray) -> int | None:
    """Return the one-based row whose JSON float endpoints would collapse."""
    serialized = np.asarray(gtis, dtype=float)
    collapsed = np.flatnonzero(serialized[:, 1] <= serialized[:, 0])
    return int(collapsed[0]) + 1 if collapsed.size else None


def _relative_gtis_for_step(
    source_gtis: np.ndarray,
    step: float,
    *,
    allow_upward_snap: bool,
) -> tuple[np.longdouble, np.ndarray]:
    """Translate GTIs and remove only epoch-resolution endpoint residue.

    Subtracting two binary64 mission timestamps can make a duration differ
    from an integer number of steps by less than either absolute endpoint's
    ULP. Fixed-window generation may snap in either direction because results
    are checked against the original GTIs after translation. Exposure
    splitting snaps downward only: an upward product can change Stingray's
    otherwise-correct small-origin chunk grouping.
    """
    origin = source_gtis[0, 0]
    relative_gtis = source_gtis - origin
    step_value = np.longdouble(step)

    for index, (source_start, source_stop) in enumerate(source_gtis):
        relative_length = relative_gtis[index, 1] - relative_gtis[index, 0]
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            quotient = relative_length / step_value
        if (
            not np.isfinite(quotient)
            or quotient > MAX_GTI_ROWS + 1
            or quotient < np.longdouble(0.5)
        ):
            continue
        nearest_count = round(float(quotient))
        if nearest_count <= 0:
            continue
        nearest_length = np.longdouble(nearest_count) * step_value
        # At most half an endpoint ULP can be attributed to round-to-nearest
        # subtraction residue. One or more full ULPs are representable source
        # exposure and must never be quantized away.
        tolerance = _float64_ulp_tolerance(
            source_start,
            source_stop,
            factor=0.5,
        )
        if abs(relative_length - nearest_length) <= tolerance:
            snapped_length = nearest_length
            if not allow_upward_snap:
                # Repeated binary multiplication can land above Stingray's
                # favorable chunk edge (for example, 3 * 0.1). Form the
                # human-facing decimal product, round it once to binary64,
                # and never enlarge the supplied relative GTI.
                try:
                    exact_decimal_length = Decimal(str(step)) * nearest_count
                    decimal_length = float(exact_decimal_length)
                except (InvalidOperation, OverflowError, ValueError):
                    continue
                if not math.isfinite(decimal_length):
                    continue
                if Decimal.from_float(decimal_length) > exact_decimal_length:
                    decimal_length = float(np.nextafter(decimal_length, -math.inf))
                snapped_length = np.longdouble(decimal_length)
                if snapped_length <= 0 or snapped_length > relative_length:
                    continue
            snapped_stop = relative_gtis[index, 0] + snapped_length
            if (
                not allow_upward_snap
                and snapped_stop - relative_gtis[index, 0] > snapped_length
            ):
                snapped_stop = np.nextafter(snapped_stop, -math.inf)
            relative_gtis[index, 1] = snapped_stop

    return origin, relative_gtis


def _contained_fixed_segments(
    starts: Any,
    stops: Any,
    source_gtis: np.ndarray,
) -> tuple[np.ndarray, int]:
    """Keep only upstream fixed segments fully contained in one source GTI.

    ``time_intervals_from_gtis`` uses an absolute 1e-5 second epsilon.  That
    tolerance can emit a segment whose stop is later than its source GTI.  We
    retain the public helper's valid output while enforcing the scientific
    containment invariant at the application boundary.
    """
    result = _normalise_upstream_gtis(
        np.column_stack((starts, stops)), label="fixed-duration segments"
    )
    contained: list[np.ndarray] = []
    omitted = 0
    source_index = 0
    previous_source_index: int | None = None

    for segment_index, segment in enumerate(result, start=1):
        candidate = np.asarray(segment, dtype=np.longdouble).copy()
        start, stop = candidate
        if not np.isfinite(start) or not np.isfinite(stop) or stop <= start:
            raise RuntimeError(
                "Stingray returned an invalid fixed-duration segment at "
                f"index {segment_index}"
            )

        while source_index < len(source_gtis) and start >= source_gtis[source_index, 1]:
            source_index += 1
        if source_index >= len(source_gtis):
            omitted += 1
            continue

        source_start, source_stop = source_gtis[source_index]
        if start < source_start:
            tolerance = _float64_ulp_tolerance(start, source_start)
            if source_start - start > tolerance:
                raise RuntimeError(
                    "Stingray returned a fixed-duration segment before its source GTI "
                    f"at index {segment_index}"
                )
            candidate[0] = source_start
        if stop > source_stop:
            tolerance = _float64_ulp_tolerance(stop, source_stop)
            if stop - source_stop > tolerance:
                omitted += 1
                continue
            candidate[1] = source_stop

        # np.arange and ``starts + segment_size`` can round the same internal
        # boundary in opposite directions.  Snap only adjacent endpoints that
        # differ by a few ULPs; material gaps or overlaps remain untouched.
        if contained and previous_source_index == source_index:
            previous_stop = contained[-1][1]
            tolerance = _float64_ulp_tolerance(candidate[0], previous_stop)
            if abs(candidate[0] - previous_stop) <= tolerance:
                candidate[0] = previous_stop

        if candidate[1] <= candidate[0]:
            raise RuntimeError(
                "Stingray returned an invalid fixed-duration segment after "
                f"endpoint normalization at index {segment_index}"
            )
        contained.append(candidate)
        previous_source_index = source_index

    if not contained:
        return np.empty((0, 2), dtype=np.longdouble), omitted
    return np.asarray(contained, dtype=np.longdouble), omitted


def _interval_payload(gtis: np.ndarray) -> dict[str, Any]:
    """Create exact interval rows, summary statistics, and a bounded plot trace."""
    if len(gtis) == 0:
        return {
            "intervals": [],
            "interval_count": 0,
            "lengths_s": [],
            "separations_s": [],
            "total_exposure_s": 0.0,
            "overall_time_span_s": 0.0,
            "duty_cycle": None,
            "plot": {
                "starts": [],
                "stops": [],
                "interval_indices": [],
                "stride": 1,
                "source_points": 0,
            },
        }

    starts = gtis[:, 0]
    stops = gtis[:, 1]
    lengths = stops - starts
    separations = starts[1:] - stops[:-1]
    span = stops[-1] - starts[0]
    exposure = np.sum(lengths, dtype=np.longdouble)
    plot = bounded_plot_preview(starts, stops, np.arange(1, len(gtis) + 1))
    return {
        "intervals": [
            {
                "index": index + 1,
                "start": float(start),
                "stop": float(stop),
                "length_s": float(stop - start),
            }
            for index, (start, stop) in enumerate(gtis)
        ],
        "interval_count": len(gtis),
        "lengths_s": lengths.astype(float).tolist(),
        "separations_s": separations.astype(float).tolist(),
        "total_exposure_s": float(exposure),
        "overall_time_span_s": float(span),
        "duty_cycle": float(exposure / span) if span > 0 else None,
        "plot": {
            "starts": plot["arrays"][0],
            "stops": plot["arrays"][1],
            "interval_indices": plot["arrays"][2],
            "stride": plot["stride"],
            "source_points": plot["source_points"],
        },
    }


def _safe_data(data: dict[str, Any], warning_messages: list[str]) -> dict[str, Any]:
    safe = json_safe(data, warning_messages)
    safe["warnings"] = list(dict.fromkeys(warning_messages))
    return safe


class GTIService(BaseService):
    """Service implementing the Utilities GTI workbench."""

    def inspect(self, event_list_name: str) -> dict[str, Any]:
        """Inspect the effective GTIs of a detached loaded EventList snapshot."""
        try:
            event_list = self.state.copy_event_data(
                event_list_name,
                max_events=MAX_MASK_EVENTS,
                max_cells=MAX_STATE_SNAPSHOT_CELLS,
                max_bytes=MAX_STATE_SNAPSHOT_BYTES,
            )
            if event_list is None:
                return self.create_result(
                    success=False,
                    message=f"EventList '{event_list_name}' not found",
                    error=None,
                )

            warning_messages: list[str] = []
            effective_gti = _stored_event_list_gti(event_list)
            if effective_gti is None:
                gtis = np.empty((0, 2), dtype=np.longdouble)
                gti_status = "missing"
                warning_messages.append(
                    "This EventList has no effective GTI; exposure and duty cycle are unavailable."
                )
            else:
                gtis, validation_error = _validate_gti_array(
                    effective_gti,
                    label="Effective GTIs",
                    allow_empty=True,
                )
                if validation_error:
                    return self.create_result(
                        success=False,
                        message=f"Stored EventList GTIs are invalid: {validation_error}",
                        error=None,
                    )
                assert gtis is not None
                if len(gtis) == 0:
                    gti_status = "empty"
                    warning_messages.append(
                        "This EventList has an empty effective GTI and therefore zero good-time exposure."
                    )
                else:
                    gti_status = "available"

            event_time = getattr(event_list, "time", None)
            event_count = 0 if event_time is None else int(np.size(event_time))
            mjdref = finite_or_none(
                getattr(event_list, "mjdref", None), warning_messages, "mjdref"
            )
            data = {
                "event_list_name": event_list_name,
                "event_count": event_count,
                "gti_status": gti_status,
                "gti_origin": "effective_event_list_gti",
                "time_unit": "s",
                "time_reference": "absolute_mission_time",
                "mjdref": mjdref,
                **_interval_payload(gtis),
                "provenance": operation_provenance(
                    "gti.inspect",
                    input_source={"type": "event_list", "name": event_list_name},
                    parameters={},
                ),
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=(
                    f"Inspected {len(gtis)} effective GTI interval(s) "
                    f"for EventList '{event_list_name}'"
                ),
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(
                exc, "Inspecting EventList GTIs", event_list=event_list_name
            )

    def validate(
        self,
        gtis: Any,
        time_reference: str = "absolute_mission_time",
    ) -> dict[str, Any]:
        """Validate manually entered GTIs without sorting or merging them."""
        try:
            reference_error = _validate_time_reference(time_reference)
            if reference_error:
                return self.create_result(
                    success=False, message=reference_error, error=None
                )
            array, validation_error = _validate_gti_array(gtis)
            if validation_error:
                return self.create_result(
                    success=False, message=validation_error, error=None
                )
            assert array is not None
            warning_messages: list[str] = []
            data = {
                "valid": True,
                "time_unit": "s",
                "time_reference": time_reference,
                **_interval_payload(array),
                "provenance": operation_provenance(
                    "gti.validate",
                    input_source={"type": "manual_gtis"},
                    parameters={"time_reference": time_reference},
                ),
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=f"Validated {len(array)} GTI interval(s)",
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(exc, "Validating GTIs")

    def set_operation(
        self,
        left_gtis: Any,
        right_gtis: Any,
        operation: str,
        time_reference: str = "absolute_mission_time",
    ) -> dict[str, Any]:
        """Intersect, union, or append two independently valid GTI sets."""
        try:
            if operation not in {"intersection", "union", "append"}:
                return self.create_result(
                    success=False,
                    message="operation must be one of: intersection, union, append",
                    error=None,
                )
            reference_error = _validate_time_reference(time_reference)
            if reference_error:
                return self.create_result(
                    success=False, message=reference_error, error=None
                )
            left, left_error = _validate_gti_array(left_gtis, label="Left GTIs")
            if left_error:
                return self.create_result(success=False, message=left_error, error=None)
            right, right_error = _validate_gti_array(right_gtis, label="Right GTIs")
            if right_error:
                return self.create_result(
                    success=False, message=right_error, error=None
                )
            assert left is not None and right is not None

            maximum_output_rows = (
                len(left) + len(right) - 1
                if operation == "intersection"
                else len(left) + len(right)
            )
            if maximum_output_rows > MAX_GTI_ROWS:
                return self.create_result(
                    success=False,
                    message=(
                        f"The requested {operation} can produce up to "
                        f"{maximum_output_rows:,} rows; the cap is {MAX_GTI_ROWS:,}"
                    ),
                    error=None,
                )

            warning_messages: list[str] = []
            if operation == "intersection":
                result = cross_two_gtis(left, right)
                strategy = "exact shared good time"
            elif operation == "union":
                result = merge_gtis([left, right], "union")
                strategy = "union with overlapping and touching intervals coalesced"
            else:
                if not check_separate(left, right):
                    return self.create_result(
                        success=False,
                        message=(
                            "Append requires mutually exclusive GTI sets; use union when "
                            "the two sets overlap"
                        ),
                        error=None,
                    )
                result = append_gtis(left, right)
                strategy = (
                    "append mutually exclusive sets; touching boundaries are joined"
                )

            result_array = _normalise_upstream_gtis(result, label=f"{operation} GTIs")
            if operation == "intersection" and len(result_array) == 0:
                warning_messages.append(
                    "The GTI sets have no shared positive-duration good time."
                )
            if operation in {"union", "append"} and len(result_array) < len(left) + len(
                right
            ):
                warning_messages.append(
                    "Touching or overlapping boundaries were coalesced according to the selected strategy."
                )

            data = {
                "operation": operation,
                "merge_strategy": strategy,
                "time_unit": "s",
                "time_reference": time_reference,
                **_interval_payload(result_array),
                "provenance": operation_provenance(
                    f"gti.{operation}",
                    input_source={"type": "two_manual_gti_sets"},
                    parameters={
                        "operation": operation,
                        "time_reference": time_reference,
                        "left_interval_count": len(left),
                        "right_interval_count": len(right),
                    },
                ),
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=f"Computed GTI {operation}: {len(result_array)} interval(s)",
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(exc, f"Computing GTI {operation}")

    def bad_time_intervals(
        self,
        gtis: Any,
        start_time: Any,
        stop_time: Any,
        time_reference: str = "absolute_mission_time",
    ) -> dict[str, Any]:
        """Return the complement of GTIs inside an explicit observation range."""
        try:
            reference_error = _validate_time_reference(time_reference)
            if reference_error:
                return self.create_result(
                    success=False, message=reference_error, error=None
                )
            start, start_error = _strict_finite_scalar(start_time, "start_time")
            if start_error:
                return self.create_result(
                    success=False, message=start_error, error=None
                )
            stop, stop_error = _strict_finite_scalar(stop_time, "stop_time")
            if stop_error:
                return self.create_result(success=False, message=stop_error, error=None)
            assert start is not None and stop is not None
            if stop <= start:
                return self.create_result(
                    success=False,
                    message="stop_time must be greater than start_time",
                    error=None,
                )

            array, validation_error = _validate_gti_array(gtis, allow_empty=True)
            if validation_error:
                return self.create_result(
                    success=False, message=validation_error, error=None
                )
            assert array is not None
            if len(array) and array[0, 0] < start:
                return self.create_result(
                    success=False,
                    message=(
                        f"GTIs interval 1 starts at {float(array[0, 0])}, before "
                        f"the defined observation start {start}"
                    ),
                    error=None,
                )
            if len(array) and array[-1, 1] > stop:
                return self.create_result(
                    success=False,
                    message=(
                        f"GTIs interval {len(array)} stops at {float(array[-1, 1])}, "
                        f"after the defined observation stop {stop}"
                    ),
                    error=None,
                )

            possible_bti_rows = (
                1
                if len(array) == 0
                else (
                    len(array) - 1 + int(array[0, 0] > start) + int(array[-1, 1] < stop)
                )
            )
            if possible_bti_rows > MAX_GTI_ROWS:
                return self.create_result(
                    success=False,
                    message=(
                        "The requested complement can produce "
                        f"{possible_bti_rows:,} bad-time rows; the cap is "
                        f"{MAX_GTI_ROWS:,}"
                    ),
                    error=None,
                )

            raw_result = get_btis(array, start_time=start, stop_time=stop)
            result = _normalise_upstream_gtis(raw_result, label="bad-time intervals")
            warning_messages: list[str] = []
            if len(result):
                positive = result[:, 1] > result[:, 0]
                if not np.all(positive):
                    omitted = int(np.count_nonzero(~positive))
                    warning_messages.append(
                        f"Omitted {omitted} zero-duration boundary interval(s) returned "
                        "by Stingray for touching GTIs."
                    )
                    result = result[positive]

            data = {
                "time_unit": "s",
                "time_reference": time_reference,
                "observation_start": start,
                "observation_stop": stop,
                "good_exposure_s": float(np.sum(array[:, 1] - array[:, 0]))
                if len(array)
                else 0.0,
                "bad_exposure_s": float(np.sum(result[:, 1] - result[:, 0]))
                if len(result)
                else 0.0,
                **_interval_payload(result),
                "provenance": operation_provenance(
                    "gti.bad_time_intervals",
                    input_source={"type": "manual_gtis"},
                    parameters={
                        "start_time": start,
                        "stop_time": stop,
                        "time_reference": time_reference,
                    },
                ),
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=f"Generated {len(result)} bad-time interval(s)",
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(exc, "Generating bad-time intervals")

    def _prepare_mask(
        self, event_list_name: str, gtis: Any
    ) -> tuple[Any, np.ndarray | None, np.ndarray | None, list[str], str | None]:
        """Snapshot an EventList and compute a scientifically bounded GTI mask."""
        event_list = self.state.copy_event_data(
            event_list_name,
            max_events=MAX_MASK_EVENTS,
            max_cells=MAX_STATE_SNAPSHOT_CELLS,
            max_bytes=MAX_STATE_SNAPSHOT_BYTES,
        )
        if event_list is None:
            return None, None, None, [], f"EventList '{event_list_name}' not found"

        time = getattr(event_list, "time", None)
        if time is None or np.size(time) == 0:
            return (
                event_list,
                None,
                None,
                [],
                (f"EventList '{event_list_name}' contains no event times"),
            )
        time_array = np.asanyarray(time)
        if time_array.ndim != 1:
            return (
                event_list,
                None,
                None,
                [],
                "EventList time data must be one-dimensional",
            )
        if len(time_array) > MAX_MASK_EVENTS:
            return (
                event_list,
                None,
                None,
                [],
                (
                    f"EventList '{event_list_name}' contains {len(time_array):,} events; "
                    f"GTI masking is capped at {MAX_MASK_EVENTS:,} events"
                ),
            )
        if not np.all(np.isfinite(time_array)):
            bad_index = int(np.flatnonzero(~np.isfinite(time_array))[0])
            return (
                event_list,
                None,
                None,
                [],
                (f"EventList time[{bad_index}] must be finite before GTI masking"),
            )
        displaced = np.flatnonzero(np.diff(time_array) < 0)
        if displaced.size:
            row = int(displaced[0] + 2)
            return (
                event_list,
                None,
                None,
                [],
                (
                    f"EventList times are not ordered at event {row}; GTI masking requires "
                    "nondecreasing time"
                ),
            )

        requested, requested_error = _validate_gti_array(gtis, label="Requested GTIs")
        if requested_error:
            return event_list, None, None, [], requested_error
        assert requested is not None

        effective_value = _stored_event_list_gti(event_list)
        warning_messages: list[str] = []
        if effective_value is None:
            return (
                event_list,
                None,
                None,
                [],
                (
                    f"EventList '{event_list_name}' has no effective GTI to intersect "
                    "with the requested intervals"
                ),
            )
        effective, effective_error = _validate_gti_array(
            effective_value,
            label="Effective EventList GTIs",
            allow_empty=True,
        )
        if effective_error:
            return event_list, None, None, [], effective_error
        assert effective is not None

        possible_intersections = (
            len(effective) + len(requested) - 1 if len(effective) else 0
        )
        if possible_intersections > MAX_GTI_ROWS:
            return (
                event_list,
                None,
                None,
                [],
                (
                    "Intersecting requested and effective GTIs can produce up to "
                    f"{possible_intersections:,} rows; the cap is {MAX_GTI_ROWS:,}"
                ),
            )

        if len(effective) == 0:
            applied = np.empty((0, 2), dtype=np.longdouble)
            mask = np.zeros(len(time_array), dtype=bool)
            warning_messages.append(
                "The source EventList has zero effective good-time exposure; no events are retained."
            )
        else:
            applied = _normalise_upstream_gtis(
                cross_two_gtis(effective, requested),
                label="effective mask GTIs",
            )
            if len(applied) == 0:
                mask = np.zeros(len(time_array), dtype=bool)
                warning_messages.append(
                    "The requested GTIs do not intersect the source EventList's effective GTIs."
                )
            else:
                raw_dt = getattr(event_list, "dt", None)
                if raw_dt is None:
                    mask_dt = 0.0
                    warning_messages.append(
                        "The EventList has no time-bin width (dt); events were treated "
                        "as point timestamps when applying GTIs."
                    )
                else:
                    mask_dt, dt_error = _strict_finite_scalar(raw_dt, "EventList.dt")
                    if dt_error:
                        return event_list, None, None, warning_messages, dt_error
                    assert mask_dt is not None
                    if mask_dt < 0:
                        return (
                            event_list,
                            None,
                            None,
                            warning_messages,
                            "EventList.dt must be non-negative",
                        )
                with collect_warnings(warning_messages):
                    mask = np.asanyarray(
                        create_gti_mask(time_array, applied, dt=mask_dt),
                        dtype=bool,
                    )
                if mask.shape != time_array.shape:
                    raise RuntimeError(
                        "Stingray returned a GTI mask whose shape does not match EventList.time"
                    )

        requested_exposure = np.sum(requested[:, 1] - requested[:, 0])
        applied_exposure = (
            np.sum(applied[:, 1] - applied[:, 0]) if len(applied) else np.longdouble(0)
        )
        tolerance = np.finfo(float).eps * max(1.0, abs(float(requested_exposure))) * 16
        if float(requested_exposure - applied_exposure) > tolerance:
            warning_messages.append(
                "Requested intervals were clipped to the source EventList's effective GTIs; "
                "retained exposure reports the intersection."
            )
        if not np.any(mask):
            warning_messages.append("The GTI mask retains no events.")

        return event_list, applied, mask, warning_messages, None

    def mask_preview(self, event_list_name: str, gtis: Any) -> dict[str, Any]:
        """Preview a GTI filter without changing application state."""
        try:
            event_list, applied, mask, warning_messages, preparation_error = (
                self._prepare_mask(event_list_name, gtis)
            )
            if preparation_error:
                return self.create_result(
                    success=False, message=preparation_error, error=None
                )
            assert event_list is not None and applied is not None and mask is not None
            time = np.asanyarray(event_list.time)
            retained_count = int(np.count_nonzero(mask))
            exact_count = min(len(time), MAX_EXACT_OUTPUT)
            plot = bounded_plot_preview(time, mask.astype(np.int8))
            exposure = (
                float(np.sum(applied[:, 1] - applied[:, 0])) if len(applied) else 0.0
            )
            data = {
                "event_list_name": event_list_name,
                "source_event_count": len(time),
                "retained_event_count": retained_count,
                "rejected_event_count": int(len(time) - retained_count),
                "retained_exposure_s": exposure,
                "time_unit": "s",
                "time_reference": "absolute_mission_time",
                "applied_gtis": _interval_payload(applied),
                "mask_preview": {
                    "time": time[:exact_count].astype(float).tolist(),
                    "retained": mask[:exact_count].tolist(),
                    "shown": exact_count,
                    "total": len(time),
                    "truncated": exact_count < len(time),
                },
                "plot": {
                    "time": plot["arrays"][0],
                    "retained": plot["arrays"][1],
                    "stride": plot["stride"],
                    "source_points": plot["source_points"],
                },
                "provenance": operation_provenance(
                    "gti.mask_preview",
                    input_source={"type": "event_list", "name": event_list_name},
                    parameters={"requested_gtis": gtis},
                ),
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=(
                    f"GTI mask preview retains {retained_count:,} of {len(time):,} events"
                ),
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(
                exc, "Previewing a GTI mask", event_list=event_list_name
            )

    def save_masked(
        self,
        event_list_name: str,
        gtis: Any,
        destination_name: str,
    ) -> dict[str, Any]:
        """Save a detached GTI-filtered EventList under a unique state name."""
        try:
            name_error = validate_derived_name(destination_name)
            if name_error:
                return self.create_result(success=False, message=name_error, error=None)
            if self.state.has_event_data(destination_name):
                return self.create_result(
                    success=False,
                    message=f"EventList '{destination_name}' already exists; choose a unique name",
                    error=None,
                )

            event_list, applied, mask, warning_messages, preparation_error = (
                self._prepare_mask(event_list_name, gtis)
            )
            if preparation_error:
                return self.create_result(
                    success=False, message=preparation_error, error=None
                )
            assert event_list is not None and applied is not None and mask is not None

            # Reuse the exact preview mask. Stingray 2.2.10's
            # apply_gtis(..., inplace=False) recomputes that mask, leaves the
            # copied source GTI on its result, and rejects an empty GTI. Public
            # apply_mask avoids all three quirks.
            derived = event_list.apply_mask(mask, inplace=False)
            derived.gti = np.array(applied, dtype=np.longdouble, copy=True)

            if not self.state.add_event_data_if_absent(destination_name, derived):
                return self.create_result(
                    success=False,
                    message=(
                        f"EventList '{destination_name}' was created concurrently; "
                        "choose a unique name"
                    ),
                    error=None,
                )

            retained_count = 0 if derived.time is None else len(derived.time)
            provenance = operation_provenance(
                "gti.save_masked",
                input_source={"type": "event_list", "name": event_list_name},
                parameters={
                    "destination_name": destination_name,
                    "requested_gtis": gtis,
                },
                derived_object={"type": "event_list", "name": destination_name},
            )
            data = {
                "source_event_list_name": event_list_name,
                "destination_name": destination_name,
                "time_unit": "s",
                "time_reference": "absolute_mission_time",
                "source_event_count": len(mask),
                "retained_event_count": retained_count,
                "rejected_event_count": int(len(mask) - retained_count),
                "retained_exposure_s": (
                    float(np.sum(applied[:, 1] - applied[:, 0]))
                    if len(applied)
                    else 0.0
                ),
                "applied_gtis": _interval_payload(applied),
                "provenance": provenance,
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=(
                    f"Saved filtered EventList '{destination_name}' with "
                    f"{retained_count:,} event(s)"
                ),
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(
                exc,
                "Saving a GTI-filtered EventList",
                event_list=event_list_name,
                destination=destination_name,
            )

    def fixed_segments(
        self,
        gtis: Any,
        segment_size: Any,
        time_reference: str = "absolute_mission_time",
    ) -> dict[str, Any]:
        """Generate non-overlapping fixed-duration intervals within GTIs."""
        try:
            reference_error = _validate_time_reference(time_reference)
            if reference_error:
                return self.create_result(
                    success=False, message=reference_error, error=None
                )
            size, size_error = _strict_finite_scalar(segment_size, "segment_size")
            if size_error:
                return self.create_result(success=False, message=size_error, error=None)
            assert size is not None
            if size <= 0:
                return self.create_result(
                    success=False, message="segment_size must be positive", error=None
                )
            array, validation_error = _validate_gti_array(gtis)
            if validation_error:
                return self.create_result(
                    success=False, message=validation_error, error=None
                )
            assert array is not None

            origin, relative_gtis = _relative_gtis_for_step(
                array,
                size,
                allow_upward_snap=True,
            )
            lengths = relative_gtis[:, 1] - relative_gtis[:, 0]
            epsilon = 1e-5
            predicted = 0
            for length in lengths:
                if length + epsilon < size:
                    continue
                numerator = length - size + epsilon
                if numerator >= np.longdouble(size) * MAX_GTI_ROWS:
                    predicted = MAX_GTI_ROWS + 1
                    break
                quotient = numerator / np.longdouble(size)
                predicted += math.floor(float(quotient)) + 1
                if predicted > MAX_GTI_ROWS:
                    break
            if predicted == 0:
                return self.create_result(
                    success=False,
                    message=(
                        f"No GTI is at least segment_size ({size}s); reduce the segment size"
                    ),
                    error=None,
                )
            if predicted > MAX_GTI_ROWS:
                return self.create_result(
                    success=False,
                    message=(
                        f"segment_size would generate approximately {predicted:,} intervals; "
                        f"the cap is {MAX_GTI_ROWS:,}"
                    ),
                    error=None,
                )
            resolution_error = _step_resolution_error(array, size, "segment_size")
            if resolution_error:
                return self.create_result(
                    success=False,
                    message=resolution_error,
                    error=None,
                )

            # Upstream asserts instead of returning an empty pair.  The
            # preflight above gives users a meaningful message; this guard also
            # verifies that a future upstream result remains non-empty.
            # Absolute mission epochs amplify np.arange rounding.  Stingray's
            # public helper is still authoritative, but receives a translated
            # GTI array so its arithmetic is performed near zero.
            starts, stops = time_intervals_from_gtis(relative_gtis, size)
            relative_result, omitted_outside_gtis = _contained_fixed_segments(
                starts, stops, relative_gtis
            )
            translated_result = relative_result + origin
            result, omitted_after_translation = _contained_fixed_segments(
                translated_result[:, 0],
                translated_result[:, 1],
                array,
            )
            omitted_outside_gtis += omitted_after_translation
            if len(result) == 0:
                return self.create_result(
                    success=False,
                    message=(
                        f"No GTI fully contains a segment of {size}s; "
                        "reduce the segment size"
                    ),
                    error=None,
                )
            collapsed_row = _first_collapsed_binary64_interval(result)
            if collapsed_row is not None:
                return self.create_result(
                    success=False,
                    message=(
                        "A generated fixed-duration interval cannot be represented "
                        "with distinct binary64 absolute timestamps at row "
                        f"{collapsed_row}; use a larger segment_size or relative-second GTIs"
                    ),
                    error=None,
                )

            warning_messages: list[str] = []
            if omitted_outside_gtis:
                warning_messages.append(
                    f"Omitted {omitted_outside_gtis} candidate segment(s) returned by "
                    "Stingray because they exceeded a source GTI boundary."
                )
            source_lengths = array[:, 1] - array[:, 0]
            source_exposure_value = np.sum(source_lengths, dtype=np.longdouble)
            segmented_exposure_value = np.sum(
                result[:, 1] - result[:, 0], dtype=np.longdouble
            )
            exposure_tolerance = (
                np.longdouble(np.finfo(float).eps)
                * max(np.longdouble(1.0), abs(source_exposure_value))
                * 16
            )
            if segmented_exposure_value - source_exposure_value > exposure_tolerance:
                raise RuntimeError(
                    "Fixed-duration segments exceed the source good-time exposure"
                )
            if (
                abs(segmented_exposure_value - source_exposure_value)
                <= exposure_tolerance
            ):
                segmented_exposure_value = source_exposure_value
            source_exposure = float(source_exposure_value)
            segmented_exposure = float(segmented_exposure_value)
            unused = float(source_exposure_value - segmented_exposure_value)
            if unused > np.finfo(float).eps * max(1.0, source_exposure) * 16:
                warning_messages.append(
                    f"{unused:.12g} s of remainder shorter than one full segment was omitted."
                )
            data = {
                "segment_size_s": size,
                "source_exposure_s": source_exposure,
                "segmented_exposure_s": segmented_exposure,
                "unused_exposure_s": unused,
                "time_unit": "s",
                "time_reference": time_reference,
                **_interval_payload(result),
                "provenance": operation_provenance(
                    "gti.fixed_segments",
                    input_source={"type": "manual_gtis"},
                    parameters={
                        "segment_size": size,
                        "time_reference": time_reference,
                    },
                ),
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=f"Generated {len(result)} fixed-duration segment(s)",
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(exc, "Generating fixed-duration GTI segments")

    def split_by_exposure(
        self,
        gtis: Any,
        exposure_per_chunk: Any,
        new_interval_if_gti_sep: Any = None,
        time_reference: str = "absolute_mission_time",
    ) -> dict[str, Any]:
        """Split GTIs into Stingray's approximate-exposure chunk groups."""
        try:
            reference_error = _validate_time_reference(time_reference)
            if reference_error:
                return self.create_result(
                    success=False, message=reference_error, error=None
                )
            exposure, exposure_error = _strict_finite_scalar(
                exposure_per_chunk, "exposure_per_chunk"
            )
            if exposure_error:
                return self.create_result(
                    success=False, message=exposure_error, error=None
                )
            assert exposure is not None
            if exposure <= 0:
                return self.create_result(
                    success=False,
                    message="exposure_per_chunk must be positive",
                    error=None,
                )

            separation: float | None = None
            if new_interval_if_gti_sep is not None:
                separation, separation_error = _strict_finite_scalar(
                    new_interval_if_gti_sep, "new_interval_if_gti_sep"
                )
                if separation_error:
                    return self.create_result(
                        success=False, message=separation_error, error=None
                    )
                assert separation is not None
                if separation <= 0:
                    return self.create_result(
                        success=False,
                        message="new_interval_if_gti_sep must be positive when supplied",
                        error=None,
                    )

            array, validation_error = _validate_gti_array(gtis)
            if validation_error:
                return self.create_result(
                    success=False, message=validation_error, error=None
                )
            assert array is not None

            with np.errstate(over="ignore", invalid="ignore"):
                lengths = array[:, 1] - array[:, 0]
            nonfinite_lengths = np.flatnonzero(~np.isfinite(lengths))
            if nonfinite_lengths.size:
                interval_number = int(nonfinite_lengths[0]) + 1
                return self.create_result(
                    success=False,
                    message=(
                        f"GTIs interval {interval_number} has a duration that cannot "
                        "be represented as finite seconds; use a narrower time range"
                    ),
                    error=None,
                )
            with np.errstate(over="ignore", invalid="ignore"):
                source_exposure_value = np.sum(lengths, dtype=np.longdouble)
            if not np.isfinite(source_exposure_value):
                return self.create_result(
                    success=False,
                    message=(
                        "Total GTI exposure cannot be represented as finite seconds; "
                        "use fewer intervals or a narrower time range"
                    ),
                    error=None,
                )

            predicted_rows = 0
            for length in lengths:
                with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                    quotient = length / np.longdouble(exposure)
                remaining_rows = MAX_GTI_ROWS - predicted_rows
                if not np.isfinite(quotient) or quotient > remaining_rows:
                    predicted_rows = MAX_GTI_ROWS + 1
                    break
                predicted_rows += max(1, math.ceil(float(quotient)))
                if predicted_rows > MAX_GTI_ROWS:
                    break
            if predicted_rows > MAX_GTI_ROWS:
                return self.create_result(
                    success=False,
                    message=(
                        "exposure_per_chunk would require approximately "
                        f"{predicted_rows:,} GTI rows; the cap is {MAX_GTI_ROWS:,}"
                    ),
                    error=None,
                )
            resolution_error = _step_resolution_error(
                array,
                exposure,
                "exposure_per_chunk",
            )
            if resolution_error:
                return self.create_result(
                    success=False,
                    message=resolution_error,
                    error=None,
                )

            # As with fixed segments, split relative times so public Stingray
            # arithmetic is independent of a large absolute mission epoch.
            origin, relative_gtis = _relative_gtis_for_step(
                array,
                exposure,
                allow_upward_snap=False,
            )
            effective_separation = separation
            if separation is not None and not find_large_bad_time_intervals(
                relative_gtis,
                separation,
            ):
                # Stingray 2.2.10 indexes an empty compulsory-edge array when
                # the optional threshold finds no qualifying source gap.
                # In that no-op case, use its ordinary public split path.
                effective_separation = None
            raw_chunks = split_gtis_by_exposure(
                relative_gtis,
                exposure,
                new_interval_if_gti_sep=effective_separation,
            )
            # 2.2.10 returns either a list of 2-D arrays or a 3-D ndarray,
            # including ``(1, 0, 2)`` for empty input.  Empty input is rejected
            # above; normalize only the container shape here.
            chunks: list[np.ndarray] = []
            for index, raw_chunk in enumerate(raw_chunks):
                chunk = _normalise_upstream_gtis(
                    raw_chunk, label=f"exposure chunk {index + 1}"
                )
                if len(chunk) == 0:
                    # Stingray 2.2.10 can append an empty trailing chunk when
                    # np.arange lands exactly on the relative exposure edge.
                    continue
                chunks.append(chunk + origin)
            if not chunks:
                raise RuntimeError("Stingray returned no exposure chunks")
            serialized_row = 0
            for chunk in chunks:
                collapsed_row = _first_collapsed_binary64_interval(chunk)
                if collapsed_row is not None:
                    return self.create_result(
                        success=False,
                        message=(
                            "A split exposure interval cannot be represented with "
                            "distinct binary64 absolute timestamps at output row "
                            f"{serialized_row + collapsed_row}; use a larger "
                            "exposure_per_chunk or relative-second GTIs"
                        ),
                        error=None,
                    )
                serialized_row += len(chunk)
            total_rows = sum(len(chunk) for chunk in chunks)
            if total_rows > MAX_GTI_ROWS:
                raise RuntimeError(
                    f"Stingray returned {total_rows:,} split GTI rows; "
                    f"the cap is {MAX_GTI_ROWS:,}"
                )

            source_exposure = float(source_exposure_value)
            output_exposure = float(
                sum(np.sum(chunk[:, 1] - chunk[:, 0]) for chunk in chunks)
            )
            if not math.isclose(
                source_exposure,
                output_exposure,
                rel_tol=1e-12,
                abs_tol=np.finfo(float).eps * max(1.0, source_exposure) * 16,
            ):
                raise RuntimeError(
                    "Stingray exposure splitting did not preserve total good-time exposure"
                )

            chunk_payloads: list[dict[str, Any]] = []
            flat_starts: list[float] = []
            flat_stops: list[float] = []
            flat_chunk_indices: list[int] = []
            for index, chunk in enumerate(chunks):
                payload = _interval_payload(chunk)
                chunk_payloads.append(
                    {
                        "chunk_index": index + 1,
                        **payload,
                    }
                )
                flat_starts.extend(chunk[:, 0].astype(float).tolist())
                flat_stops.extend(chunk[:, 1].astype(float).tolist())
                flat_chunk_indices.extend([index + 1] * len(chunk))

            plot = bounded_plot_preview(flat_starts, flat_stops, flat_chunk_indices)
            warning_messages = [
                (
                    "Stingray's exposure split is approximate: chunks preserve GTI "
                    "boundaries and can differ from the requested exposure."
                )
            ]
            data = {
                "exposure_per_chunk_s": exposure,
                "new_interval_if_gti_sep_s": separation,
                "source_exposure_s": source_exposure,
                "output_exposure_s": output_exposure,
                "chunk_count": len(chunks),
                "interval_count": total_rows,
                "chunks": chunk_payloads,
                "plot": {
                    "starts": plot["arrays"][0],
                    "stops": plot["arrays"][1],
                    "chunk_indices": plot["arrays"][2],
                    "stride": plot["stride"],
                    "source_points": plot["source_points"],
                },
                "time_unit": "s",
                "time_reference": time_reference,
                "provenance": operation_provenance(
                    "gti.split_by_exposure",
                    input_source={"type": "manual_gtis"},
                    parameters={
                        "exposure_per_chunk": exposure,
                        "new_interval_if_gti_sep": separation,
                        "time_reference": time_reference,
                    },
                ),
            }
            return self.create_result(
                success=True,
                data=_safe_data(data, warning_messages),
                message=f"Split GTIs into {len(chunks)} approximate-exposure chunk(s)",
            )
        except Exception as exc:  # pragma: no cover - ErrorHandler integration
            return self.handle_error(exc, "Splitting GTIs by exposure")
