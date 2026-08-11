/** Typed API surface for the curated public `stingray.utils` workbench. */

import { apiClient, type ApiResponse } from './client';

export type NullableNumber = number | null;

export interface UtilityProvenance {
  operation: string;
  input_source: {
    kind: 'installed_runtime' | 'pasted_values' | 'parameters' | 'pasted_matrix' | 'event_list';
    name?: string;
  };
  parameters: Record<string, string | number | boolean | null>;
  stingray_version: string;
  window_allowlist_source?: string;
  supported_window_types?: string[];
  source_snapshot?: boolean;
  uncertainty_compatibility?: {
    workaround_applied: boolean;
    reference: string;
    input_to_stingray: 'variance' | 'standard_uncertainty' | null;
  };
}

export interface UtilityData {
  warnings: string[];
  provenance: UtilityProvenance;
}

export interface NamedPlotPreview {
  values: Record<string, NullableNumber[]>;
  stride: number;
  source_points: number;
}

export interface MiscCapabilities extends UtilityData {
  window_types: string[];
  rebin: {
    modes: Array<'linear' | 'logarithmic'>;
    linear_methods: Array<'sum' | 'mean'>;
    logarithmic_method: 'mean';
    linear_uncertainty_workaround_required: boolean;
    linear_uncertainty_workaround_reference: string;
    linear_uncertainty_support: string;
  };
  baseline_defaults: {
    lambda: number;
    asymmetry: number;
    iterations: number;
    offset_correction: boolean;
  };
  runtime_advisories: {
    nearest_power_of_two: string;
  };
  limits: {
    max_array_values: number;
    max_exact_output_values: number;
    max_matrix_cells: number;
    max_baseline_iterations: number;
    max_fft_samples: number;
    max_poisson_count: number;
    max_energy_ranges: number;
  };
}

export interface RebinSeries {
  x: NullableNumber[];
  y: NullableNumber[];
  y_error: NullableNumber[] | null;
}

export interface RebinnedSeries extends RebinSeries {
  samples_per_bin: NullableNumber[] | number | null;
}

export interface RebinData extends UtilityData {
  mode: 'linear' | 'logarithmic';
  method: 'sum' | 'mean';
  original: RebinSeries;
  rebinned: RebinnedSeries;
  error_semantics: string | null;
  units: Record<string, string>;
  plot_preview: {
    original: NamedPlotPreview;
    rebinned: NamedPlotPreview;
  };
}

export interface BaselineData extends UtilityData {
  x: NullableNumber[];
  original: NullableNumber[];
  baseline: NullableNumber[];
  corrected: NullableNumber[];
  units: Record<string, string>;
  plot_preview: NamedPlotPreview;
}

export interface WindowSummary {
  minimum: NullableNumber;
  maximum: NullableNumber;
  sum: NullableNumber;
  mean: NullableNumber;
  rms: NullableNumber;
  energy: NullableNumber;
  coherent_gain: NullableNumber;
  equivalent_noise_bandwidth_bins: NullableNumber;
}

export interface WindowData extends UtilityData {
  window_type: string;
  n_samples: number;
  sample_index: NullableNumber[];
  window: NullableNumber[];
  units: Record<string, string>;
  summary: WindowSummary;
  plot_preview: NamedPlotPreview;
}

export interface OptimalBinTimeData extends UtilityData {
  requested_bin_time: number;
  adjusted_bin_time: number;
  sample_count: number;
  delta: number;
  fractional_change: number;
  changed: boolean;
  units: string;
}

export interface NearestPowerOfTwoData extends UtilityData {
  requested_value: number;
  nearest_power_of_two: number;
  delta: number;
  fractional_change: number;
  changed: boolean;
  units: string;
}

export interface SegmentSizeData extends UtilityData {
  requested_segment_size: number;
  adjusted_segment_size: number;
  sample_count: number;
  delta: number;
  fractional_change: number;
  changed: boolean;
  units: string;
}

export interface PoissonErrorData extends UtilityData {
  counts: NullableNumber[];
  symmetric_error: NullableNumber[];
  confidence_sigma: number;
  units: Record<string, string>;
  assumptions: string;
  plot_preview: NamedPlotPreview;
}

