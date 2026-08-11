/**
 * Typed API boundary for the explicit statistical utilities exposed by the
 * FastAPI backend.  Each method maps to one supported Stingray operation;
 * there is deliberately no generic function-execution endpoint.
 */

import { apiClient, ApiResponse } from './client';

export type StatisticalSidedness = 'one-sided' | 'two-sided';
export type TrialDirection = 'single-to-multi' | 'multi-to-single';

export interface StatisticsResultBase {
  warnings: string[];
  provenance: Record<string, unknown>;
  units: Record<string, string>;
}

export interface GaussianResult extends StatisticsResultBase {
  calculation: 'gaussian_significance';
  input_mode: 'probability' | 'log_probability';
  input_probability: number | null;
  input_log_probability: number | null;
  effective_one_sided_probability: number | null;
  effective_one_sided_log_probability: number | null;
  sigma: number | null;
  sidedness: StatisticalSidedness;
  tail: 'upper';
  direction: 'probability_to_gaussian_sigma';
}

export interface TrialCorrectionResult extends StatisticsResultBase {
  calculation: 'trial_correction';
  direction: TrialDirection;
  input_probability: number;
  output_probability: number | null;
  n_trials: number;
  independence_assumption: string;
}

export interface StatisticEvaluationResult extends StatisticsResultBase {
  family: 'pds' | 'z2_n' | 'epoch_folding' | 'phase_dispersion';
  calculation: 'probability';
  observed_statistic: number;
  probability: number | null;
  log_probability: number | null;
  probability_scope: 'overall_post_trial';
  tail: 'upper' | 'lower';
  more_significant_when: 'larger' | 'smaller';
  direction: 'observed_statistic_to_false_alarm_probability';
  n_trials: number;
  n_summed_spectra?: number;
  n_rebin?: number;
  harmonics?: number;
  n_phase_bins?: number;
  n_samples?: number;
}

export interface StatisticDetectionResult extends StatisticsResultBase {
  family: 'pds' | 'z2_n' | 'epoch_folding' | 'phase_dispersion';
  calculation: 'detection_level';
  detection_level: number | null;
  false_alarm_probability: number;
  false_alarm_probability_scope: 'overall_post_trial';
  n_trials: number;
  tail: 'upper' | 'lower';
  decision_rule: string;
  direction: 'false_alarm_probability_to_detection_level';
  n_summed_spectra?: number;
  n_rebin?: number;
  harmonics?: number;
  n_phase_bins?: number;
  n_samples?: number;
}

export type GaussianRequest = {
  sidedness: StatisticalSidedness;
} & (
  | { probability: number; log_probability?: never }
  | { probability?: never; log_probability: number }
);

export interface TrialCorrectionRequest {
  direction: TrialDirection;
  probability: number;
  n_trials: number;
}

export interface PdsEvaluateRequest {
  power: number;
  n_trials?: number;
  n_summed_spectra?: number;
  n_rebin?: number;
}

export interface PdsDetectionRequest {
  false_alarm_probability: number;
  n_trials?: number;
  n_summed_spectra?: number;
  n_rebin?: number;
}

export interface Z2EvaluateRequest {
  z2: number;
  harmonics?: number;
  n_trials?: number;
  n_summed_spectra?: number;
}

export interface Z2DetectionRequest {
  false_alarm_probability: number;
  harmonics?: number;
  n_trials?: number;
  n_summed_spectra?: number;
}

export interface FoldEvaluateRequest {
  statistic: number;
  n_phase_bins: number;
  n_trials?: number;
}

export interface FoldDetectionRequest {
  false_alarm_probability: number;
  n_phase_bins: number;
  n_trials?: number;
}

export interface PdmEvaluateRequest {
  statistic: number;
  n_samples: number;
  n_phase_bins: number;
  n_trials?: number;
}

export interface PdmDetectionRequest {
  false_alarm_probability: number;
  n_samples: number;
  n_phase_bins: number;
  n_trials?: number;
}

const PREFIX = '/api/utilities/statistics';

export const statisticsApi = {
  gaussian(params: GaussianRequest): Promise<ApiResponse<GaussianResult>> {
    return apiClient.post(`${PREFIX}/gaussian`, params);
  },

  trials(params: TrialCorrectionRequest): Promise<ApiResponse<TrialCorrectionResult>> {
    return apiClient.post(`${PREFIX}/trials`, params);
  },

  evaluatePds(params: PdsEvaluateRequest): Promise<ApiResponse<StatisticEvaluationResult>> {
    return apiClient.post(`${PREFIX}/pds/evaluate`, {
      power: params.power,
      n_trials: params.n_trials ?? 1,
      n_summed_spectra: params.n_summed_spectra ?? 1,
      n_rebin: params.n_rebin ?? 1,
    });
  },

  detectPds(params: PdsDetectionRequest): Promise<ApiResponse<StatisticDetectionResult>> {
    return apiClient.post(`${PREFIX}/pds/detection`, {
      false_alarm_probability: params.false_alarm_probability,
      n_trials: params.n_trials ?? 1,
      n_summed_spectra: params.n_summed_spectra ?? 1,
      n_rebin: params.n_rebin ?? 1,
    });
  },

  evaluateZ2(params: Z2EvaluateRequest): Promise<ApiResponse<StatisticEvaluationResult>> {
    return apiClient.post(`${PREFIX}/z2/evaluate`, {
      z2: params.z2,
      harmonics: params.harmonics ?? 2,
      n_trials: params.n_trials ?? 1,
      n_summed_spectra: params.n_summed_spectra ?? 1,
    });
  },

  detectZ2(params: Z2DetectionRequest): Promise<ApiResponse<StatisticDetectionResult>> {
    return apiClient.post(`${PREFIX}/z2/detection`, {
      false_alarm_probability: params.false_alarm_probability,
      harmonics: params.harmonics ?? 2,
      n_trials: params.n_trials ?? 1,
      n_summed_spectra: params.n_summed_spectra ?? 1,
    });
  },

  evaluateFold(params: FoldEvaluateRequest): Promise<ApiResponse<StatisticEvaluationResult>> {
    return apiClient.post(`${PREFIX}/fold/evaluate`, {
      statistic: params.statistic,
      n_phase_bins: params.n_phase_bins,
      n_trials: params.n_trials ?? 1,
    });
  },

  detectFold(params: FoldDetectionRequest): Promise<ApiResponse<StatisticDetectionResult>> {
    return apiClient.post(`${PREFIX}/fold/detection`, {
      false_alarm_probability: params.false_alarm_probability,
      n_phase_bins: params.n_phase_bins,
      n_trials: params.n_trials ?? 1,
    });
  },

  evaluatePdm(params: PdmEvaluateRequest): Promise<ApiResponse<StatisticEvaluationResult>> {
    return apiClient.post(`${PREFIX}/pdm/evaluate`, {
      statistic: params.statistic,
      n_samples: params.n_samples,
      n_phase_bins: params.n_phase_bins,
      n_trials: params.n_trials ?? 1,
    });
  },

  detectPdm(params: PdmDetectionRequest): Promise<ApiResponse<StatisticDetectionResult>> {
    return apiClient.post(`${PREFIX}/pdm/detection`, {
      false_alarm_probability: params.false_alarm_probability,
      n_samples: params.n_samples,
      n_phase_bins: params.n_phase_bins,
      n_trials: params.n_trials ?? 1,
    });
  },
};

export default statisticsApi;
