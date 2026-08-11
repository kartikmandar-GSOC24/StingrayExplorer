"""Curated public ``stingray.utils`` helpers for the Utilities workbench.

The service deliberately exposes a small, typed surface rather than arbitrary
function dispatch.  Every numerical result is produced by Stingray's public
API; this module adds bounded allocation, defensive validation, provenance and
JSON-safe presentation around those calls.
"""

from __future__ import annotations

import ast
import inspect
import math
import textwrap
from typing import Any, Iterable, Optional

import numpy as np
import stingray
from stingray.utils import (
    baseline_als,
    create_window,
    equal_count_energy_ranges,
    fix_segment_size_to_integer_samples,
    nearest_power_of_two,
    optimal_bin_time,
    poisson_symmetrical_errors,
    rebin_data,
    rebin_data_log,
    standard_error as stingray_standard_error,
)

from .analysis_helpers import collect_warnings
from .base_service import BaseService
from .utility_helpers import (
    MAX_ARRAY_INPUT,
    MAX_EXACT_OUTPUT,
    MAX_MATRIX_CELLS,
    MAX_STATE_SNAPSHOT_BYTES,
    MAX_STATE_SNAPSHOT_CELLS,
    bounded_plot_preview,
    json_safe,
    operation_provenance,
    validate_finite_array,
)

MAX_BASELINE_ITERATIONS = 100
MAX_ENERGY_RANGES = 1_000
MAX_FFT_SAMPLES = 2**24
MAX_POISSON_LOOKUP_COUNT = MAX_MATRIX_CELLS


