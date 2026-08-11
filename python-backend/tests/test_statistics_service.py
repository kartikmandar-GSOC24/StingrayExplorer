"""Scientific, serialization, validation, and concurrency tests for statistics."""

from __future__ import annotations

import inspect
import json

import numpy as np
import pytest
from pydantic import ValidationError
from routes import statistics_routes
from routes.statistics_routes import (
    GaussianRequest,
    PdmEvaluateRequest,
    PdsEvaluateRequest,
    TrialRequest,
)
from services.statistics_service import MAX_COUNT_PARAMETER, StatisticsService
from stingray import stats as stingray_stats


@pytest.fixture()
def service(state_manager) -> StatisticsService:
    return StatisticsService(state_manager)


def _assert_success(result):
    assert result["success"], result
    assert set(result) == {"success", "data", "message", "error"}
    assert result["error"] is None
    assert isinstance(result["data"]["warnings"], list)
    assert result["data"]["provenance"]["stingray_version"] == "2.2.10"
    json.dumps(result, allow_nan=False)
    return result["data"]


def test_gaussian_probability_uses_stingray_one_sided_upper_tail(service):
    probability = 0.0013498980316301035
    data = _assert_success(
        service.gaussian_significance(
            probability=probability,
            sidedness="one-sided",
        )
    )

    expected = float(stingray_stats.equivalent_gaussian_Nsigma(probability))
    assert data["sigma"] == pytest.approx(expected)
    assert data["sigma"] == pytest.approx(3.0)
    assert data["effective_one_sided_probability"] == probability
    assert data["effective_one_sided_log_probability"] == pytest.approx(
        np.log(probability)
    )
    assert data["sidedness"] == "one-sided"
    assert data["tail"] == "upper"
    assert data["direction"] == "probability_to_gaussian_sigma"
    assert data["provenance"]["public_api_calls"] == [
        "stingray.stats.equivalent_gaussian_Nsigma"
    ]


def test_gaussian_two_sided_probability_splits_the_total_between_tails(service):
    total_probability = 0.002699796063260207
    data = _assert_success(
        service.gaussian_significance(
            probability=total_probability,
            sidedness="two-sided",
        )
    )

    one_tail = total_probability / 2.0
    expected = float(stingray_stats.equivalent_gaussian_Nsigma(one_tail))
    assert data["effective_one_sided_probability"] == pytest.approx(one_tail)
    assert data["effective_one_sided_log_probability"] == pytest.approx(
        np.log(total_probability) - np.log(2.0)
    )
    assert data["sigma"] == pytest.approx(expected)
    assert data["sigma"] == pytest.approx(3.0)


def test_gaussian_log_probability_supports_extreme_significance(service):
    log_probability = -1000.0
    data = _assert_success(
        service.gaussian_significance(
            log_probability=log_probability,
            sidedness="one-sided",
        )
    )

    expected = float(
        stingray_stats.equivalent_gaussian_Nsigma_from_logp(log_probability)
    )
    assert data["sigma"] == pytest.approx(expected)
    assert data["sigma"] == pytest.approx(44.6159802496772)
    assert data["effective_one_sided_probability"] == 0.0
    assert any("underflowed to 0.0" in warning for warning in data["warnings"])
    assert data["provenance"]["public_api_calls"] == [
        "stingray.stats.equivalent_gaussian_Nsigma_from_logp"
    ]


def test_gaussian_two_sided_log_probability_uses_half_each_tail(service):
    total_log_probability = float(np.log(0.002699796063260207))
    data = _assert_success(
        service.gaussian_significance(
            log_probability=total_log_probability,
            sidedness="two-sided",
        )
    )

    effective_log_probability = total_log_probability - float(np.log(2.0))
    expected = stingray_stats.equivalent_gaussian_Nsigma_from_logp(
        effective_log_probability
    )
    assert data["effective_one_sided_log_probability"] == pytest.approx(
        effective_log_probability
    )
    assert data["sigma"] == pytest.approx(float(expected))
    assert data["sigma"] == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("direction", "probability", "n_trials", "upstream"),
    [
        (
            "single-to-multi",
            0.0001,
            37,
            stingray_stats.p_multitrial_from_single_trial,
        ),
        (
            "multi-to-single",
            0.01,
            37,
            stingray_stats.p_single_trial_from_p_multitrial,
        ),
    ],
)
def test_trial_conversions_match_stingray(
    service, direction, probability, n_trials, upstream
):
    data = _assert_success(
        service.convert_trials(
            direction=direction,
            probability=probability,
            n_trials=n_trials,
        )
    )

    expected = float(upstream(probability, n_trials))
    assert data["output_probability"] == pytest.approx(expected)
    assert data["direction"] == direction
    assert data["n_trials"] == n_trials
    assert "independent" in data["independence_assumption"]


