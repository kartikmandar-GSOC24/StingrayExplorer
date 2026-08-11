"""Tests for the curated Miscellaneous Utilities service and route contract."""

from __future__ import annotations

import inspect
import json
import warnings

import numpy as np
import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError
from stingray import EventList
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
    standard_error,
)

import routes.misc_routes as misc_routes
import services.misc_service as misc_module
from routes.misc_routes import LinearRebinRequest, PoissonErrorRequest, WindowRequest
from services.misc_service import (
    LINEAR_REBIN_NEEDS_VARIANCE_INPUT,
    MAX_BASELINE_ITERATIONS,
    MAX_FFT_SAMPLES,
    MAX_POISSON_LOOKUP_COUNT,
    MiscService,
    SUPPORTED_WINDOWS,
)
from services.utility_helpers import MAX_ARRAY_INPUT, MAX_EXACT_OUTPUT, MAX_MATRIX_CELLS


@pytest.fixture()
def service(state_manager):
    return MiscService(state_manager)


def assert_json_safe(result):
    """The production JSON encoder rejects NaN/Infinity, so tests do too."""

    json.dumps(result, allow_nan=False)


def test_capabilities_are_derived_from_installed_stingray(service):
    result = service.capabilities()
    assert result["success"], result
    data = result["data"]
    assert data["window_types"] == [
        "uniform",
        "parzen",
        "hamming",
        "hanning",
        "triangular",
        "welch",
        "blackmann",
        "flat-top",
    ]
    assert tuple(data["window_types"]) == SUPPORTED_WINDOWS
    assert data["rebin"]["linear_uncertainty_workaround_required"] is True
    assert data["limits"]["max_array_values"] == MAX_ARRAY_INPUT
    assert data["limits"]["max_matrix_cells"] == MAX_MATRIX_CELLS
    assert data["provenance"]["stingray_version"] == "2.2.10"
    assert_json_safe(result)


def test_window_capabilities_remain_derivable_without_installed_source(monkeypatch):
    def unavailable_source(_function):
        raise OSError("frozen module has no source file")

    monkeypatch.setattr(misc_module.inspect, "getsource", unavailable_source)

    assert misc_module._derive_supported_windows() == SUPPORTED_WINDOWS


def test_numeric_success_payloads_state_units(service):
    linear = service.linear_rebin([0.5, 1.5], [1.0, 2.0], 2.0, dx=1.0)
    logarithmic = service.logarithmic_rebin(
        [1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0], 0.1, dx=1.0
    )
    baseline = service.estimate_baseline(np.arange(8.0), np.linspace(1.0, 2.0, 8))
    window = service.generate_window(4, "uniform")
    poisson = service.poisson_errors([0, 4])
    standard = service.standard_error([[1.0, 2.0], [3.0, 4.0]])

    for result in (linear, logarithmic, baseline, window, poisson, standard):
        assert result["success"], result
        assert result["data"]["units"]
        assert all(
            isinstance(value, str) and value
            for value in result["data"]["units"].values()
        )


@pytest.mark.parametrize(
    "method,analytic_error",
    [("sum", 2.0 * np.sqrt(2.0)), ("mean", np.sqrt(2.0))],
)
def test_linear_rebin_matches_stingray_bins_and_analytic_uncertainty(
    service, method, analytic_error
):
    x = np.arange(0.5, 8.5, 1.0)
    y = np.arange(1.0, 9.0)
    sigma = np.full(x.size, 2.0)

    result = service.linear_rebin(
        x,
        y,
        2.0,
        y_error=sigma,
        method=method,
        dx=1.0,
    )
    assert result["success"], result
    data = result["data"]

    # 2.2.10 expects variance input due to the bug fixed by upstream PR #953.
    expected = rebin_data(x, y, 2.0, yerr=sigma**2, method=method, dx=1.0)
    np.testing.assert_allclose(data["rebinned"]["x"], expected[0])
    np.testing.assert_allclose(data["rebinned"]["y"], expected[1])
    np.testing.assert_allclose(data["rebinned"]["y_error"], expected[2])
    np.testing.assert_allclose(data["rebinned"]["y_error"], analytic_error)
    assert data["provenance"]["uncertainty_compatibility"]["workaround_applied"]
    assert any("PR #953" in warning for warning in data["warnings"])
    assert LINEAR_REBIN_NEEDS_VARIANCE_INPUT
    assert_json_safe(result)


