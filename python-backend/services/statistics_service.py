"""Statistical utility service backed by the public Stingray 2.2.10 API."""

# Service boundaries intentionally catch unexpected library failures and route
# them through BaseService's standardized error handler.
# ruff: noqa: BLE001

from __future__ import annotations

import math
from numbers import Integral, Real
from typing import Any

from stingray import stats as stingray_stats

from .analysis_helpers import collect_warnings
from .base_service import BaseService
from .utility_helpers import finite_or_none, json_safe, operation_provenance

# Plain Python integers dispatch to the int32 Numba overload used by Stingray's
# trial-correction ufuncs. Keeping parameters within this bound avoids a
# platform-dependent OverflowError while still allowing realistic searches.
MAX_COUNT_PARAMETER = 2_147_483_647

PROBABILITY_UNITS = "dimensionless probability"
LOG_PROBABILITY_UNITS = "natural logarithm of a dimensionless probability"


def _number_error(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
    maximum_inclusive: bool = True,
) -> str | None:
    """Return a readable validation error for a finite real scalar."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return f"{label} must be a finite number"
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return f"{label} must be a finite number"
    if not math.isfinite(numeric):
        return f"{label} must be finite"
    if minimum is not None:
        invalid = numeric < minimum if minimum_inclusive else numeric <= minimum
        if invalid:
            relation = "at least" if minimum_inclusive else "greater than"
            return f"{label} must be {relation} {minimum:g}"
    if maximum is not None:
        invalid = numeric > maximum if maximum_inclusive else numeric >= maximum
        if invalid:
            relation = "at most" if maximum_inclusive else "less than"
            return f"{label} must be {relation} {maximum:g}"
    return None


def _count_error(value: Any, label: str, *, minimum: int = 1) -> str | None:
    """Return a readable validation error for a bounded integer count."""
    if isinstance(value, bool) or not isinstance(value, Integral):
        return f"{label} must be an integer"
    integer = int(value)
    if integer < minimum:
        return f"{label} must be at least {minimum}"
    if integer > MAX_COUNT_PARAMETER:
        return f"{label} must not exceed {MAX_COUNT_PARAMETER:,}"
    return None


def _append_underflow_warning(
    probability: float | None,
    log_probability: float | None,
    warning_messages: list[str],
) -> None:
    """Explain a linear-probability underflow without discarding its zero."""
    if probability == 0.0 and log_probability is not None:
        warning = (
            "The linear probability underflowed to 0.0 in floating-point; "
            "the finite natural-log probability preserves the significance."
        )
        if warning not in warning_messages:
            warning_messages.append(warning)


class StatisticsService(BaseService):
    """Stateless wrappers around supported public functions in ``stingray.stats``."""

    def _invalid(self, message: str) -> dict[str, Any]:
        return self.create_result(
            success=False,
            data=None,
            message=message,
            error=None,
        )

    def _finish(
        self,
        core: dict[str, Any],
        warning_messages: list[str],
        *,
        operation: str,
        parameters: dict[str, Any],
        public_api_calls: list[str],
        message: str,
    ) -> dict[str, Any]:
        """Sanitize a successful payload and attach reproducibility metadata."""
        data = json_safe(core, warning_messages)
        data["provenance"] = json_safe(
            operation_provenance(
                operation,
                input_source="user-supplied scalar inputs",
                parameters=parameters,
                public_api_calls=public_api_calls,
            ),
            warning_messages,
            "provenance",
        )
        data["warnings"] = warning_messages
        return self.create_result(success=True, data=data, message=message)

    def gaussian_significance(
        self,
        *,
        probability: float | None = None,
        log_probability: float | None = None,
        sidedness: str = "one-sided",
    ) -> dict[str, Any]:
        """Convert a tail probability to Gaussian sigma with explicit sidedness.

        Stingray implements the one-sided upper-tail convention ``Q^-1(p)``.
        For a two-sided total probability, half of the probability belongs to
        each tail, so this service passes ``p / 2`` (or ``ln(p) - ln(2)``) to
        Stingray and exposes that transformed effective tail in the response.
        """
        try:
            if sidedness not in {"one-sided", "two-sided"}:
                return self._invalid("sidedness must be 'one-sided' or 'two-sided'")
            if (probability is None) == (log_probability is None):
                return self._invalid(
                    "Provide exactly one of probability or log_probability"
                )

            if probability is not None:
                error = _number_error(
                    probability,
                    "probability",
                    minimum=0.0,
                    maximum=1.0,
                    minimum_inclusive=False,
                    maximum_inclusive=False,
                )
                if error:
                    return self._invalid(error)
                input_probability = float(probability)
                input_log_probability = math.log(input_probability)
                input_mode = "probability"
            else:
                error = _number_error(
                    log_probability,
                    "log_probability",
                    maximum=0.0,
                    maximum_inclusive=False,
                )
                if error:
                    return self._invalid(
                        f"{error}; log_probability is the natural logarithm of p"
                    )
                input_probability = None
                input_log_probability = float(log_probability)
                input_mode = "log_probability"

            tail_adjustment = math.log(2.0) if sidedness == "two-sided" else 0.0
            effective_log_probability = input_log_probability - tail_adjustment
            effective_probability = math.exp(effective_log_probability)

            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                if input_mode == "probability" and effective_probability > 0.0:
                    raw_sigma = stingray_stats.equivalent_gaussian_Nsigma(
                        effective_probability
                    )
                    public_call = "stingray.stats.equivalent_gaussian_Nsigma"
                else:
                    raw_sigma = stingray_stats.equivalent_gaussian_Nsigma_from_logp(
                        effective_log_probability
                    )
                    public_call = "stingray.stats.equivalent_gaussian_Nsigma_from_logp"

            sigma = finite_or_none(raw_sigma, warning_messages, "Gaussian sigma")
            effective_probability_value = finite_or_none(
                effective_probability,
                warning_messages,
                "effective one-sided probability",
            )
            _append_underflow_warning(
                effective_probability_value,
                effective_log_probability,
                warning_messages,
            )
            parameters = {
                "probability": probability,
                "log_probability": log_probability,
                "sidedness": sidedness,
            }
            core = {
                "calculation": "gaussian_significance",
                "input_mode": input_mode,
                "input_probability": input_probability,
                "input_log_probability": input_log_probability,
                "effective_one_sided_probability": effective_probability_value,
                "effective_one_sided_log_probability": effective_log_probability,
                "sigma": sigma,
                "sidedness": sidedness,
                "tail": "upper",
                "direction": "probability_to_gaussian_sigma",
                "units": {
                    "input_probability": PROBABILITY_UNITS,
                    "input_log_probability": LOG_PROBABILITY_UNITS,
                    "sigma": "standard deviations from the Gaussian mean",
                },
            }
            return self._finish(
                core,
                warning_messages,
                operation="statistics.gaussian_significance",
                parameters=parameters,
                public_api_calls=[public_call],
                message="Converted tail probability to Gaussian significance",
            )
        except Exception as exc:
            return self.handle_error(
                exc,
                "Converting probability to Gaussian significance",
                probability=probability,
                log_probability=log_probability,
                sidedness=sidedness,
            )

    def convert_trials(
        self,
        *,
        direction: str,
        probability: float,
        n_trials: int,
    ) -> dict[str, Any]:
        """Apply Stingray's independent-trial forward or inverse correction."""
        try:
            if direction not in {"single-to-multi", "multi-to-single"}:
                return self._invalid(
                    "direction must be 'single-to-multi' or 'multi-to-single'"
                )
            error = _number_error(
                probability,
                "probability",
                minimum=0.0,
                maximum=1.0,
            )
            if error:
                return self._invalid(error)
            if direction == "multi-to-single" and float(probability) == 1.0:
                return self._invalid(
                    "probability must be less than 1 for multi-to-single conversion; "
                    "the inverse is numerically ill-conditioned at 1"
                )
            error = _count_error(n_trials, "n_trials")
            if error:
                return self._invalid(error)

            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                if direction == "single-to-multi":
                    raw_output = stingray_stats.p_multitrial_from_single_trial(
                        float(probability), int(n_trials)
                    )
                    public_call = "stingray.stats.p_multitrial_from_single_trial"
                else:
                    raw_output = stingray_stats.p_single_trial_from_p_multitrial(
                        float(probability), int(n_trials)
                    )
                    public_call = "stingray.stats.p_single_trial_from_p_multitrial"

            output_probability = finite_or_none(
                raw_output, warning_messages, "trial-corrected probability"
            )
            parameters = {
                "direction": direction,
                "probability": probability,
                "n_trials": n_trials,
            }
            core = {
                "calculation": "trial_correction",
                "direction": direction,
                "input_probability": float(probability),
                "output_probability": output_probability,
                "n_trials": int(n_trials),
                "independence_assumption": (
                    "Trials are assumed to be statistically independent."
                ),
                "units": {
                    "input_probability": PROBABILITY_UNITS,
                    "output_probability": PROBABILITY_UNITS,
                },
            }
            return self._finish(
                core,
                warning_messages,
                operation="statistics.trial_correction",
                parameters=parameters,
                public_api_calls=[public_call],
                message="Converted probability across independent trials",
            )
        except Exception as exc:
            return self.handle_error(
                exc,
                "Converting trial probability",
                direction=direction,
                probability=probability,
                n_trials=n_trials,
            )

    def evaluate_pds(
        self,
        *,
        power: float,
        n_trials: int = 1,
        n_summed_spectra: int = 1,
        n_rebin: int = 1,
    ) -> dict[str, Any]:
        """Evaluate an observed Leahy-normalized PDS power."""
        errors = [
            _number_error(power, "power", minimum=0.0),
            _count_error(n_trials, "n_trials"),
            _count_error(n_summed_spectra, "n_summed_spectra"),
            _count_error(n_rebin, "n_rebin"),
        ]
        error = next((item for item in errors if item), None)
        if error:
            return self._invalid(error)
        if not math.isfinite(float(power) * int(n_summed_spectra) * int(n_rebin)):
            return self._invalid(
                "power x n_summed_spectra x n_rebin must remain finite"
            )
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_probability = stingray_stats.pds_probability(
                    float(power),
                    ntrial=int(n_trials),
                    n_summed_spectra=int(n_summed_spectra),
                    n_rebin=int(n_rebin),
                )
                raw_log_probability = stingray_stats.pds_logprobability(
                    float(power),
                    ntrial=int(n_trials),
                    n_summed_spectra=int(n_summed_spectra),
                    n_rebin=int(n_rebin),
                )
            return self._finish_evaluation(
                family="pds",
                observed_statistic=float(power),
                raw_probability=raw_probability,
                raw_log_probability=raw_log_probability,
                parameters={
                    "power": power,
                    "n_trials": n_trials,
                    "n_summed_spectra": n_summed_spectra,
                    "n_rebin": n_rebin,
                },
                echoed_parameters={
                    "n_trials": int(n_trials),
                    "n_summed_spectra": int(n_summed_spectra),
                    "n_rebin": int(n_rebin),
                },
                warning_messages=warning_messages,
                public_api_calls=[
                    "stingray.stats.pds_probability",
                    "stingray.stats.pds_logprobability",
                ],
                statistic_units="dimensionless Leahy-normalized power",
                tail="upper",
            )
        except Exception as exc:
            return self.handle_error(exc, "Evaluating PDS probability", power=power)

    def detect_pds(
        self,
        *,
        false_alarm_probability: float,
        n_trials: int = 1,
        n_summed_spectra: int = 1,
        n_rebin: int = 1,
    ) -> dict[str, Any]:
        """Calculate a Leahy PDS threshold for an overall false-alarm rate."""
        parameters = {
            "false_alarm_probability": false_alarm_probability,
            "n_trials": n_trials,
            "n_summed_spectra": n_summed_spectra,
            "n_rebin": n_rebin,
        }
        error = self._detection_parameters_error(
            false_alarm_probability,
            n_trials,
            (n_summed_spectra, "n_summed_spectra"),
            (n_rebin, "n_rebin"),
        )
        if error:
            return self._invalid(error)
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_level = stingray_stats.pds_detection_level(
                    epsilon=float(false_alarm_probability),
                    ntrial=int(n_trials),
                    n_summed_spectra=int(n_summed_spectra),
                    n_rebin=int(n_rebin),
                )
            return self._finish_detection(
                family="pds",
                false_alarm_probability=float(false_alarm_probability),
                raw_level=raw_level,
                parameters=parameters,
                echoed_parameters={
                    "n_trials": int(n_trials),
                    "n_summed_spectra": int(n_summed_spectra),
                    "n_rebin": int(n_rebin),
                },
                warning_messages=warning_messages,
                public_api_call="stingray.stats.pds_detection_level",
                statistic_units="dimensionless Leahy-normalized power",
                tail="upper",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating PDS detection level", **parameters
            )

    def evaluate_z2(
        self,
        *,
        z2: float,
        harmonics: int = 2,
        n_trials: int = 1,
        n_summed_spectra: int = 1,
    ) -> dict[str, Any]:
        """Evaluate an observed averaged Z-squared-n statistic."""
        errors = [
            _number_error(z2, "z2", minimum=0.0),
            _count_error(harmonics, "harmonics"),
            _count_error(n_trials, "n_trials"),
            _count_error(n_summed_spectra, "n_summed_spectra"),
        ]
        error = next((item for item in errors if item), None)
        if error:
            return self._invalid(error)
        if not math.isfinite(float(z2) * int(n_summed_spectra)):
            return self._invalid("z2 x n_summed_spectra must remain finite")
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_probability = stingray_stats.z2_n_probability(
                    float(z2),
                    int(harmonics),
                    ntrial=int(n_trials),
                    n_summed_spectra=int(n_summed_spectra),
                )
                raw_log_probability = stingray_stats.z2_n_logprobability(
                    float(z2),
                    int(harmonics),
                    ntrial=int(n_trials),
                    n_summed_spectra=int(n_summed_spectra),
                )
            return self._finish_evaluation(
                family="z2_n",
                observed_statistic=float(z2),
                raw_probability=raw_probability,
                raw_log_probability=raw_log_probability,
                parameters={
                    "z2": z2,
                    "harmonics": harmonics,
                    "n_trials": n_trials,
                    "n_summed_spectra": n_summed_spectra,
                },
                echoed_parameters={
                    "harmonics": int(harmonics),
                    "n_trials": int(n_trials),
                    "n_summed_spectra": int(n_summed_spectra),
                },
                warning_messages=warning_messages,
                public_api_calls=[
                    "stingray.stats.z2_n_probability",
                    "stingray.stats.z2_n_logprobability",
                ],
                statistic_units="dimensionless Z-squared-n statistic",
                tail="upper",
            )
        except Exception as exc:
            return self.handle_error(exc, "Evaluating Z-squared-n probability", z2=z2)

    def detect_z2(
        self,
        *,
        false_alarm_probability: float,
        harmonics: int = 2,
        n_trials: int = 1,
        n_summed_spectra: int = 1,
    ) -> dict[str, Any]:
        """Calculate a Z-squared-n threshold for an overall false-alarm rate."""
        parameters = {
            "false_alarm_probability": false_alarm_probability,
            "harmonics": harmonics,
            "n_trials": n_trials,
            "n_summed_spectra": n_summed_spectra,
        }
        error = self._detection_parameters_error(
            false_alarm_probability,
            n_trials,
            (harmonics, "harmonics"),
            (n_summed_spectra, "n_summed_spectra"),
        )
        if error:
            return self._invalid(error)
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_level = stingray_stats.z2_n_detection_level(
                    n=int(harmonics),
                    epsilon=float(false_alarm_probability),
                    ntrial=int(n_trials),
                    n_summed_spectra=int(n_summed_spectra),
                )
            return self._finish_detection(
                family="z2_n",
                false_alarm_probability=float(false_alarm_probability),
                raw_level=raw_level,
                parameters=parameters,
                echoed_parameters={
                    "harmonics": int(harmonics),
                    "n_trials": int(n_trials),
                    "n_summed_spectra": int(n_summed_spectra),
                },
                warning_messages=warning_messages,
                public_api_call="stingray.stats.z2_n_detection_level",
                statistic_units="dimensionless Z-squared-n statistic",
                tail="upper",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating Z-squared-n detection level", **parameters
            )

    def evaluate_fold(
        self,
        *,
        statistic: float,
        n_phase_bins: int,
        n_trials: int = 1,
    ) -> dict[str, Any]:
        """Evaluate an observed epoch-folding statistic."""
        errors = [
            _number_error(statistic, "statistic", minimum=0.0),
            _count_error(n_phase_bins, "n_phase_bins", minimum=3),
            _count_error(n_trials, "n_trials"),
        ]
        error = next((item for item in errors if item), None)
        if error:
            return self._invalid(error)
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_probability = stingray_stats.fold_profile_probability(
                    float(statistic), int(n_phase_bins), ntrial=int(n_trials)
                )
                raw_log_probability = stingray_stats.fold_profile_logprobability(
                    float(statistic), int(n_phase_bins), ntrial=int(n_trials)
                )
            return self._finish_evaluation(
                family="epoch_folding",
                observed_statistic=float(statistic),
                raw_probability=raw_probability,
                raw_log_probability=raw_log_probability,
                parameters={
                    "statistic": statistic,
                    "n_phase_bins": n_phase_bins,
                    "n_trials": n_trials,
                },
                echoed_parameters={
                    "n_phase_bins": int(n_phase_bins),
                    "n_trials": int(n_trials),
                },
                warning_messages=warning_messages,
                public_api_calls=[
                    "stingray.stats.fold_profile_probability",
                    "stingray.stats.fold_profile_logprobability",
                ],
                statistic_units="dimensionless epoch-folding statistic",
                tail="upper",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Evaluating epoch-folding probability", statistic=statistic
            )

    def detect_fold(
        self,
        *,
        false_alarm_probability: float,
        n_phase_bins: int,
        n_trials: int = 1,
    ) -> dict[str, Any]:
        """Calculate an epoch-folding threshold for an overall false-alarm rate."""
        parameters = {
            "false_alarm_probability": false_alarm_probability,
            "n_phase_bins": n_phase_bins,
            "n_trials": n_trials,
        }
        error = self._detection_parameters_error(
            false_alarm_probability,
            n_trials,
            (n_phase_bins, "n_phase_bins", 3),
        )
        if error:
            return self._invalid(error)
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_level = stingray_stats.fold_detection_level(
                    int(n_phase_bins),
                    epsilon=float(false_alarm_probability),
                    ntrial=int(n_trials),
                )
            return self._finish_detection(
                family="epoch_folding",
                false_alarm_probability=float(false_alarm_probability),
                raw_level=raw_level,
                parameters=parameters,
                echoed_parameters={
                    "n_phase_bins": int(n_phase_bins),
                    "n_trials": int(n_trials),
                },
                warning_messages=warning_messages,
                public_api_call="stingray.stats.fold_detection_level",
                statistic_units="dimensionless epoch-folding statistic",
                tail="upper",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating epoch-folding detection level", **parameters
            )

    def evaluate_pdm(
        self,
        *,
        statistic: float,
        n_samples: int,
        n_phase_bins: int,
        n_trials: int = 1,
    ) -> dict[str, Any]:
        """Evaluate an observed phase-dispersion statistic (lower tail)."""
        error = self._pdm_parameters_error(
            statistic=statistic,
            n_samples=n_samples,
            n_phase_bins=n_phase_bins,
            n_trials=n_trials,
        )
        if error:
            return self._invalid(error)
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_probability = stingray_stats.phase_dispersion_probability(
                    float(statistic),
                    int(n_samples),
                    int(n_phase_bins),
                    ntrial=int(n_trials),
                )
                raw_log_probability = stingray_stats.phase_dispersion_logprobability(
                    float(statistic),
                    int(n_samples),
                    int(n_phase_bins),
                    ntrial=int(n_trials),
                )
            return self._finish_evaluation(
                family="phase_dispersion",
                observed_statistic=float(statistic),
                raw_probability=raw_probability,
                raw_log_probability=raw_log_probability,
                parameters={
                    "statistic": statistic,
                    "n_samples": n_samples,
                    "n_phase_bins": n_phase_bins,
                    "n_trials": n_trials,
                },
                echoed_parameters={
                    "n_samples": int(n_samples),
                    "n_phase_bins": int(n_phase_bins),
                    "n_trials": int(n_trials),
                },
                warning_messages=warning_messages,
                public_api_calls=[
                    "stingray.stats.phase_dispersion_probability",
                    "stingray.stats.phase_dispersion_logprobability",
                ],
                statistic_units="dimensionless phase-dispersion statistic",
                tail="lower",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Evaluating phase-dispersion probability", statistic=statistic
            )

    def detect_pdm(
        self,
        *,
        false_alarm_probability: float,
        n_samples: int,
        n_phase_bins: int,
        n_trials: int = 1,
    ) -> dict[str, Any]:
        """Calculate a PDM lower-tail threshold for an overall false-alarm rate."""
        parameters = {
            "false_alarm_probability": false_alarm_probability,
            "n_samples": n_samples,
            "n_phase_bins": n_phase_bins,
            "n_trials": n_trials,
        }
        error = self._pdm_parameters_error(
            statistic=None,
            n_samples=n_samples,
            n_phase_bins=n_phase_bins,
            n_trials=n_trials,
        )
        if not error:
            error = _number_error(
                false_alarm_probability,
                "false_alarm_probability",
                minimum=0.0,
                maximum=1.0,
                minimum_inclusive=False,
                maximum_inclusive=False,
            )
        if error:
            return self._invalid(error)
        try:
            warning_messages: list[str] = []
            with collect_warnings(warning_messages):
                raw_level = stingray_stats.phase_dispersion_detection_level(
                    int(n_samples),
                    int(n_phase_bins),
                    epsilon=float(false_alarm_probability),
                    ntrial=int(n_trials),
                )
            return self._finish_detection(
                family="phase_dispersion",
                false_alarm_probability=float(false_alarm_probability),
                raw_level=raw_level,
                parameters=parameters,
                echoed_parameters={
                    "n_samples": int(n_samples),
                    "n_phase_bins": int(n_phase_bins),
                    "n_trials": int(n_trials),
                },
                warning_messages=warning_messages,
                public_api_call="stingray.stats.phase_dispersion_detection_level",
                statistic_units="dimensionless phase-dispersion statistic",
                tail="lower",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating phase-dispersion detection level", **parameters
            )

    def _finish_evaluation(
        self,
        *,
        family: str,
        observed_statistic: float,
        raw_probability: Any,
        raw_log_probability: Any,
        parameters: dict[str, Any],
        echoed_parameters: dict[str, int],
        warning_messages: list[str],
        public_api_calls: list[str],
        statistic_units: str,
        tail: str,
    ) -> dict[str, Any]:
        probability = finite_or_none(
            raw_probability, warning_messages, "false-alarm probability"
        )
        log_probability = finite_or_none(
            raw_log_probability,
            warning_messages,
            "natural-log false-alarm probability",
        )
        _append_underflow_warning(probability, log_probability, warning_messages)
        core = {
            "family": family,
            "calculation": "probability",
            "direction": "observed_statistic_to_false_alarm_probability",
            "observed_statistic": observed_statistic,
            "probability": probability,
            "log_probability": log_probability,
            "probability_scope": "overall_post_trial",
            **echoed_parameters,
            "tail": tail,
            "more_significant_when": "larger" if tail == "upper" else "smaller",
            "units": {
                "observed_statistic": statistic_units,
                "probability": PROBABILITY_UNITS,
                "log_probability": LOG_PROBABILITY_UNITS,
            },
        }
        return self._finish(
            core,
            warning_messages,
            operation=f"statistics.{family}.probability",
            parameters=parameters,
            public_api_calls=public_api_calls,
            message=f"Evaluated {family.replace('_', ' ')} false-alarm probability",
        )

    def _finish_detection(
        self,
        *,
        family: str,
        false_alarm_probability: float,
        raw_level: Any,
        parameters: dict[str, Any],
        echoed_parameters: dict[str, int],
        warning_messages: list[str],
        public_api_call: str,
        statistic_units: str,
        tail: str,
    ) -> dict[str, Any]:
        detection_level = finite_or_none(raw_level, warning_messages, "detection level")
        comparison = ">=" if tail == "upper" else "<="
        core = {
            "family": family,
            "calculation": "detection_level",
            "direction": "false_alarm_probability_to_detection_level",
            "false_alarm_probability": false_alarm_probability,
            "false_alarm_probability_scope": "overall_post_trial",
            "detection_level": detection_level,
            **echoed_parameters,
            "tail": tail,
            "decision_rule": f"observed_statistic {comparison} detection_level",
            "units": {
                "false_alarm_probability": PROBABILITY_UNITS,
                "detection_level": statistic_units,
            },
        }
        return self._finish(
            core,
            warning_messages,
            operation=f"statistics.{family}.detection_level",
            parameters=parameters,
            public_api_calls=[public_api_call],
            message=f"Calculated {family.replace('_', ' ')} detection level",
        )

    def _detection_parameters_error(
        self,
        false_alarm_probability: Any,
        n_trials: Any,
        *counts: tuple[Any, str] | tuple[Any, str, int],
    ) -> str | None:
        error = _number_error(
            false_alarm_probability,
            "false_alarm_probability",
            minimum=0.0,
            maximum=1.0,
            minimum_inclusive=False,
            maximum_inclusive=False,
        )
        if error:
            return error
        error = _count_error(n_trials, "n_trials")
        if error:
            return error
        for count in counts:
            value, label = count[:2]
            minimum = count[2] if len(count) == 3 else 1
            error = _count_error(value, label, minimum=minimum)
            if error:
                return error
        return None

    def _pdm_parameters_error(
        self,
        *,
        statistic: Any | None,
        n_samples: Any,
        n_phase_bins: Any,
        n_trials: Any,
    ) -> str | None:
        if statistic is not None:
            error = _number_error(
                statistic,
                "statistic",
                minimum=0.0,
                maximum=1.0,
            )
            if error:
                return error
        for value, label, minimum in (
            (n_samples, "n_samples", 3),
            (n_phase_bins, "n_phase_bins", 2),
            (n_trials, "n_trials", 1),
        ):
            error = _count_error(value, label, minimum=minimum)
            if error:
                return error
        if int(n_samples) <= int(n_phase_bins):
            return "n_samples must be greater than n_phase_bins"
        return None