@pytest.mark.parametrize(
    ("direction", "probability"),
    [
        ("single-to-multi", 0.0),
        ("single-to-multi", 1.0),
        ("multi-to-single", 0.0),
    ],
)
def test_trial_conversion_supported_boundaries_match_stingray(
    service, direction, probability
):
    data = _assert_success(
        service.convert_trials(
            direction=direction,
            probability=probability,
            n_trials=7,
        )
    )
    with np.errstate(divide="ignore"):
        if direction == "single-to-multi":
            expected = stingray_stats.p_multitrial_from_single_trial(probability, 7)
        else:
            expected = stingray_stats.p_single_trial_from_p_multitrial(probability, 7)
    assert data["output_probability"] == float(expected)
    if probability == 0.0:
        assert any("divide by zero" in warning for warning in data["warnings"])


@pytest.mark.parametrize(
    ("method", "kwargs", "probability_call", "log_probability_call"),
    [
        (
            "evaluate_pds",
            {"power": 10.0, "n_trials": 3, "n_summed_spectra": 2, "n_rebin": 4},
            lambda values: stingray_stats.pds_probability(
                values["power"],
                ntrial=values["n_trials"],
                n_summed_spectra=values["n_summed_spectra"],
                n_rebin=values["n_rebin"],
            ),
            lambda values: stingray_stats.pds_logprobability(
                values["power"],
                ntrial=values["n_trials"],
                n_summed_spectra=values["n_summed_spectra"],
                n_rebin=values["n_rebin"],
            ),
        ),
        (
            "evaluate_z2",
            {"z2": 20.0, "harmonics": 3, "n_trials": 7, "n_summed_spectra": 2},
            lambda values: stingray_stats.z2_n_probability(
                values["z2"],
                values["harmonics"],
                ntrial=values["n_trials"],
                n_summed_spectra=values["n_summed_spectra"],
            ),
            lambda values: stingray_stats.z2_n_logprobability(
                values["z2"],
                values["harmonics"],
                ntrial=values["n_trials"],
                n_summed_spectra=values["n_summed_spectra"],
            ),
        ),
        (
            "evaluate_fold",
            {"statistic": 30.0, "n_phase_bins": 16, "n_trials": 7},
            lambda values: stingray_stats.fold_profile_probability(
                values["statistic"],
                values["n_phase_bins"],
                ntrial=values["n_trials"],
            ),
            lambda values: stingray_stats.fold_profile_logprobability(
                values["statistic"],
                values["n_phase_bins"],
                ntrial=values["n_trials"],
            ),
        ),
        (
            "evaluate_pdm",
            {
                "statistic": 0.8,
                "n_samples": 1000,
                "n_phase_bins": 16,
                "n_trials": 7,
            },
            lambda values: stingray_stats.phase_dispersion_probability(
                values["statistic"],
                values["n_samples"],
                values["n_phase_bins"],
                ntrial=values["n_trials"],
            ),
            lambda values: stingray_stats.phase_dispersion_logprobability(
                values["statistic"],
                values["n_samples"],
                values["n_phase_bins"],
                ntrial=values["n_trials"],
            ),
        ),
    ],
)
def test_statistic_evaluations_match_both_public_stingray_calls(
    service,
    method,
    kwargs,
    probability_call,
    log_probability_call,
):
    data = _assert_success(getattr(service, method)(**kwargs))

    assert data["probability"] == pytest.approx(float(probability_call(kwargs)))
    assert data["log_probability"] == pytest.approx(float(log_probability_call(kwargs)))
    assert data["probability"] == pytest.approx(np.exp(data["log_probability"]))
    assert data["calculation"] == "probability"
    assert data["direction"] == "observed_statistic_to_false_alarm_probability"
    assert data["probability_scope"] == "overall_post_trial"
    assert data["more_significant_when"] == (
        "smaller" if method == "evaluate_pdm" else "larger"
    )