def _derive_supported_windows() -> tuple[str, ...]:
    """Extract the exact allowlist used by the installed public function.

    ``create_window`` has no public capabilities function.  Its implementation
    does, however, define one local ``windows`` list which is the authoritative
    validation source (including upstream's historical ``blackmann`` spelling).
    Parsing that literal avoids maintaining a second list that can drift from
    the installed Stingray version.
    """

    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(create_window)))
    except (OSError, TypeError, SyntaxError):
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "windows"
                for target in targets
            ):
                continue
            value = node.value
            if not isinstance(value, (ast.List, ast.Tuple)):
                break
            names = tuple(
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
            if names and len(names) == len(value.elts):
                return names
            break

    # Frozen/PyInstaller builds commonly retain bytecode while omitting
    # retrievable source. The literal allowlist remains in ``co_consts``;
    # verify each candidate through the public API before accepting it.
    code = getattr(create_window, "__code__", None)
    for constant in getattr(code, "co_consts", ()):
        if not (
            isinstance(constant, (tuple, list))
            and constant
            and all(isinstance(item, str) for item in constant)
        ):
            continue
        candidate = tuple(constant)
        try:
            for name in candidate:
                create_window(2, name)
        except (TypeError, ValueError, IndexError):
            continue
        return candidate
    raise RuntimeError(
        "The installed create_window implementation has no derivable window allowlist"
    )


SUPPORTED_WINDOWS = _derive_supported_windows()


def _legacy_linear_rebin_uncertainty_behavior() -> bool:
    """Characterize whether installed ``rebin_data`` expects variances.

    Stingray 2.2.10 square-roots the *sum* of the values passed as ``yerr``.
    Upstream PR #953 changed it to square standard uncertainties before that
    sum.  A tiny public-API characterization keeps the workaround correct if
    the environment is later upgraded to a release containing the fix.
    """

    _, _, error, _ = rebin_data(
        np.asarray([0.5, 1.5]),
        np.asarray([0.0, 0.0]),
        2.0,
        yerr=np.asarray([2.0, 2.0]),
        method="sum",
        dx=1.0,
    )
    return bool(np.isclose(np.asarray(error, dtype=float)[0], 2.0))


LINEAR_REBIN_NEEDS_VARIANCE_INPUT = _legacy_linear_rebin_uncertainty_behavior()


def _finite_scalar(
    value: Any,
    label: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    minimum_inclusive: bool = True,
    maximum_inclusive: bool = True,
) -> tuple[Optional[float], Optional[str]]:
    """Validate a real scalar without accepting booleans as numbers."""

    if isinstance(value, (bool, np.bool_)):
        return None, f"{label} must be a finite number, not a boolean"
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None, f"{label} must be a finite number"
    if not math.isfinite(result):
        return None, f"{label} must be finite"
    if minimum is not None:
        bad = result < minimum if minimum_inclusive else result <= minimum
        if bad:
            operator = ">=" if minimum_inclusive else ">"
            return None, f"{label} must be {operator} {minimum}"
    if maximum is not None:
        bad = result > maximum if maximum_inclusive else result >= maximum
        if bad:
            operator = "<=" if maximum_inclusive else "<"
            return None, f"{label} must be {operator} {maximum}"
    return result, None


def _bounded_integer(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> tuple[Optional[int], Optional[str]]:
    """Validate an exact integer with an explicit inclusive range."""

    if isinstance(value, (bool, np.bool_)):
        return None, f"{label} must be an integer between {minimum} and {maximum}"
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None, f"{label} must be an integer between {minimum} and {maximum}"
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None, f"{label} must be an integer between {minimum} and {maximum}"
    integer = int(numeric)
    if integer < minimum or integer > maximum:
        return None, f"{label} must be between {minimum} and {maximum}"
    return integer, None


def _named_preview(names: Iterable[str], *arrays: Iterable[Any]) -> dict[str, Any]:
    """Name the aligned arrays returned by the shared bounded preview helper."""

    raw = bounded_plot_preview(*arrays)
    return {
        "values": dict(zip(names, raw["arrays"])),
        "stride": raw["stride"],
        "source_points": raw["source_points"],
    }


def _uniform_spacing_match(
    x: np.ndarray,
    spacing: float,
) -> tuple[bool, bool]:
    """Check a nominally uniform grid without mistaking float ULPs for jitter.

    Subtracting two large, nearby coordinates can only represent their spacing
    to roughly the ULP of those coordinates.  The tolerance below combines the
    service's ordinary relative tolerance with the IEEE-754 rounding bound for
    both stored endpoints and their subtraction.  ``ulp_accommodation_used``
    tells callers when the grid passes only because that representational bound
    is necessary, so the normalization can be disclosed to the user.
    """

    observed = np.diff(x)
    ordinary_tolerance = 1e-10 * abs(spacing) + 16 * np.finfo(float).eps * max(
        1.0, abs(spacing)
    )
    endpoint_roundoff = 0.5 * (np.abs(np.spacing(x[:-1])) + np.abs(np.spacing(x[1:])))
    subtraction_roundoff = 0.5 * np.abs(np.spacing(observed))
    ulp_tolerance = endpoint_roundoff + subtraction_roundoff
    error = np.abs(observed - spacing)
    matches_ordinary = bool(np.all(error <= ordinary_tolerance))
    matches_with_ulps = bool(
        np.all(error <= np.maximum(ordinary_tolerance, ulp_tolerance))
    )
    return matches_with_ulps, matches_with_ulps and not matches_ordinary


def _normalization_scale(values: np.ndarray) -> float:
    """Return a finite homogeneous scale that avoids square/sum overflow."""

    maximum = float(np.max(np.abs(values)))
    return maximum if maximum > 0.0 else 1.0


def _normalize_finite_input(
    values: np.ndarray,
    scale: float,
    *,
    label: str,
) -> tuple[Optional[np.ndarray], Optional[str]]:
    """Apply homogeneous conditioning without erasing nonzero input values."""

    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        normalized = np.asarray(values, dtype=float) / scale
    if np.any((values != 0.0) & (normalized == 0.0)):
        return (
            None,
            f"{label} spans too wide a finite dynamic range to condition without "
            "losing nonzero values; the result was withheld",
        )
    return normalized, None


def _restore_scaled_output(
    values: Any,
    scale: float,
    *,
    label: str,
) -> tuple[Optional[np.ndarray], Optional[str]]:
    """Undo homogeneous conditioning and fail closed on range overflow."""

    normalized = np.asarray(values, dtype=float)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        restored = normalized * scale
    underflowed = (normalized != 0.0) & (restored == 0.0)
    if not np.all(np.isfinite(restored)) or np.any(underflowed):
        return (
            None,
            f"{label} is outside the finite float range; the result was withheld",
        )
    return restored, None


class MiscService(BaseService):
    """Service wrapper around the supported public ``stingray.utils`` tools."""

    def _invalid(self, message: str) -> dict[str, Any]:
        return self.create_result(success=False, message=message, error=None)

    def _success(
        self,
        data: dict[str, Any],
        message: str,
        warnings: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        warning_list = list(dict.fromkeys(warnings or []))
        safe_data = json_safe(data, warning_list)
        safe_data["warnings"] = list(dict.fromkeys(warning_list))
        return self.create_result(
            success=True, data=safe_data, message=message, error=None
        )

    @staticmethod
    def _xy_arrays(
        x: Iterable[Any],
        y: Iterable[Any],
        *,
        min_size: int,
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[str]]:
        x_array, error = validate_finite_array(x, label="x", min_size=1)
        if error:
            return None, None, error
        y_array, error = validate_finite_array(y, label="y", min_size=1)
        if error:
            return None, None, error
        assert x_array is not None and y_array is not None
        if x_array.shape != y_array.shape:
            return None, None, "x and y must have the same length"
        if x_array.size < min_size:
            return (
                None,
                None,
                f"x and y must contain at least {min_size} values each",
            )
        bad_spacing = np.flatnonzero(np.diff(x_array) <= 0)
        if bad_spacing.size:
            index = int(bad_spacing[0])
            return (
                None,
                None,
                f"x must be strictly increasing; x[{index + 1}] is not greater than x[{index}]",
            )
        return x_array, y_array, None

    def capabilities(self) -> dict[str, Any]:
        """Return installed capabilities, defaults and allocation limits."""

        data = {
            "window_types": list(SUPPORTED_WINDOWS),
            "rebin": {
                "modes": ["linear", "logarithmic"],
                "linear_methods": ["sum", "mean"],
                "logarithmic_method": "mean",
                "linear_uncertainty_workaround_required": (
                    LINEAR_REBIN_NEEDS_VARIANCE_INPUT
                ),
                "linear_uncertainty_workaround_reference": (
                    "StingraySoftware/stingray#953"
                ),
                "linear_uncertainty_support": (
                    "uniform x spacing and an integer dx_new / dx ratio only; "
                    "fractional-overlap uncertainty weights are not squared upstream"
                ),
            },
            "baseline_defaults": {
                "lambda": 1e11,
                "asymmetry": 0.001,
                "iterations": 10,
                "offset_correction": False,
            },
            "limits": {
                "max_array_values": MAX_ARRAY_INPUT,
                "max_exact_output_values": MAX_EXACT_OUTPUT,
                "max_matrix_cells": MAX_MATRIX_CELLS,
                "max_baseline_iterations": MAX_BASELINE_ITERATIONS,
                "max_fft_samples": MAX_FFT_SAMPLES,
                "max_poisson_count": MAX_POISSON_LOOKUP_COUNT,
                "max_energy_ranges": MAX_ENERGY_RANGES,
            },
            "runtime_advisories": {
                "nearest_power_of_two": (
                    "Results are fail-closed if installed Stingray 2.2.10 returns "
                    "a value that is not mathematically nearest."
                )
            },
            "provenance": operation_provenance(
                "misc_capabilities",
                input_source={"kind": "installed_runtime"},
                parameters={},
                window_allowlist_source="installed create_window source literal",
            ),
        }
        return self._success(data, "Miscellaneous utility capabilities loaded")

    def linear_rebin(
        self,
        x: Iterable[Any],
        y: Iterable[Any],
        dx_new: Any,
        *,
        y_error: Optional[Iterable[Any]] = None,
        method: str = "sum",
        dx: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Linearly rebin x/y data while propagating standard uncertainties."""

        try:
            x_array, y_array, error = self._xy_arrays(x, y, min_size=2)
            if error:
                return self._invalid(error)
            assert x_array is not None and y_array is not None

            resolution, error = _finite_scalar(
                dx_new, "dx_new", minimum=0.0, minimum_inclusive=False
            )
            if error:
                return self._invalid(error)
            assert resolution is not None

            if method not in {"sum", "mean"}:
                return self._invalid("method must be either 'sum' or 'mean'")

            old_resolution: Optional[float] = None
            if dx is not None:
                old_resolution, error = _finite_scalar(
                    dx, "dx", minimum=0.0, minimum_inclusive=False
                )
                if error:
                    return self._invalid(error)

            # Validate whole-interval coverage before calculating any rebin
            # factor.  Otherwise an extreme but finite ``dx_new`` can overflow
            # ``round(dx_new / dx)`` and leak a technical exception before the
            # scientifically meaningful "no complete bin" check runs.
            tail_resolution = (
                old_resolution
                if old_resolution is not None
                else float(x_array[-1] - x_array[-2])
            )
            with np.errstate(over="ignore", invalid="ignore"):
                covered_span = float((x_array[-1] - x_array[0]) + tail_resolution)
            if not math.isfinite(covered_span) or covered_span <= 0:
                return self._invalid(
                    "The covered input span is not representable as a positive "
                    "finite number"
                )
            span_tolerance = 8.0 * max(
                abs(float(np.spacing(covered_span))),
                abs(float(np.spacing(resolution))),
            )
            if resolution > covered_span + span_tolerance:
                return self._invalid(
                    "dx_new is wider than the covered input span, so no complete "
                    f"output bin fits (dx_new={resolution:g}, covered span={covered_span:g})"
                )

            errors: Optional[np.ndarray] = None
            uniform_dx: Optional[float] = None
            canonical_rebin_factor: Optional[int] = None
            ulp_accommodation_used = False
            if y_error is not None:
                errors, error = validate_finite_array(
                    y_error,
                    label="y_error",
                    min_size=2,
                )
                if error:
                    return self._invalid(error)
                assert errors is not None
                if errors.shape != y_array.shape:
                    return self._invalid("y_error must have the same length as x and y")
                bad = np.flatnonzero(errors < 0)
                if bad.size:
                    return self._invalid(f"y_error[{int(bad[0])}] must be non-negative")

                observed_spacing = np.diff(x_array)
                if old_resolution is not None:
                    uniform_dx = old_resolution
                    spacing_matches, ulp_accommodation_used = _uniform_spacing_match(
                        x_array, uniform_dx
                    )
                else:
                    # The median is robust to the alternating adjacent spacings
                    # produced when a small cadence is stored on a large offset.
                    uniform_dx = float(np.median(observed_spacing))
                    spacing_matches, ulp_accommodation_used = _uniform_spacing_match(
                        x_array, uniform_dx
                    )
                    if spacing_matches:
                        nearest_factor = round(resolution / uniform_dx)
                        if nearest_factor >= 1:
                            candidate_dx = resolution / nearest_factor
                            candidate_matches, candidate_used_ulps = (
                                _uniform_spacing_match(x_array, candidate_dx)
                            )
                            if candidate_matches:
                                uniform_dx = candidate_dx
                                ulp_accommodation_used = (
                                    ulp_accommodation_used or candidate_used_ulps
                                )

                if not spacing_matches:
                    return self._invalid(
                        "y_error propagation is supported only for uniformly spaced x "
                        "values; an explicit dx must also match that spacing"
                    )
                assert uniform_dx is not None
                rebin_factor = resolution / uniform_dx
                if not math.isclose(
                    rebin_factor,
                    round(rebin_factor),
                    rel_tol=1e-10,
                    abs_tol=1e-12,
                ):
                    return self._invalid(
                        "y_error propagation requires an integer dx_new / dx ratio. "
                        "Stingray 2.2.10 does not square fractional-overlap weights, "
                        "so uncertainty propagation would be scientifically incorrect."
                    )
                canonical_rebin_factor = int(round(rebin_factor))

            if errors is None:
                candidate_dx = (
                    old_resolution
                    if old_resolution is not None
                    else float(np.median(np.diff(x_array)))
                )
                spacing_matches, candidate_used_ulps = _uniform_spacing_match(
                    x_array, candidate_dx
                )
                candidate_factor = resolution / candidate_dx
                if (
                    spacing_matches
                    and candidate_factor >= 1
                    and math.isclose(
                        candidate_factor,
                        round(candidate_factor),
                        rel_tol=1e-10,
                        abs_tol=1e-12,
                    )
                ):
                    uniform_dx = candidate_dx
                    canonical_rebin_factor = int(round(candidate_factor))
                    ulp_accommodation_used = candidate_used_ulps

            dx_old = (
                np.diff(x_array)
                if old_resolution is None
                else np.asarray([old_resolution], dtype=float)
            )
            effective_old_resolution = uniform_dx if errors is not None else None
            resolution_comparison = (
                np.asarray([effective_old_resolution], dtype=float)
                if effective_old_resolution is not None
                else dx_old
            )
            if np.any(resolution < resolution_comparison):
                return self._invalid(
                    "dx_new must be at least as large as every old x resolution"
                )

            estimated_bins = (
                math.ceil(
                    (float(x_array[-1] - x_array[0]) + float(dx_old[-1])) / resolution
                )
                + 2
            )
            if estimated_bins > MAX_EXACT_OUTPUT:
                return self._invalid(
                    f"linear rebin would allocate about {estimated_bins:,} bins; "
                    f"the cap is {MAX_EXACT_OUTPUT:,}"
                )

            # Both supported aggregations are homogeneous in y, and propagated
            # standard uncertainties are homogeneous in sigma.  Normalize before
            # the public Stingray call so its intermediate sums and squares do not
            # overflow or underflow for otherwise representable finite results.
            candidate_scale = _normalization_scale(y_array)
            conditioning_boundary = math.sqrt(np.finfo(float).max)
            underflow_boundary = math.sqrt(np.finfo(float).tiny)
            y_scale = (
                candidate_scale
                if candidate_scale > conditioning_boundary
                or candidate_scale < underflow_boundary
                else 1.0
            )
            normalized_y = y_array / y_scale
            error_scale = _normalization_scale(errors) if errors is not None else 1.0
            normalized_errors = errors / error_scale if errors is not None else None

            warning_list: list[str] = []
            stingray_error_input = normalized_errors
            workaround_applied = bool(
                errors is not None and LINEAR_REBIN_NEEDS_VARIANCE_INPUT
            )
            if workaround_applied:
                # Stingray 2.2.10 sums yerr and then square-roots it.  Supplying
                # variances yields sqrt(sum(sigma^2)), exactly the #953 fix,
                # after the checks above rule out fractional-overlap weights.
                stingray_error_input = np.square(normalized_errors)
                warning_list.append(
                    "Installed Stingray rebin_data treats yerr as variances. "
                    "Squared standard uncertainties were supplied as the compatibility "
                    "workaround from upstream PR #953; Stingray controlled the bin "
                    "boundaries and aggregation for whole, non-overlapping samples."
                )

            x_origin = float(x_array[0])
            coordinate_scale = 1.0
            stingray_resolution = resolution
            if canonical_rebin_factor is not None:
                assert uniform_dx is not None
                # Integer sample coordinates avoid two installed-2.2.10 edge
                # defects without changing the public scientific operation:
                # large absolute origins create fractional-overlap artifacts,
                # and float modulo can misclassify an exact whole-bin span and
                # silently discard its final complete bin.
                stingray_x = np.arange(x_array.size, dtype=float)
                stingray_dx = 1.0
                stingray_resolution = float(canonical_rebin_factor)
                coordinate_scale = uniform_dx
                if ulp_accommodation_used:
                    warning_list.append(
                        "The x values match a uniform grid only after accounting for "
                        "floating-point ULPs at their absolute scale. Stingray "
                        "rebin_data was evaluated on an equivalent origin-relative "
                        "grid to avoid precision-induced fractional overlaps; output "
                        "coordinates were translated back."
                    )
                with np.errstate(over="ignore", invalid="ignore"):
                    raw_span_ratio = (
                        x_array[-1] - x_array[0] + uniform_dx
                    ) / resolution
                if (
                    x_array.size % canonical_rebin_factor == 0
                    and math.isfinite(float(raw_span_ratio))
                    and float(raw_span_ratio) % 1 > 0
                ):
                    warning_list.append(
                        "The installed Stingray 2.2.10 float-modulo edge check would "
                        "misclassify this exact whole-bin span. The equivalent integer "
                        "sample grid was used so no complete trailing bin was discarded."
                    )
            else:
                stingray_x = x_array - x_origin
                stingray_dx = old_resolution

            with collect_warnings(warning_list):
                x_bin, y_bin, error_bin, samples = rebin_data(
                    stingray_x,
                    normalized_y,
                    stingray_resolution,
                    yerr=stingray_error_input,
                    method=method,
                    dx=stingray_dx,
                )
            x_bin = np.asarray(x_bin, dtype=float) * coordinate_scale + x_origin
            if not np.all(np.isfinite(x_bin)):
                return self._invalid(
                    "linear-rebin x coordinates are outside the finite float range; "
                    "the result was withheld"
                )
            normalized_y_bin = np.asarray(y_bin, dtype=float)
            y_bin, output_error = _restore_scaled_output(
                normalized_y_bin,
                y_scale,
                label="linear-rebin y output",
            )
            if output_error:
                return self._invalid(output_error)
            assert y_bin is not None
            normalized_error_bin = np.asarray(error_bin, dtype=float)
            if errors is not None:
                error_bin, output_error = _restore_scaled_output(
                    normalized_error_bin,
                    error_scale,
                    label="linear-rebin uncertainty output",
                )
                if output_error:
                    return self._invalid(output_error)
                assert error_bin is not None
            else:
                error_bin = normalized_error_bin

            if canonical_rebin_factor is not None:
                expected_bins = x_array.size // canonical_rebin_factor
                if len(y_bin) != expected_bins:
                    return self._invalid(
                        "Installed Stingray returned an unexpected number of complete "
                        "linear-rebin bins; the result was withheld"
                    )
                complete_count = expected_bins * canonical_rebin_factor
                if complete_count:
                    grouped = normalized_y[:complete_count].reshape(
                        expected_bins, canonical_rebin_factor
                    )
                    expected_y = (
                        np.sum(grouped, axis=1)
                        if method == "sum"
                        else np.mean(grouped, axis=1)
                    )
                    if not np.allclose(
                        normalized_y_bin,
                        expected_y,
                        rtol=1e-12,
                        atol=1e-14,
                    ):
                        return self._invalid(
                            "Installed Stingray did not preserve the complete uniform "
                            "input bins; the result was withheld"
                        )

            original_preview_arrays: list[np.ndarray] = [x_array, y_array]
            original_preview_names = ["x", "y"]
            rebinned_preview_arrays: list[np.ndarray] = [x_bin, y_bin]
            rebinned_preview_names = ["x", "y"]
            if errors is not None:
                original_preview_arrays.append(errors)
                original_preview_names.append("y_error")
                rebinned_preview_arrays.append(error_bin)
                rebinned_preview_names.append("y_error")

            parameters = {
                "dx_new": resolution,
                "dx": old_resolution,
                "method": method,
                "uncertainties_supplied": errors is not None,
            }
            data = {
                "mode": "linear",
                "method": method,
                "units": {
                    "x": "same as input x",
                    "y": "same as input y",
                    "y_error": "same as input y",
                    "samples_per_bin": "input samples",
                },
                "original": {
                    "x": x_array,
                    "y": y_array,
                    "y_error": errors,
                },
                "rebinned": {
                    "x": x_bin,
                    "y": y_bin,
                    "y_error": error_bin if errors is not None else None,
                    "samples_per_bin": samples,
                },
                "error_semantics": (
                    "independent one-standard-deviation uncertainties propagated "
                    "in quadrature"
                    if errors is not None
                    else None
                ),
                "plot_preview": {
                    "original": _named_preview(
                        original_preview_names, *original_preview_arrays
                    ),
                    "rebinned": _named_preview(
                        rebinned_preview_names, *rebinned_preview_arrays
                    ),
                },
                "provenance": operation_provenance(
                    "linear_rebin",
                    input_source={"kind": "pasted_values"},
                    parameters=parameters,
                    uncertainty_compatibility={
                        "workaround_applied": workaround_applied,
                        "reference": "StingraySoftware/stingray#953",
                        "input_to_stingray": (
                            "variance" if workaround_applied else "standard_uncertainty"
                        )
                        if errors is not None
                        else None,
                    },
                    coordinate_processing={
                        "origin_relative_stingray_input": True,
                        "uniform_grid_reexpressed": canonical_rebin_factor is not None,
                        "ulp_accommodation_used": ulp_accommodation_used,
                    },
                    numeric_conditioning={
                        "homogeneous_y_scale": y_scale,
                        "homogeneous_uncertainty_scale": (
                            error_scale if errors is not None else None
                        ),
                    },
                ),
            }
            return self._success(data, "Data rebinned linearly", warning_list)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "linear rebinning")

    def logarithmic_rebin(
        self,
        x: Iterable[Any],
        y: Iterable[Any],
        factor: Any,
        *,
        y_error: Optional[Iterable[Any]] = None,
        dx: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Logarithmically rebin x/y data using Stingray's mean-only helper."""

        try:
            x_array, y_array, error = self._xy_arrays(x, y, min_size=2)
            if error:
                return self._invalid(error)
            assert x_array is not None and y_array is not None
            if np.any(x_array <= 0):
                index = int(np.flatnonzero(x_array <= 0)[0])
                return self._invalid(
                    f"x[{index}] must be positive for logarithmic rebinning"
                )

            growth, error = _finite_scalar(
                factor, "factor", minimum=0.0, minimum_inclusive=False
            )
            if error:
                return self._invalid(error)
            assert growth is not None

            old_resolution: Optional[float] = None
            if dx is not None:
                old_resolution, error = _finite_scalar(
                    dx, "dx", minimum=0.0, minimum_inclusive=False
                )
                if error:
                    return self._invalid(error)
            initial_resolution = (
                float(np.median(np.diff(x_array)))
                if old_resolution is None
                else old_resolution
            )

            # Mirror the installed scalar boundary-growth loop, including its
            # realized (rounded) width.  At a large absolute origin with a tiny
            # dx, ``edge + dx * (1 + factor)`` can repeatedly round to exactly
            # ``edge + dx``.  Upstream then keeps the same width for an enormous
            # number of iterations and effectively hangs the request.
            first_edge = float(x_array[0] * 0.5)
            edge = float(first_edge + initial_resolution)
            if (
                not math.isfinite(first_edge)
                or not math.isfinite(edge)
                or edge <= first_edge
            ):
                return self._invalid(
                    "the initial logarithmic bin width is not representable at the "
                    "absolute x scale"
                )
            width = initial_resolution
            estimated_bins = 1
            while edge <= float(x_array[-1]):
                with np.errstate(over="ignore", invalid="ignore"):
                    next_edge = float(edge + width * (1.0 + growth))
                if not math.isfinite(next_edge):
                    return self._invalid(
                        "factor produces non-finite logarithmic bin edges"
                    )
                realized_width = next_edge - edge
                if realized_width <= width:
                    return self._invalid(
                        "the logarithmic bin width cannot grow at the absolute x "
                        "scale with this factor; the public Stingray call was withheld "
                        "to avoid a non-progressing edge loop"
                    )
                edge = next_edge
                width = realized_width
                estimated_bins += 1
                if estimated_bins > MAX_EXACT_OUTPUT:
                    return self._invalid(
                        f"logarithmic rebin would allocate more than "
                        f"{MAX_EXACT_OUTPUT:,} bins"
                    )

            errors: Optional[np.ndarray] = None
            if y_error is not None:
                errors, error = validate_finite_array(
                    y_error,
                    label="y_error",
                    min_size=2,
                )
                if error:
                    return self._invalid(error)
                assert errors is not None
                if errors.shape != y_array.shape:
                    return self._invalid("y_error must have the same length as x and y")
                bad = np.flatnonzero(errors < 0)
                if bad.size:
                    return self._invalid(f"y_error[{int(bad[0])}] must be non-negative")

            y_scale = _normalization_scale(y_array)
            normalized_y = y_array / y_scale
            error_scale = _normalization_scale(errors) if errors is not None else 1.0
            normalized_errors = errors / error_scale if errors is not None else None

            warning_list: list[str] = []
            with collect_warnings(warning_list):
                x_bin, y_bin, error_bin, samples = rebin_data_log(
                    x_array,
                    normalized_y,
                    growth,
                    y_err=normalized_errors,
                    dx=old_resolution,
                )

            x_bin = np.asarray(x_bin, dtype=float)
            if not np.all(np.isfinite(x_bin)):
                return self._invalid(
                    "logarithmic-rebin x coordinates are outside the finite float "
                    "range; the result was withheld"
                )
            y_bin, output_error = _restore_scaled_output(
                y_bin,
                y_scale,
                label="logarithmic-rebin y output",
            )
            if output_error:
                return self._invalid(output_error)
            assert y_bin is not None
            if errors is not None:
                error_bin, output_error = _restore_scaled_output(
                    error_bin,
                    error_scale,
                    label="logarithmic-rebin uncertainty output",
                )
                if output_error:
                    return self._invalid(output_error)
                assert error_bin is not None
            else:
                error_bin = np.asarray(error_bin, dtype=float)

            original_preview_arrays: list[np.ndarray] = [x_array, y_array]
            original_preview_names = ["x", "y"]
            rebinned_preview_arrays: list[np.ndarray] = [x_bin, y_bin]
            rebinned_preview_names = ["x", "y"]
            if errors is not None:
                original_preview_arrays.append(errors)
                original_preview_names.append("y_error")
                rebinned_preview_arrays.append(error_bin)
                rebinned_preview_names.append("y_error")

            parameters = {
                "factor": growth,
                "dx": old_resolution,
                "method": "mean",
                "uncertainties_supplied": errors is not None,
            }
            data = {
                "mode": "logarithmic",
                "method": "mean",
                "units": {
                    "x": "same as input x",
                    "y": "same as input y",
                    "y_error": "same as input y",
                    "samples_per_bin": "input samples",
                },
                "original": {
                    "x": x_array,
                    "y": y_array,
                    "y_error": errors,
                },
                "rebinned": {
                    "x": x_bin,
                    "y": y_bin,
                    "y_error": error_bin if errors is not None else None,
                    "samples_per_bin": samples,
                },
                "error_semantics": (
                    "standard uncertainty of the arithmetic mean, computed as "
                    "sqrt(sum(sigma_i^2)) / N and assuming independent input errors"
                    if errors is not None
                    else None
                ),
                "plot_preview": {
                    "original": _named_preview(
                        original_preview_names, *original_preview_arrays
                    ),
                    "rebinned": _named_preview(
                        rebinned_preview_names, *rebinned_preview_arrays
                    ),
                },
                "provenance": operation_provenance(
                    "logarithmic_rebin",
                    input_source={"kind": "pasted_values"},
                    parameters=parameters,
                    numeric_conditioning={
                        "homogeneous_y_scale": y_scale,
                        "homogeneous_uncertainty_scale": (
                            error_scale if errors is not None else None
                        ),
                    },
                ),
            }
            return self._success(data, "Data rebinned logarithmically", warning_list)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "logarithmic rebinning")

    def estimate_baseline(
        self,
        x: Iterable[Any],
        y: Iterable[Any],
        *,
        lam: Any = 1e11,
        asymmetry: Any = 0.001,
        iterations: Any = 10,
        offset_correction: bool = False,
    ) -> dict[str, Any]:
        """Estimate and subtract an asymmetric least-squares baseline."""

        try:
            x_array, y_array, error = self._xy_arrays(x, y, min_size=3)
            if error:
                return self._invalid(error)
            assert x_array is not None and y_array is not None

            smoothing, error = _finite_scalar(
                lam, "lambda", minimum=0.0, minimum_inclusive=False
            )
            if error:
                return self._invalid(error)
            probability, error = _finite_scalar(
                asymmetry,
                "asymmetry",
                minimum=0.0,
                maximum=1.0,
                minimum_inclusive=False,
                maximum_inclusive=False,
            )
            if error:
                return self._invalid(error)
            n_iterations, error = _bounded_integer(
                iterations,
                "iterations",
                minimum=1,
                maximum=MAX_BASELINE_ITERATIONS,
            )
            if error:
                return self._invalid(error)
            if not isinstance(offset_correction, (bool, np.bool_)):
                return self._invalid("offset_correction must be a boolean")
            assert smoothing is not None and probability is not None
            assert n_iterations is not None

            candidate_scale = _normalization_scale(y_array)
            conditioning_boundary = math.sqrt(np.finfo(float).max)
            underflow_boundary = math.sqrt(np.finfo(float).tiny)
            y_scale = (
                candidate_scale
                if candidate_scale > conditioning_boundary
                or candidate_scale < underflow_boundary
                else 1.0
            )
            normalized_y = y_array / y_scale
            warning_list: list[str] = []
            with collect_warnings(warning_list):
                corrected, baseline = baseline_als(
                    x_array,
                    normalized_y,
                    lam=smoothing,
                    p=probability,
                    niter=n_iterations,
                    return_baseline=True,
                    offset_correction=bool(offset_correction),
                )

            baseline, output_error = _restore_scaled_output(
                baseline,
                y_scale,
                label="baseline output",
            )
            if output_error:
                return self._invalid(output_error)
            corrected, output_error = _restore_scaled_output(
                corrected,
                y_scale,
                label="baseline-corrected output",
            )
            if output_error:
                return self._invalid(output_error)
            assert baseline is not None and corrected is not None

            parameters = {
                "lambda": smoothing,
                "asymmetry": probability,
                "iterations": n_iterations,
                "offset_correction": bool(offset_correction),
            }
            data = {
                "x": x_array,
                "original": y_array,
                "baseline": baseline,
                "corrected": corrected,
                "units": {
                    "x": "same as input x",
                    "original": "same as input y",
                    "baseline": "same as input y",
                    "corrected": "same as input y",
                },
                "plot_preview": _named_preview(
                    ["x", "original", "baseline", "corrected"],
                    x_array,
                    y_array,
                    baseline,
                    corrected,
                ),
                "provenance": operation_provenance(
                    "asymmetric_least_squares_baseline",
                    input_source={"kind": "pasted_values"},
                    parameters=parameters,
                    numeric_conditioning={"homogeneous_y_scale": y_scale},
                ),
            }
            return self._success(
                data, "Asymmetric least-squares baseline estimated", warning_list
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "baseline estimation")

    def generate_window(
        self, n_samples: Any, window_type: Any = "uniform"
    ) -> dict[str, Any]:
        """Generate one of the windows supported by installed Stingray."""

        try:
            count, error = _bounded_integer(
                n_samples,
                "n_samples",
                minimum=2,
                maximum=MAX_EXACT_OUTPUT,
            )
            if error:
                return self._invalid(error)
            if not isinstance(window_type, str):
                return self._invalid("window_type must be a string")
            canonical_type = window_type.lower()
            if canonical_type not in SUPPORTED_WINDOWS:
                return self._invalid(
                    "window_type must be one of: " + ", ".join(SUPPORTED_WINDOWS)
                )
            assert count is not None

            warning_list: list[str] = []
            with collect_warnings(warning_list):
                window = create_window(count, canonical_type)
            indices = np.arange(count, dtype=int)

            window_sum = float(np.sum(window))
            energy = float(np.sum(np.square(window)))
            equivalent_noise_bandwidth: Optional[float]
            if np.isclose(window_sum, 0.0, rtol=0.0, atol=np.finfo(float).eps):
                equivalent_noise_bandwidth = None
                warning_list.append(
                    "Equivalent noise bandwidth is undefined because this short "
                    "window has zero coherent sum."
                )
            else:
                equivalent_noise_bandwidth = count * energy / window_sum**2

            data = {
                "window_type": canonical_type,
                "n_samples": count,
                "sample_index": indices,
                "window": window,
                "units": {
                    "sample_index": "sample",
                    "window": "dimensionless",
                    "summary": "dimensionless unless named in bins",
                },
                "summary": {
                    "minimum": np.min(window),
                    "maximum": np.max(window),
                    "sum": window_sum,
                    "mean": np.mean(window),
                    "rms": np.sqrt(np.mean(np.square(window))),
                    "energy": energy,
                    "coherent_gain": np.mean(window),
                    "equivalent_noise_bandwidth_bins": equivalent_noise_bandwidth,
                },
                "plot_preview": _named_preview(
                    ["sample_index", "window"], indices, window
                ),
                "provenance": operation_provenance(
                    "create_window",
                    input_source={"kind": "parameters"},
                    parameters={
                        "n_samples": count,
                        "window_type": canonical_type,
                    },
                    supported_window_types=list(SUPPORTED_WINDOWS),
                    window_allowlist_source="installed create_window source literal",
                ),
            }
            return self._success(
                data, f"{canonical_type} window generated", warning_list
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "window generation")

    def calculate_optimal_bin_time(
        self, fft_length: Any, proposed_bin_time: Any
    ) -> dict[str, Any]:
        """Adjust a bin time so an FFT interval has a power-of-two sample count."""

        try:
            length, error = _finite_scalar(
                fft_length,
                "fft_length",
                minimum=0.0,
                minimum_inclusive=False,
            )
            if error:
                return self._invalid(error)
            proposed, error = _finite_scalar(
                proposed_bin_time,
                "proposed_bin_time",
                minimum=0.0,
                minimum_inclusive=False,
            )
            if error:
                return self._invalid(error)
            assert length is not None and proposed is not None
            if proposed > length:
                return self._invalid("proposed_bin_time must not exceed fft_length")
            requested_samples = length / proposed
            if (
                not math.isfinite(requested_samples)
                or requested_samples > MAX_FFT_SAMPLES
            ):
                return self._invalid(
                    f"the requested FFT would require {requested_samples:,.0f} samples; "
                    f"the cap is {MAX_FFT_SAMPLES:,}"
                )

            adjusted = float(optimal_bin_time(length, proposed))
            if not math.isfinite(adjusted) or adjusted <= 0.0:
                return self._invalid(
                    "installed Stingray returned a non-finite or non-positive FFT "
                    "bin time; the result was withheld"
                )
            reconstructed_samples = length / adjusted
            if not math.isfinite(reconstructed_samples):
                return self._invalid(
                    "the adjusted FFT sample count is not representable; the result "
                    "was withheld"
                )
            sample_count = int(round(reconstructed_samples))
            if sample_count <= 0 or sample_count & (sample_count - 1):
                return self._invalid(
                    "installed Stingray did not produce a positive power-of-two FFT "
                    "sample count at this numeric scale; the result was withheld"
                )
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                reconstructed_length = adjusted * sample_count
            reconstruction_tolerance = max(
                1e-12 * abs(length),
                8.0 * abs(float(np.spacing(length))),
                8.0 * abs(float(np.spacing(reconstructed_length))),
            )
            if (
                not math.isfinite(reconstructed_length)
                or abs(reconstructed_length - length) > reconstruction_tolerance
            ):
                return self._invalid(
                    "the adjusted FFT bin time does not reconstruct fft_length with "
                    "a representable power-of-two sample count; the result was withheld"
                )
            delta = adjusted - proposed
            changed = not math.isclose(adjusted, proposed, rel_tol=1e-12, abs_tol=0.0)
            warnings = []
            if changed:
                warnings.append(
                    f"Bin time changed by {delta:.12g} ({delta / proposed * 100:.6g}%)."
                )
            parameters = {
                "fft_length": length,
                "proposed_bin_time": proposed,
            }
            data = {
                "requested_bin_time": proposed,
                "adjusted_bin_time": adjusted,
                "sample_count": sample_count,
                "delta": delta,
                "fractional_change": delta / proposed,
                "changed": changed,
                "units": "same time units as fft_length and proposed_bin_time",
                "provenance": operation_provenance(
                    "optimal_bin_time",
                    input_source={"kind": "parameters"},
                    parameters=parameters,
                ),
            }
            return self._success(data, "Optimal FFT bin time calculated", warnings)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "optimal FFT bin-time calculation")

    def calculate_nearest_power_of_two(self, value: Any) -> dict[str, Any]:
        """Return Stingray's nearest integral power of two."""

        try:
            requested, error = _bounded_integer(
                value,
                "value",
                minimum=2,
                maximum=MAX_FFT_SAMPLES,
            )
            if error:
                return self._invalid(error)
            assert requested is not None
            nearest = int(nearest_power_of_two(requested))
            lower = 2 ** int(math.floor(math.log2(requested)))
            upper = lower * 2
            mathematically_nearest = (
                lower if requested - lower < upper - requested else upper
            )
            if nearest != mathematically_nearest:
                return self._invalid(
                    f"installed Stingray {stingray.__version__} "
                    f"returned {nearest} for value {requested}, but the nearest power "
                    f"of two is {mathematically_nearest}. The result is withheld rather "
                    "than bypassing the public API; use a value for which the installed "
                    "helper is correct or upgrade Stingray."
                )
            delta = nearest - requested
            changed = nearest != requested
            warnings = []
            if changed:
                warnings.append(
                    f"Value changed by {delta:.12g} ({delta / requested * 100:.6g}%)."
                )
            data = {
                "requested_value": requested,
                "nearest_power_of_two": nearest,
                "delta": delta,
                "fractional_change": delta / requested,
                "changed": changed,
                "units": "dimensionless",
                "provenance": operation_provenance(
                    "nearest_power_of_two",
                    input_source={"kind": "parameters"},
                    parameters={"value": requested},
                ),
            }
            return self._success(data, "Nearest power of two calculated", warnings)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "nearest-power-of-two calculation")

    def adjust_segment_size(
        self,
        segment_size: Any,
        dt: Any,
        *,
        tolerance: Any = 0.01,
    ) -> dict[str, Any]:
        """Adjust a segment to an integer number of samples using Stingray."""

        try:
            requested, error = _finite_scalar(
                segment_size,
                "segment_size",
                minimum=0.0,
                minimum_inclusive=False,
            )
            if error:
                return self._invalid(error)
            sample_time, error = _finite_scalar(
                dt, "dt", minimum=0.0, minimum_inclusive=False
            )
            if error:
                return self._invalid(error)
            rounding_tolerance, error = _finite_scalar(
                tolerance,
                "tolerance",
                minimum=0.0,
                maximum=1.0,
                maximum_inclusive=False,
            )
            if error:
                return self._invalid(error)
            assert requested is not None and sample_time is not None
            assert rounding_tolerance is not None
            if requested < sample_time:
                return self._invalid("segment_size must be at least one dt")
            requested_samples = requested / sample_time
            if (
                not math.isfinite(requested_samples)
                or requested_samples > MAX_FFT_SAMPLES
            ):
                return self._invalid(
                    f"segment would contain {requested_samples:,.0f} samples; "
                    f"the cap is {MAX_FFT_SAMPLES:,}"
                )

            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                adjusted, sample_count = fix_segment_size_to_integer_samples(
                    requested,
                    sample_time,
                    tolerance=rounding_tolerance,
                )
            adjusted = float(adjusted)
            sample_count = int(sample_count)
            if (
                not math.isfinite(adjusted)
                or adjusted <= 0.0
                or sample_count <= 0
                or sample_count > MAX_FFT_SAMPLES
            ):
                return self._invalid(
                    "installed Stingray returned a non-finite or invalid adjusted "
                    "segment size; the result was withheld"
                )
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                reconstructed_size = sample_count * sample_time
            if (
                not math.isfinite(reconstructed_size)
                or reconstructed_size <= 0.0
                or reconstructed_size != adjusted
            ):
                return self._invalid(
                    "the adjusted segment size does not reconstruct from its sample "
                    "count and dt within the finite float range; the result was withheld"
                )
            delta = adjusted - requested
            changed = not math.isclose(adjusted, requested, rel_tol=1e-12, abs_tol=0.0)
            warnings = []
            if changed:
                warnings.append(
                    f"Segment size changed by {delta:.12g} "
                    f"({delta / requested * 100:.6g}%)."
                )
            parameters = {
                "segment_size": requested,
                "dt": sample_time,
                "tolerance": rounding_tolerance,
            }
            data = {
                "requested_segment_size": requested,
                "adjusted_segment_size": adjusted,
                "sample_count": sample_count,
                "delta": delta,
                "fractional_change": delta / requested,
                "changed": changed,
                "units": "same time units as segment_size and dt",
                "provenance": operation_provenance(
                    "fix_segment_size_to_integer_samples",
                    input_source={"kind": "parameters"},
                    parameters=parameters,
                ),
            }
            return self._success(
                data, "Segment size adjusted to whole samples", warnings
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "segment-size adjustment")

    def poisson_errors(self, counts: Iterable[Any]) -> dict[str, Any]:
        """Calculate Stingray's one-sigma symmetrized frequentist Poisson errors."""

        try:
            count_array, error = validate_finite_array(
                counts,
                label="counts",
                min_size=1,
            )
            if error:
                return self._invalid(error)
            assert count_array is not None
            negative = np.flatnonzero(count_array < 0)
            if negative.size:
                return self._invalid(f"counts[{int(negative[0])}] must be non-negative")
            noninteger = np.flatnonzero(count_array != np.floor(count_array))
            if noninteger.size:
                return self._invalid(
                    f"counts[{int(noninteger[0])}] must be an integer Poisson count"
                )
            maximum = int(np.max(count_array))
            if maximum > MAX_POISSON_LOOKUP_COUNT:
                return self._invalid(
                    f"largest count is {maximum:,}; Stingray's lookup allocation is "
                    f"capped at {MAX_POISSON_LOOKUP_COUNT:,}"
                )

            integer_counts = count_array.astype(np.int64)
            warning_list: list[str] = []
            with collect_warnings(warning_list):
                errors = poisson_symmetrical_errors(integer_counts)
            data = {
                "counts": integer_counts,
                "symmetric_error": errors,
                "confidence_sigma": 1.0,
                "units": {
                    "counts": "count",
                    "symmetric_error": "count",
                    "confidence_sigma": "standard deviations",
                },
                "assumptions": (
                    "Counts are independent Poisson observations. Stingray averages "
                    "the absolute lower and upper frequentist-confidence offsets to "
                    "report one approximately symmetric one-sigma error."
                ),
                "plot_preview": _named_preview(
                    ["counts", "symmetric_error"], integer_counts, errors
                ),
                "provenance": operation_provenance(
                    "poisson_symmetrical_errors",
                    input_source={"kind": "pasted_values"},
                    parameters={"confidence_sigma": 1.0},
                ),
            }
            return self._success(
                data, "Symmetric Poisson errors calculated", warning_list
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "Poisson error calculation")

    def standard_error(
        self,
        samples: Iterable[Iterable[Any]],
        *,
        mean: Optional[Iterable[Any]] = None,
    ) -> dict[str, Any]:
        """Calculate column-wise SEM for a bounded rectangular sample matrix."""

        try:
            if isinstance(samples, (str, bytes)):
                return self._invalid("samples must be a two-dimensional numeric matrix")

            # Enforce the total-cell cap while materializing iterables, before
            # NumPy allocates a dense matrix. Per-axis Pydantic limits alone do
            # not constrain the product of nested row and column counts, and
            # direct service callers may provide generators.
            prepared_rows: list[list[Any]] = []
            total_cells = 0
            try:
                sample_rows = iter(samples)
            except TypeError:
                return self._invalid("samples must be a two-dimensional numeric matrix")

            for row_index, row in enumerate(sample_rows):
                if row_index >= MAX_MATRIX_CELLS:
                    return self._invalid(
                        f"samples exceeds the cap of {MAX_MATRIX_CELLS:,} total cells"
                    )
                if isinstance(row, (str, bytes)):
                    return self._invalid(f"samples[{row_index}] must be a numeric row")
                try:
                    row_values = iter(row)
                except TypeError:
                    return self._invalid(f"samples[{row_index}] must be a numeric row")

                prepared_row: list[Any] = []
                for column_index, value in enumerate(row_values):
                    if total_cells >= MAX_MATRIX_CELLS:
                        return self._invalid(
                            f"samples exceeds the cap of {MAX_MATRIX_CELLS:,} total cells"
                        )
                    if isinstance(
                        value,
                        (bool, np.bool_, str, bytes, complex, np.complexfloating),
                    ):
                        return self._invalid(
                            f"samples[{row_index}][{column_index}] must be a finite real number"
                        )
                    prepared_row.append(value)
                    total_cells += 1
                prepared_rows.append(prepared_row)

            try:
                matrix = np.asarray(prepared_rows, dtype=float)
            except (TypeError, ValueError, OverflowError) as exc:
                return self._invalid(
                    f"samples must be a rectangular numeric matrix ({exc})"
                )
            if matrix.ndim != 2:
                return self._invalid("samples must be a two-dimensional matrix")
            rows, columns = matrix.shape
            if rows < 2:
                return self._invalid("samples must contain at least two rows")
            if columns < 1:
                return self._invalid("samples must contain at least one column")
            if matrix.size > MAX_MATRIX_CELLS:
                return self._invalid(
                    f"samples contains {matrix.size:,} cells; the cap is "
                    f"{MAX_MATRIX_CELLS:,}"
                )
            bad = np.argwhere(~np.isfinite(matrix))
            if bad.size:
                row, column = (int(v) for v in bad[0])
                return self._invalid(f"samples[{row}][{column}] must be finite")

            # Column-wise homogeneous scaling keeps both the arithmetic mean and
            # Stingray's squared deviations representable at extreme magnitudes.
            column_scales = np.max(np.abs(matrix), axis=0)
            column_scales = np.where(column_scales > 0.0, column_scales, 1.0)
            normalized_matrix = matrix / column_scales
            normalized_calculated_mean = np.mean(normalized_matrix, axis=0)
            calculated_mean, output_error = _restore_scaled_output(
                normalized_calculated_mean,
                1.0,
                label="normalized arithmetic sample mean",
            )
            if output_error:
                return self._invalid(output_error)
            assert calculated_mean is not None
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                calculated_mean = calculated_mean * column_scales
            if not np.all(np.isfinite(calculated_mean)):
                return self._invalid(
                    "column-wise arithmetic sample mean is outside the finite float "
                    "range; the result was withheld"
                )
            mean_source = "calculated_arithmetic_mean"
            warning_list: list[str] = []
            if mean is None:
                reference_mean = calculated_mean
            else:
                reference_mean, error = validate_finite_array(
                    mean,
                    label="mean",
                    min_size=columns,
                    max_size=columns,
                )
                if error:
                    return self._invalid(error)
                assert reference_mean is not None
                if reference_mean.shape != (columns,):
                    return self._invalid(
                        f"mean must contain exactly {columns} values, one per column"
                    )
                mean_source = "provided"
                if not np.allclose(
                    reference_mean,
                    calculated_mean,
                    rtol=1e-10,
                    atol=1e-12,
                ):
                    return self._invalid(
                        "mean must match the column-wise arithmetic sample mean; "
                        "omit it to have the service calculate the mean"
                    )

            normalized_reference_mean = reference_mean / column_scales
            with collect_warnings(warning_list):
                normalized_errors = stingray_standard_error(
                    normalized_matrix,
                    normalized_reference_mean,
                )
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                errors = np.asarray(normalized_errors, dtype=float) * column_scales
            underflowed = (np.asarray(normalized_errors) != 0.0) & (errors == 0.0)
            if not np.all(np.isfinite(errors)) or np.any(underflowed):
                return self._invalid(
                    "standard-error output is outside the finite float range; "
                    "the result was withheld"
                )
            column_index = np.arange(columns, dtype=int)
            parameters = {
                "rows": rows,
                "columns": columns,
                "mean_source": mean_source,
            }
            data = {
                "mean": reference_mean,
                "calculated_sample_mean": calculated_mean,
                "standard_error": errors,
                "sample_count": rows,
                "column_count": columns,
                "mean_source": mean_source,
                "units": {
                    "mean": "same as input samples",
                    "calculated_sample_mean": "same as input samples",
                    "standard_error": "same as input samples",
                    "sample_count": "samples",
                    "column_count": "columns",
                },
                "assumptions": (
                    "Rows are independent samples of the same column-wise quantities; "
                    "the calculation uses sample variance with n-1 degrees of freedom "
                    "and divides it by n before taking the square root."
                ),
                "plot_preview": _named_preview(
                    ["column_index", "mean", "standard_error"],
                    column_index,
                    reference_mean,
                    errors,
                ),
                "provenance": operation_provenance(
                    "standard_error",
                    input_source={"kind": "pasted_matrix"},
                    parameters=parameters,
                    numeric_conditioning={
                        "homogeneous_column_scales": column_scales,
                    },
                ),
            }
            return self._success(
                data, "Column-wise standard errors calculated", warning_list
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "standard-error calculation")

    def equal_count_ranges(
        self,
        *,
        n_ranges: Any,
        energies: Optional[Iterable[Any]] = None,
        event_list_name: Optional[str] = None,
        energy_min: Optional[Any] = None,
        energy_max: Optional[Any] = None,
        energy_unit: str = "keV",
    ) -> dict[str, Any]:
        """Create approximately equal-count energy ranges from one exact source."""

        try:
            has_values = energies is not None
            has_event = event_list_name is not None
            if has_values == has_event:
                return self._invalid(
                    "provide exactly one energy source: energies or event_list_name"
                )

            if not isinstance(energy_unit, str) or not energy_unit.strip():
                return self._invalid("energy_unit must be a non-empty unit label")
            if energy_unit != energy_unit.strip() or len(energy_unit) > 32:
                return self._invalid(
                    "energy_unit must be at most 32 characters with no surrounding whitespace"
                )

            source: dict[str, Any]
            source_snapshot = False
            if has_event:
                if not isinstance(event_list_name, str) or not event_list_name:
                    return self._invalid("event_list_name must be a non-empty string")
                if energy_unit != "keV":
                    return self._invalid(
                        "loaded EventList.energy values use keV by the public Stingray "
                        "contract; energy_unit must be 'keV' for this source"
                    )
                event_list = self.state.copy_event_data(
                    event_list_name,
                    max_events=MAX_ARRAY_INPUT,
                    max_cells=MAX_STATE_SNAPSHOT_CELLS,
                    max_bytes=MAX_STATE_SNAPSHOT_BYTES,
                )
                if event_list is None:
                    return self._invalid(f"EventList '{event_list_name}' was not found")
                source_snapshot = True
                event_energies = getattr(event_list, "energy", None)
                if event_energies is None:
                    return self._invalid(
                        f"EventList '{event_list_name}' has no energy data"
                    )
                energy_array, error = validate_finite_array(
                    event_energies,
                    label=f"EventList '{event_list_name}' energy",
                    min_size=2,
                )
                source = {"kind": "event_list", "name": event_list_name}
                # Stingray's public EventList contract defines energy in keV.
                energy_unit = "keV"
            else:
                energy_array, error = validate_finite_array(
                    energies,
                    label="energies",
                    min_size=2,
                )
                source = {"kind": "pasted_values"}
            if error:
                return self._invalid(error)
            assert energy_array is not None

            range_count, error = _bounded_integer(
                n_ranges,
                "n_ranges",
                minimum=1,
                maximum=MAX_ENERGY_RANGES,
            )
            if error:
                return self._invalid(error)
            assert range_count is not None

            lower: Optional[float] = None
            upper: Optional[float] = None
            if energy_min is not None:
                lower, error = _finite_scalar(energy_min, "energy_min")
                if error:
                    return self._invalid(error)
            if energy_max is not None:
                upper, error = _finite_scalar(energy_max, "energy_max")
                if error:
                    return self._invalid(error)
            effective_lower = float(np.min(energy_array)) if lower is None else lower
            effective_upper = float(np.max(energy_array)) if upper is None else upper
            if effective_lower >= effective_upper:
                return self._invalid("energy_min must be smaller than energy_max")

            selected_mask = (energy_array >= effective_lower) & (
                energy_array <= effective_upper
            )
            selected = energy_array[selected_mask]
            if selected.size < range_count:
                return self._invalid(
                    f"only {selected.size:,} energies fall in the requested range; "
                    f"at least {range_count:,} are required for {range_count:,} bins"
                )

            warning_list: list[str] = []
            with collect_warnings(warning_list):
                edges = np.asarray(
                    equal_count_energy_ranges(
                        energy_array,
                        range_count,
                        emin=lower,
                        emax=upper,
                    ),
                    dtype=float,
                )
            if edges.shape != (range_count + 1,):
                return self._invalid(
                    "Stingray returned an unexpected energy-edge shape"
                )
            if not np.all(np.isfinite(edges)):
                return self._invalid("Stingray returned non-finite energy edges")
            duplicate = np.flatnonzero(np.diff(edges) <= 0)
            if duplicate.size:
                return self._invalid(
                    "the energy distribution cannot form the requested number of "
                    "positive-width equal-count ranges; reduce n_ranges"
                )

            counts, _ = np.histogram(selected, bins=edges)
            sorted_selected = np.sort(selected)
            ranks = np.arange(sorted_selected.size, dtype=int)
            parameters = {
                "n_ranges": range_count,
                "energy_min": lower,
                "energy_max": upper,
                "energy_unit": energy_unit,
            }
            data = {
                "bin_edges": edges,
                "counts": counts,
                "n_ranges": range_count,
                "selected_count": int(selected.size),
                "excluded_count": int(energy_array.size - selected.size),
                "energy_min": float(edges[0]),
                "energy_max": float(edges[-1]),
                "energy_unit": energy_unit,
                "plot_preview": _named_preview(
                    ["rank", "energy"], ranks, sorted_selected
                ),
                "provenance": operation_provenance(
                    "equal_count_energy_ranges",
                    input_source=source,
                    parameters=parameters,
                    source_snapshot=source_snapshot,
                ),
            }
            return self._success(
                data, "Equal-count energy ranges calculated", warning_list
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self.handle_error(exc, "equal-count energy-range calculation")


__all__ = [
    "LINEAR_REBIN_NEEDS_VARIANCE_INPUT",
    "MAX_BASELINE_ITERATIONS",
    "MAX_ENERGY_RANGES",
    "MAX_FFT_SAMPLES",
    "MAX_POISSON_LOOKUP_COUNT",
    "MiscService",
    "SUPPORTED_WINDOWS",
]