def test_linear_rebin_rejects_fractional_overlap_uncertainties(service):
    result = service.linear_rebin(
        np.arange(0.5, 8.5),
        np.ones(8),
        2.5,
        y_error=np.full(8, 2.0),
        dx=1.0,
    )
    assert not result["success"]
    assert "integer dx_new / dx" in result["message"]
    assert "fractional-overlap" in result["message"]


def test_linear_rebin_rejects_uncertainties_for_nonuniform_x(service):
    result = service.linear_rebin(
        [0.5, 1.5, 3.0, 4.0],
        [1.0, 1.0, 1.0, 1.0],
        3.0,
        y_error=[1.0, 1.0, 1.0, 1.0],
    )
    assert not result["success"]
    assert "uniformly spaced" in result["message"]


@pytest.mark.parametrize("supplied_dx", [0.1, None])
def test_linear_rebin_accepts_uniform_grid_quantized_by_large_offset(
    service, supplied_dx
):
    origin = 1e12
    dx = 0.1
    x = origin + np.arange(20) * dx
    y = np.arange(1.0, 21.0)
    sigma = np.full(x.size, 0.1)

    # At this absolute scale, one ULP is larger than the apparent variation
    # between the two adjacent spacings, despite the scientifically uniform grid.
    assert np.ptp(np.diff(x)) > 1e-4
    assert np.spacing(origin) >= np.ptp(np.diff(x))

    result = service.linear_rebin(
        x,
        y,
        0.2,
        y_error=sigma,
        method="sum",
        dx=supplied_dx,
    )
    assert result["success"], result

    canonical_x = np.arange(x.size, dtype=float) * dx
    expected = rebin_data(
        canonical_x,
        y,
        0.2,
        yerr=sigma**2,
        method="sum",
        dx=dx,
    )
    data = result["data"]
    np.testing.assert_allclose(data["rebinned"]["x"], expected[0] + origin)
    np.testing.assert_allclose(data["rebinned"]["y"], expected[1])
    np.testing.assert_allclose(data["rebinned"]["y_error"], expected[2])
    assert data["provenance"]["coordinate_processing"] == {
        "origin_relative_stingray_input": True,
        "uniform_grid_reexpressed": True,
        "ulp_accommodation_used": True,
    }
    assert any("floating-point ULPs" in warning for warning in data["warnings"])
    assert_json_safe(result)


def test_linear_rebin_still_rejects_real_jitter_on_large_offset(service):
    x = 1e12 + np.arange(20) * 0.1
    x[10] += 0.01
    result = service.linear_rebin(
        x,
        np.ones(x.size),
        0.2,
        y_error=np.full(x.size, 0.1),
        dx=0.1,
    )
    assert not result["success"]
    assert "uniformly spaced" in result["message"]


@pytest.mark.parametrize("sample_count", [6, 12])
def test_linear_rebin_preserves_every_complete_uniform_bin(service, sample_count):
    x = np.arange(sample_count, dtype=float) * 0.1
    y = np.arange(sample_count, dtype=float)

    result = service.linear_rebin(x, y, 0.2, method="sum", dx=0.1)

    assert result["success"], result
    data = result["data"]
    expected = rebin_data(
        np.arange(sample_count, dtype=float),
        y,
        2.0,
        method="sum",
        dx=1.0,
    )
    np.testing.assert_allclose(data["rebinned"]["y"], expected[1])
    np.testing.assert_allclose(data["rebinned"]["y"], y.reshape(-1, 2).sum(axis=1))
    assert sum(data["rebinned"]["y"]) == pytest.approx(sum(y))
    assert len(data["rebinned"]["y"]) == sample_count // 2
    assert any("float-modulo" in warning for warning in data["warnings"])


def test_linear_rebin_without_uncertainties_allows_fractional_bins(service):
    x = np.arange(0.5, 8.5)
    y = np.arange(8.0)
    result = service.linear_rebin(x, y, 2.5, method="mean", dx=1.0)
    expected = rebin_data(x, y, 2.5, method="mean", dx=1.0)
    assert result["success"], result
    assert result["data"]["rebinned"]["y_error"] is None
    np.testing.assert_allclose(result["data"]["rebinned"]["x"], expected[0])
    np.testing.assert_allclose(result["data"]["rebinned"]["y"], expected[1])