@pytest.mark.parametrize(
    ("method", "kwargs", "upstream", "upstream_args"),
    [
        (
            "detect_pds",
            {
                "false_alarm_probability": 0.01,
                "n_trials": 37,
                "n_summed_spectra": 2,
                "n_rebin": 4,
            },
            stingray_stats.pds_detection_level,
            {
                "epsilon": 0.01,
                "ntrial": 37,
                "n_summed_spectra": 2,
                "n_rebin": 4,
            },
        ),
        (
            "detect_z2",
            {
                "false_alarm_probability": 0.01,
                "harmonics": 3,
                "n_trials": 7,
                "n_summed_spectra": 2,
            },
            stingray_stats.z2_n_detection_level,
            {"n": 3, "epsilon": 0.01, "ntrial": 7, "n_summed_spectra": 2},
        ),
        (
            "detect_fold",
            {"false_alarm_probability": 0.01, "n_phase_bins": 16, "n_trials": 7},
            stingray_stats.fold_detection_level,
            {"nbin": 16, "epsilon": 0.01, "ntrial": 7},
        ),
        (
            "detect_pdm",
            {
                "false_alarm_probability": 0.01,
                "n_samples": 1000,
                "n_phase_bins": 16,
                "n_trials": 7,
            },
            stingray_stats.phase_dispersion_detection_level,
            {"nsamples": 1000, "nbin": 16, "epsilon": 0.01, "ntrial": 7},
        ),
    ],
)
def test_detection_levels_match_public_stingray_calls(
    service, method, kwargs, upstream, upstream_args
):
    data = _assert_success(getattr(service, method)(**kwargs))

    assert data["detection_level"] == pytest.approx(float(upstream(**upstream_args)))
    assert data["false_alarm_probability"] == kwargs["false_alarm_probability"]
    assert data["false_alarm_probability_scope"] == "overall_post_trial"
    assert data["direction"] == "false_alarm_probability_to_detection_level"
    expected_operator = "<=" if method == "detect_pdm" else ">="
    assert data["decision_rule"] == (
        f"observed_statistic {expected_operator} detection_level"
    )


def test_detection_level_roundtrips_to_requested_overall_probability(service):
    detection = _assert_success(
        service.detect_pds(
            false_alarm_probability=0.01,
            n_trials=37,
            n_summed_spectra=2,
            n_rebin=4,
        )
    )
    evaluated = _assert_success(
        service.evaluate_pds(
            power=detection["detection_level"],
            n_trials=37,
            n_summed_spectra=2,
            n_rebin=4,
        )
    )
    assert evaluated["probability"] == pytest.approx(0.01)


@pytest.mark.parametrize(
    ("method", "kwargs", "message"),
    [
        (
            "gaussian_significance",
            {"probability": np.nan, "sidedness": "one-sided"},
            "must be finite",
        ),
        (
            "gaussian_significance",
            {"probability": 0.1, "log_probability": -2.0},
            "exactly one",
        ),
        (
            "convert_trials",
            {"direction": "single-to-multi", "probability": 0.01, "n_trials": True},
            "must be an integer",
        ),
        (
            "convert_trials",
            {"direction": "single-to-multi", "probability": 0.01, "n_trials": 1.0},
            "must be an integer",
        ),
        (
            "convert_trials",
            {
                "direction": "single-to-multi",
                "probability": 0.01,
                "n_trials": MAX_COUNT_PARAMETER + 1,
            },
            "must not exceed",
        ),
        ("evaluate_pds", {"power": -1.0}, "must be at least 0"),
        ("evaluate_pds", {"power": 10**1000}, "must be a finite number"),
        ("evaluate_z2", {"z2": np.inf}, "must be finite"),
        (
            "evaluate_fold",
            {"statistic": 10.0, "n_phase_bins": 2},
            "must be at least 3",
        ),
        (
            "evaluate_pdm",
            {"statistic": 1.1, "n_samples": 100, "n_phase_bins": 10},
            "must be at most 1",
        ),
        (
            "evaluate_pdm",
            {"statistic": 0.8, "n_samples": 10, "n_phase_bins": 10},
            "must be greater than",
        ),
        (
            "detect_pds",
            {"false_alarm_probability": 1.0},
            "must be less than 1",
        ),
        (
            "convert_trials",
            {"direction": "multi-to-single", "probability": 1.0, "n_trials": 10},
            "must be less than 1",
        ),
    ],
)
def test_service_rejects_invalid_and_nonfinite_domains(
    service, method, kwargs, message
):
    result = getattr(service, method)(**kwargs)

    assert not result["success"]
    assert result["data"] is None
    assert result["error"] is None
    assert message in result["message"]
    json.dumps(result, allow_nan=False)