export interface StandardErrorData extends UtilityData {
  mean: NullableNumber[];
  calculated_sample_mean: NullableNumber[];
  standard_error: NullableNumber[];
  sample_count: number;
  column_count: number;
  mean_source: 'calculated_arithmetic_mean' | 'provided';
  units: Record<string, string>;
  assumptions: string;
  plot_preview: NamedPlotPreview;
}

export interface EnergyRangesData extends UtilityData {
  bin_edges: NullableNumber[];
  counts: NullableNumber[];
  n_ranges: number;
  selected_count: number;
  excluded_count: number;
  energy_min: number;
  energy_max: number;
  energy_unit: string;
  plot_preview: NamedPlotPreview;
}

export interface LinearRebinParams {
  x: number[];
  y: number[];
  dx_new: number;
  y_error?: number[] | null;
  method: 'sum' | 'mean';
  dx?: number | null;
}

export interface LogarithmicRebinParams {
  x: number[];
  y: number[];
  factor: number;
  y_error?: number[] | null;
  dx?: number | null;
}

export interface BaselineParams {
  x: number[];
  y: number[];
  lam: number;
  asymmetry: number;
  iterations: number;
  offset_correction: boolean;
}

interface EnergyRangesCommonParams {
  n_ranges: number;
  energy_min?: number | null;
  energy_max?: number | null;
  energy_unit: string;
}

export type EnergyRangesParams = EnergyRangesCommonParams & (
  | { energies: number[]; event_list_name?: never }
  | { energies?: never; event_list_name: string }
);

export const miscApi = {
  async capabilities(): Promise<ApiResponse<MiscCapabilities>> {
    return apiClient.get('/api/utilities/misc/capabilities');
  },

  async linearRebin(params: LinearRebinParams): Promise<ApiResponse<RebinData>> {
    return apiClient.post('/api/utilities/misc/rebin/linear', {
      x: params.x,
      y: params.y,
      dx_new: params.dx_new,
      y_error: params.y_error ?? null,
      method: params.method,
      dx: params.dx ?? null,
    });
  },

  async logarithmicRebin(params: LogarithmicRebinParams): Promise<ApiResponse<RebinData>> {
    return apiClient.post('/api/utilities/misc/rebin/logarithmic', {
      x: params.x,
      y: params.y,
      factor: params.factor,
      y_error: params.y_error ?? null,
      dx: params.dx ?? null,
    });
  },

  async estimateBaseline(params: BaselineParams): Promise<ApiResponse<BaselineData>> {
    return apiClient.post('/api/utilities/misc/baseline', params);
  },

  async generateWindow(params: {
    n_samples: number;
    window_type: string;
  }): Promise<ApiResponse<WindowData>> {
    return apiClient.post('/api/utilities/misc/window', params);
  },

  async optimalBinTime(params: {
    fft_length: number;
    proposed_bin_time: number;
  }): Promise<ApiResponse<OptimalBinTimeData>> {
    return apiClient.post('/api/utilities/misc/sampling/optimal-bin-time', params);
  },

  async nearestPowerOfTwo(params: {
    value: number;
  }): Promise<ApiResponse<NearestPowerOfTwoData>> {
    return apiClient.post('/api/utilities/misc/sampling/nearest-power-of-two', params);
  },

  async adjustSegmentSize(params: {
    segment_size: number;
    dt: number;
    tolerance: number;
  }): Promise<ApiResponse<SegmentSizeData>> {
    return apiClient.post('/api/utilities/misc/sampling/segment-size', params);
  },

  async poissonErrors(params: {
    counts: number[];
  }): Promise<ApiResponse<PoissonErrorData>> {
    return apiClient.post('/api/utilities/misc/errors/poisson', params);
  },

  async standardError(params: {
    samples: number[][];
    mean?: number[] | null;
  }): Promise<ApiResponse<StandardErrorData>> {
    return apiClient.post('/api/utilities/misc/errors/standard', {
      samples: params.samples,
      mean: params.mean ?? null,
    });
  },

  async equalCountEnergyRanges(
    params: EnergyRangesParams
  ): Promise<ApiResponse<EnergyRangesData>> {
    return apiClient.post('/api/utilities/misc/energy-ranges', {
      n_ranges: params.n_ranges,
      energies: 'energies' in params ? params.energies : null,
      event_list_name: 'event_list_name' in params ? params.event_list_name : null,
      energy_min: params.energy_min ?? null,
      energy_max: params.energy_max ?? null,
      energy_unit: params.energy_unit,
    });
  },
};

export default miscApi;