def test_linear_rebin_scales_extreme_finite_values_without_overflow_or_underflow(
    service,
):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = service.linear_rebin(
            np.arange(4.0),
            np.full(4, 1e308),
            2.0,
            method="mean",
            dx=1.0,
            y_error=np.full(4, 1e-200),
        )

    assert result["success"], result
    np.testing.assert_allclose(result["data"]["rebinned"]["y"], 1e308)
    np.testing.assert_allclose(
        result["data"]["rebinned"]["y_error"],
        np.sqrt(2.0) / 2.0 * 1e-200,
        rtol=1e-12,
        atol=0.0,
    )
    assert not [item for item in caught if issubclass(item.category, RuntimeWarning)]
    assert_json_safe(result)


def test_linear_rebin_scales_large_single_sample_uncertainty(service):
    result = service.linear_rebin(
        [0.0, 1.0],
        [1.0, 2.0],
        1.0,
        method="mean",
        dx=1.0,
        y_error=[1e308, 1e308],
    )

    assert result["success"], result
    np.testing.assert_allclose(result["data"]["rebinned"]["y_error"], 1e308)
    assert_json_safe(result)


def test_linear_rebin_fails_closed_when_true_sum_exceeds_float_range(service):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = service.linear_rebin(
            [0.0, 1.0],
            [1e308, 1e308],
            2.0,
            method="sum",
            dx=1.0,
        )

    assert result["success"] is False
    assert result["error"] is None
    assert "outside the finite float range" in result["message"]
    assert not [item for item in caught if issubclass(item.category, RuntimeWarning)]


@pytest.mark.parametrize("dx_new", [0.3, 1e308])
def test_linear_rebin_rejects_target_wider_than_covered_input(service, dx_new):
    result = service.linear_rebin(
        [0.0, 0.1],
        [1.0, 2.0],
        dx_new,
        method="sum",
        dx=0.1,
    )

    assert result["success"] is False
    assert result["error"] is None
    assert "no complete output bin fits" in result["message"]


def test_logarithmic_rebin_matches_stingray_and_labels_errors_as_mean(service):
    x = np.arange(1.0, 101.0)
    y = np.linspace(2.0, 5.0, x.size)
    sigma = np.full(x.size, 2.0)
    result = service.logarithmic_rebin(
        x,
        y,
        0.1,
        y_error=sigma,
        dx=1.0,
    )
    assert result["success"], result
    expected = rebin_data_log(x, y, 0.1, y_err=sigma, dx=1.0)
    data = result["data"]
    np.testing.assert_allclose(data["rebinned"]["x"], expected[0])
    np.testing.assert_allclose(data["rebinned"]["y"], expected[1])
    np.testing.assert_allclose(data["rebinned"]["y_error"], expected[2])
    np.testing.assert_array_equal(data["rebinned"]["samples_per_bin"], expected[3])
    assert data["method"] == "mean"
    assert "sqrt(sum(sigma_i^2)) / N" in data["error_semantics"]
    assert_json_safe(result)


@pytest.mark.parametrize("uncertainty", [1e-200, 1e308])
def test_logarithmic_rebin_scales_extreme_finite_values(service, uncertainty):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = service.logarithmic_rebin(
            [1.0, 2.0],
            [1e308, 1e308],
            0.1,
            y_error=[uncertainty, uncertainty],
            dx=1.0,
        )

    assert result["success"], result
    np.testing.assert_allclose(result["data"]["rebinned"]["y"], 1e308)
    np.testing.assert_allclose(
        result["data"]["rebinned"]["y_error"],
        uncertainty,
        rtol=1e-12,
        atol=0.0,
    )
    assert not [item for item in caught if issubclass(item.category, RuntimeWarning)]
    assert_json_safe(result)