def test_probability_underflow_preserves_zero_and_finite_log_probability(service):
    data = _assert_success(service.evaluate_pds(power=1_000_000.0))

    assert data["probability"] == 0.0
    assert np.isfinite(data["log_probability"])
    assert data["log_probability"] == pytest.approx(
        float(stingray_stats.pds_logprobability(1_000_000.0))
    )
    assert any("underflowed to 0.0" in warning for warning in data["warnings"])


def test_nonfinite_upstream_log_output_becomes_null_with_warning(service):
    data = _assert_success(
        service.evaluate_pdm(
            statistic=0.0,
            n_samples=1000,
            n_phase_bins=16,
        )
    )

    assert data["probability"] == 0.0
    assert data["log_probability"] is None
    assert any(
        "non-finite" in warning and "represented as null" in warning
        for warning in data["warnings"]
    )


def test_numpy_scalar_inputs_are_normalized_in_provenance(service):
    result = service.evaluate_pds(
        power=np.float32(10.0),
        n_trials=np.int64(3),
        n_summed_spectra=np.int64(2),
        n_rebin=np.int64(4),
    )
    data = _assert_success(result)

    parameters = data["provenance"]["parameters"]
    assert parameters == {
        "power": 10.0,
        "n_trials": 3,
        "n_summed_spectra": 2,
        "n_rebin": 4,
    }


def test_ill_conditioned_inverse_trial_result_is_null_and_warnings_are_captured(
    service,
):
    data = _assert_success(
        service.convert_trials(
            direction="multi-to-single",
            probability=float(np.nextafter(1.0, 0.0)),
            n_trials=1000,
        )
    )

    assert data["output_probability"] is None
    assert any("very close to 1" in warning for warning in data["warnings"])
    assert any("ill-conditioned" in warning for warning in data["warnings"])
    assert any("represented as null" in warning for warning in data["warnings"])


def test_request_models_are_strict_finite_and_forbid_extra_fields():
    with pytest.raises(ValidationError):
        PdsEvaluateRequest(power=np.nan)
    with pytest.raises(ValidationError):
        PdsEvaluateRequest(power=10.0, n_trials=1.0)
    with pytest.raises(ValidationError):
        PdsEvaluateRequest(power=10.0, surprise=True)
    with pytest.raises(ValidationError):
        GaussianRequest(probability=0.1, log_probability=-2.0)
    with pytest.raises(ValidationError):
        GaussianRequest()
    assert (
        TrialRequest(
            direction="single-to-multi", probability=0.0, n_trials=1
        ).probability
        == 0.0
    )
    assert (
        TrialRequest(
            direction="single-to-multi", probability=1.0, n_trials=1
        ).probability
        == 1.0
    )
    assert (
        TrialRequest(
            direction="multi-to-single", probability=0.0, n_trials=1
        ).probability
        == 0.0
    )
    with pytest.raises(ValidationError):
        TrialRequest(direction="multi-to-single", probability=1.0, n_trials=1)
    with pytest.raises(ValidationError):
        PdmEvaluateRequest(
            statistic=0.8,
            n_samples=10,
            n_phase_bins=10,
        )


def test_router_exposes_only_the_explicit_statistics_operations():
    actual = {
        (route.path, frozenset(route.methods))
        for route in statistics_routes.router.routes
    }
    expected_paths = {
        "/gaussian",
        "/trials",
        "/pds/evaluate",
        "/pds/detection",
        "/z2/evaluate",
        "/z2/detection",
        "/fold/evaluate",
        "/fold/detection",
        "/pdm/evaluate",
        "/pdm/detection",
    }

    assert actual == {(path, frozenset({"POST"})) for path in expected_paths}


def test_every_statistics_route_offloads_its_service_operation_to_a_thread():
    assert statistics_routes.router.routes
    for route in statistics_routes.router.routes:
        source = inspect.getsource(route.endpoint)
        assert "return await asyncio.to_thread(" in source, route.path