def test_logarithmic_rebin_rejects_non_growing_edge_before_public_call(
    service, monkeypatch
):
    origin = 1e8
    dx = 2.0 * np.spacing(origin)
    x = origin + np.arange(10) * dx

    def must_not_run(*args, **kwargs):
        raise AssertionError("non-progressing public rebin must be rejected first")

    monkeypatch.setattr(misc_module, "rebin_data_log", must_not_run)
    result = service.logarithmic_rebin(x, np.arange(10.0), 0.1, dx=dx)

    assert result["success"] is False
    assert result["error"] is None
    assert "cannot grow" in result["message"]
    assert "non-progressing edge loop" in result["message"]


def test_baseline_matches_public_stingray_api(service):
    x = np.linspace(0.0, 10.0, 101)
    y = 4.0 + 0.2 * x + np.exp(-((x - 5.0) ** 2) / 0.2)
    result = service.estimate_baseline(
        x,
        y,
        lam=1e5,
        asymmetry=0.01,
        iterations=12,
    )
    assert result["success"], result
    expected_corrected, expected_baseline = baseline_als(
        x,
        y,
        lam=1e5,
        p=0.01,
        niter=12,
        return_baseline=True,
    )
    np.testing.assert_allclose(result["data"]["baseline"], expected_baseline)
    np.testing.assert_allclose(result["data"]["corrected"], expected_corrected)
    assert_json_safe(result)


def test_baseline_scales_large_finite_constant_without_nulls(service):
    result = service.estimate_baseline(
        np.arange(8.0),
        np.full(8, 1e308),
        lam=1e5,
        asymmetry=0.01,
        iterations=12,
    )

    assert result["success"], result
    data = result["data"]
    assert np.all(np.isfinite(data["baseline"]))
    assert np.all(np.isfinite(data["corrected"]))
    expected_corrected, expected_baseline = baseline_als(
        np.arange(8.0),
        np.ones(8),
        lam=1e5,
        p=0.01,
        niter=12,
        return_baseline=True,
    )
    np.testing.assert_allclose(data["baseline"], expected_baseline * 1e308)
    np.testing.assert_allclose(data["corrected"], expected_corrected * 1e308)
    assert_json_safe(result)


@pytest.mark.parametrize("window_type", SUPPORTED_WINDOWS)
def test_every_reported_window_matches_stingray(service, window_type):
    result = service.generate_window(32, window_type)
    assert result["success"], result
    np.testing.assert_allclose(result["data"]["window"], create_window(32, window_type))
    assert result["data"]["summary"]["energy"] >= 0
    assert_json_safe(result)


def test_short_zero_sum_window_is_json_safe_and_explained(service):
    result = service.generate_window(2, "hanning")
    assert result["success"], result
    assert result["data"]["summary"]["equivalent_noise_bandwidth_bins"] is None
    assert any("undefined" in warning for warning in result["data"]["warnings"])
    assert_json_safe(result)


def test_nonfinite_stingray_output_becomes_null_with_warning(service, monkeypatch):
    monkeypatch.setattr(
        misc_module,
        "create_window",
        lambda count, window_type: np.asarray([1.0, np.nan]),
    )
    result = service.generate_window(2, "uniform")
    assert result["success"], result
    assert result["data"]["window"] == [1.0, None]
    assert any("non-finite" in warning for warning in result["data"]["warnings"])
    assert_json_safe(result)


def test_sampling_helpers_match_public_stingray_functions(service):
    bin_result = service.calculate_optimal_bin_time(10.0, 0.3)
    assert bin_result["success"], bin_result
    expected_bin = optimal_bin_time(10.0, 0.3)
    assert bin_result["data"]["adjusted_bin_time"] == pytest.approx(expected_bin)
    assert bin_result["data"]["sample_count"] == 64
    assert bin_result["data"]["changed"]

    power_result = service.calculate_nearest_power_of_two(65)
    assert power_result["success"], power_result
    assert power_result["data"]["nearest_power_of_two"] == nearest_power_of_two(65)
    assert power_result["data"]["delta"] == -1
    assert power_result["data"]["units"] == "dimensionless"

    segment_result = service.adjust_segment_size(0.999, 0.1, tolerance=0.01)
    assert segment_result["success"], segment_result
    expected_segment, expected_samples = fix_segment_size_to_integer_samples(
        0.999, 0.1, tolerance=0.01
    )
    assert segment_result["data"]["adjusted_segment_size"] == expected_segment
    assert segment_result["data"]["sample_count"] == expected_samples
    assert segment_result["data"]["changed"]

    for result in (bin_result, power_result, segment_result):
        assert_json_safe(result)


@pytest.mark.parametrize(
    "fft_length,proposed_bin_time",
    [(1e-320, 1e-322), (5e-323, 1e-323)],
)
def test_optimal_bin_time_fails_closed_for_subnormal_non_power_of_two_count(
    service, fft_length, proposed_bin_time
):
    result = service.calculate_optimal_bin_time(fft_length, proposed_bin_time)

    assert result["success"] is False
    assert result["error"] is None
    assert "power-of-two FFT sample count" in result["message"]


def test_segment_size_fails_closed_when_upward_rounding_overflows(service):
    maximum = np.finfo(float).max
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = service.adjust_segment_size(
            maximum,
            maximum / 1.995,
            tolerance=0.01,
        )

    assert result["success"] is False
    assert result["error"] is None
    assert "non-finite or invalid adjusted segment size" in result["message"]
    assert not [item for item in caught if issubclass(item.category, RuntimeWarning)]


def test_poisson_errors_match_public_stingray_api(service):
    counts = np.asarray([0, 1, 2, 10, 100])
    result = service.poisson_errors(counts)
    assert result["success"], result
    np.testing.assert_allclose(
        result["data"]["symmetric_error"], poisson_symmetrical_errors(counts)
    )
    assert "frequentist-confidence" in result["data"]["assumptions"]
    assert_json_safe(result)


def test_standard_error_matches_stingray_and_analytic_sem(service):
    samples = np.asarray([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    mean = np.mean(samples, axis=0)
    result = service.standard_error(samples)
    assert result["success"], result
    expected = standard_error(samples, mean)
    np.testing.assert_allclose(result["data"]["standard_error"], expected)
    np.testing.assert_allclose(
        result["data"]["standard_error"], np.full(2, np.sqrt(4.0 / 3.0))
    )
    np.testing.assert_allclose(result["data"]["mean"], mean)
    assert result["data"]["mean_source"] == "calculated_arithmetic_mean"
    assert_json_safe(result)


def test_standard_error_rejects_non_mean_reference(service):
    result = service.standard_error([[1.0, 2.0], [3.0, 4.0]], mean=[0.0, 0.0])
    assert not result["success"]
    assert "arithmetic sample mean" in result["message"]


def test_standard_error_scales_large_identical_samples(service):
    result = service.standard_error([[1e308], [1e308]])

    assert result["success"], result
    np.testing.assert_allclose(result["data"]["mean"], [1e308])
    np.testing.assert_array_equal(result["data"]["standard_error"], [0.0])
    assert_json_safe(result)


def test_standard_error_scales_tiny_nonzero_samples(service):
    result = service.standard_error([[1e-200], [-1e-200]])

    assert result["success"], result
    np.testing.assert_array_equal(result["data"]["mean"], [0.0])
    np.testing.assert_allclose(
        result["data"]["standard_error"],
        [1e-200],
        rtol=1e-12,
        atol=0.0,
    )
    assert_json_safe(result)


def test_equal_count_pasted_energy_matches_stingray(service):
    energies = np.linspace(0.5, 10.0, 100)
    result = service.equal_count_ranges(n_ranges=5, energies=energies)
    assert result["success"], result
    data = result["data"]
    expected = equal_count_energy_ranges(energies, 5)
    np.testing.assert_allclose(data["bin_edges"], expected)
    expected_counts, _ = np.histogram(energies, bins=expected)
    np.testing.assert_array_equal(data["counts"], expected_counts)
    assert sum(data["counts"]) == 100
    assert data["energy_unit"] == "keV"
    assert data["provenance"]["input_source"] == {"kind": "pasted_values"}
    assert_json_safe(result)


def test_equal_count_event_energy_uses_snapshot_and_does_not_mutate_source(
    state_manager,
):
    times = np.arange(20.0)
    energies = np.linspace(1.0, 8.0, 20)
    events = EventList(time=times, energy=energies, gti=[[0.0, 20.0]])
    state_manager.add_event_data("science", events)
    stored = state_manager.get_event_data("science")
    time_before = stored.time.copy()
    energy_before = stored.energy.copy()
    time_identity = id(stored.time)
    energy_identity = id(stored.energy)

    result = MiscService(state_manager).equal_count_ranges(
        n_ranges=4,
        event_list_name="science",
    )
    assert result["success"], result
    assert result["data"]["energy_unit"] == "keV"
    assert result["data"]["provenance"]["source_snapshot"] is True
    np.testing.assert_array_equal(stored.time, time_before)
    np.testing.assert_array_equal(stored.energy, energy_before)
    assert id(stored.time) == time_identity
    assert id(stored.energy) == energy_identity


def test_equal_count_event_without_energy_is_rejected(state_manager):
    state_manager.add_event_data(
        "no-energy",
        EventList(time=np.arange(5.0), gti=[[0.0, 5.0]]),
    )
    result = MiscService(state_manager).equal_count_ranges(
        n_ranges=2,
        event_list_name="no-energy",
    )
    assert not result["success"]
    assert "no energy data" in result["message"]


def test_equal_count_missing_event_list_is_rejected(service):
    result = service.equal_count_ranges(n_ranges=2, event_list_name="missing")
    assert not result["success"]
    assert "was not found" in result["message"]


def test_event_energy_unit_cannot_be_silently_reinterpreted(state_manager):
    state_manager.add_event_data(
        "science",
        EventList(
            time=np.arange(5.0),
            energy=np.linspace(1.0, 5.0, 5),
            gti=[[0.0, 5.0]],
        ),
    )
    result = MiscService(state_manager).equal_count_ranges(
        n_ranges=2,
        event_list_name="science",
        energy_unit="MeV",
    )
    assert not result["success"]
    assert "must be 'keV'" in result["message"]


@pytest.mark.parametrize(
    "call,expected",
    [
        (lambda svc: svc.linear_rebin([0, 1], [1], 2), "same length"),
        (lambda svc: svc.linear_rebin([0, np.nan], [1, 2], 2), "x[1]"),
        (lambda svc: svc.linear_rebin([0, 0], [1, 2], 2), "strictly increasing"),
        (
            lambda svc: svc.linear_rebin([0, 1], [1, 2], 2, y_error=[1, -1]),
            "non-negative",
        ),
        (lambda svc: svc.logarithmic_rebin([0, 1], [1, 2], 0.1), "positive"),
        (lambda svc: svc.logarithmic_rebin([1, 2], [1, 2], 0), "factor"),
        (lambda svc: svc.estimate_baseline([0, 1], [1, 2]), "at least 3"),
        (
            lambda svc: svc.estimate_baseline([0, 1, 2], [1, 2, 3], asymmetry=1),
            "asymmetry",
        ),
        (
            lambda svc: svc.estimate_baseline(
                [0, 1, 2],
                [1, 2, 3],
                iterations=MAX_BASELINE_ITERATIONS + 1,
            ),
            "iterations",
        ),
        (lambda svc: svc.generate_window(1, "uniform"), "n_samples"),
        (lambda svc: svc.generate_window(8, "blackman"), "window_type"),
        (lambda svc: svc.calculate_optimal_bin_time(1, 2), "must not exceed"),
        (lambda svc: svc.calculate_nearest_power_of_two(1), "between 2"),
        (lambda svc: svc.calculate_nearest_power_of_two(3.5), "integer"),
        (
            lambda svc: svc.calculate_nearest_power_of_two(70),
            "result is withheld",
        ),
        (lambda svc: svc.adjust_segment_size(0.05, 0.1), "at least one dt"),
        (lambda svc: svc.poisson_errors([1, 2.5]), "integer Poisson"),
        (lambda svc: svc.poisson_errors([1, -1]), "non-negative"),
        (lambda svc: svc.standard_error([[1, 2]]), "at least two rows"),
        (
            lambda svc: svc.standard_error([[1, 2], [3, np.inf]]),
            "samples[1][1]",
        ),
        (
            lambda svc: svc.equal_count_ranges(n_ranges=2),
            "exactly one energy source",
        ),
        (
            lambda svc: svc.equal_count_ranges(
                n_ranges=2, energies=[1, 2], event_list_name="also"
            ),
            "exactly one energy source",
        ),
        (
            lambda svc: svc.equal_count_ranges(n_ranges=3, energies=[1, 2]),
            "at least 3",
        ),
        (
            lambda svc: svc.equal_count_ranges(n_ranges=2, energies=[1, 1, 1, 1]),
            "energy_min",
        ),
    ],
)
def test_invalid_domains_are_actionable(service, call, expected):
    result = call(service)
    assert not result["success"], result
    assert expected in result["message"]


def test_explicit_allocation_caps_reject_before_large_work(service):
    too_many = np.zeros(MAX_ARRAY_INPUT + 1)
    array_result = service.poisson_errors(too_many)
    assert not array_result["success"]
    assert "cap" in array_result["message"]

    lookup_result = service.poisson_errors([MAX_POISSON_LOOKUP_COUNT + 1])
    assert not lookup_result["success"]
    assert "lookup allocation" in lookup_result["message"]

    matrix = np.zeros((500, MAX_MATRIX_CELLS // 500 + 1))
    matrix_result = service.standard_error(matrix)
    assert not matrix_result["success"]
    assert "cells" in matrix_result["message"]

    fft_result = service.calculate_optimal_bin_time(1.0, 1.0 / (MAX_FFT_SAMPLES + 1))
    assert not fft_result["success"]
    assert "FFT" in fft_result["message"] and "cap" in fft_result["message"]

    rebin_result = service.linear_rebin(
        [0.0, 1.0],
        [1.0, 2.0],
        1e-9,
        dx=1e-9,
    )
    assert not rebin_result["success"]
    assert "allocate" in rebin_result["message"]


def test_exact_arrays_are_preserved_while_plot_preview_is_decimated(service):
    x = np.arange(0.5, 6001.5)
    y = np.sin(x)
    result = service.linear_rebin(x, y, 2.0, dx=1.0)
    assert result["success"], result
    original = result["data"]["original"]
    preview = result["data"]["plot_preview"]["original"]
    assert len(original["x"]) == 6001
    assert preview["source_points"] == 6001
    assert preview["stride"] == 2
    assert len(preview["values"]["x"]) == 3001
    assert_json_safe(result)


def test_route_models_reject_coercion_and_unknown_fields():
    with pytest.raises(ValidationError):
        LinearRebinRequest(
            x=[True, 1.0],
            y=[1.0, 2.0],
            dx_new=2.0,
        )
    with pytest.raises(ValidationError):
        WindowRequest(n_samples=8, window_type="uniform", arbitrary="nope")
    with pytest.raises(ValidationError):
        LinearRebinRequest(
            x=[0.0, np.nan],
            y=[1.0, 2.0],
            dx_new=2.0,
        )
    with pytest.raises(ValidationError):
        PoissonErrorRequest(counts=[0.0] * (MAX_ARRAY_INPUT + 1))


def test_every_misc_route_structurally_offloads_to_thread():
    api_routes = [
        route for route in misc_routes.router.routes if isinstance(route, APIRoute)
    ]
    assert {route.path for route in api_routes} == {
        "/capabilities",
        "/rebin/linear",
        "/rebin/logarithmic",
        "/baseline",
        "/window",
        "/sampling/optimal-bin-time",
        "/sampling/nearest-power-of-two",
        "/sampling/segment-size",
        "/errors/poisson",
        "/errors/standard",
        "/energy-ranges",
    }
    for route in api_routes:
        source = inspect.getsource(route.endpoint)
        assert "asyncio.to_thread" in source, f"{route.path} blocks the event loop"


@pytest.mark.asyncio
async def test_window_route_dispatches_through_to_thread(service, monkeypatch):
    calls = []

    async def fake_to_thread(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        return function(*args, **kwargs)

    monkeypatch.setattr(misc_routes.asyncio, "to_thread", fake_to_thread)
    result = await misc_routes.generate_window(
        WindowRequest(n_samples=8, window_type="hamming"),
        service,
    )
    assert result["success"], result
    assert len(calls) == 1
    assert calls[0][0] == service.generate_window


def test_limits_exported_by_capabilities_match_service_constants(service):
    limits = service.capabilities()["data"]["limits"]
    assert limits["max_exact_output_values"] == MAX_EXACT_OUTPUT
    assert limits["max_fft_samples"] == MAX_FFT_SAMPLES
    assert limits["max_poisson_count"] == MAX_POISSON_LOOKUP_COUNT
