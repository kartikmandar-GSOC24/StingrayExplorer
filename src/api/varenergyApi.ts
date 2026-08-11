/**
 * API functions for variability-vs-energy spectra (rms, lag, excess variance,
 * variable-energy composite, covariance / averaged covariance).
 */

import { apiClient, ApiResponse } from './client';

// Types

export interface RmsSpectrumData {
  energy: number[];
  spectrum: Array<number | null>;
  spectrum_error: Array<number | null>;
  freq_range: [number, number];
  norm: string;
  n_segments_hint: number;
  warnings: string[];
}

export interface LagSpectrumData {
  energy: number[];
  spectrum: Array<number | null>;
  spectrum_error: Array<number | null>;
  freq_range: [number, number];
  ref_band: [number, number] | null;
  n_segments_hint: number;
  warnings: string[];
}

export interface ExcessVarianceData {
  energy: number[];
  spectrum: Array<number | null>;
  spectrum_error: Array<number | null>;
  normalization: string;
  warnings: string[];
}

/** One panel (counts / rms / lag) of the VariableEnergySpectrum composite. */
export interface VarEnergyBand {
  spectrum: Array<number | null>;
  error: Array<number | null>;
}

export interface VariableEnergySpectrumData {
  energy: number[];
  counts: VarEnergyBand;
  rms: VarEnergyBand;
  lag: VarEnergyBand;
  freq_range: [number, number];
  ref_band: [number, number] | null;
  norm: string;
  n_segments_hint: number;
  warnings: string[];
}

/**
 * Shared shape for both /covariance-spectrum (n_segments_hint always 1, one
 * segment spanning the longest GTI) and /avg-covariance-spectrum
 * (segment_size is user-chosen; n_segments_hint = whole segments fitting the
 * GTIs).
 */
export interface CovarianceSpectrumData {
  energy: number[];
  spectrum: Array<number | null>;
  spectrum_error: Array<number | null>;
  freq_range: [number, number];
  ref_band: [number, number] | null;
  norm: string;
  segment_size: number;
  n_segments_hint: number;
  // GTI accounting: segments start at GTI boundaries, so GTIs shorter than
  // segment_size contribute nothing; when n_gtis_used < n_gtis_total the
  // backend also appends a warning naming the skipped exposure.
  n_gtis_total?: number;
  n_gtis_used?: number;
  exposure_total?: number;
  exposure_used?: number;
  warnings: string[];
}

// API functions
export const varenergyApi = {
  /**
   * Fractional/absolute rms vs energy. No ref_band field: it is silently
   * inert for RmsSpectrum on a single EventList.
   */
  async rmsSpectrum(params: {
    event_list_name: string;
    bin_time: number;
    segment_size: number;
    freq_min: number;
    freq_max: number;
    energy_min: number;
    energy_max: number;
    n_bands?: number;
    log_bands?: boolean;
    norm?: string;
  }): Promise<ApiResponse<RmsSpectrumData>> {
    return apiClient.post('/api/varenergy/rms-spectrum', {
      event_list_name: params.event_list_name,
      bin_time: params.bin_time,
      segment_size: params.segment_size,
      freq_min: params.freq_min,
      freq_max: params.freq_max,
      energy_min: params.energy_min,
      energy_max: params.energy_max,
      n_bands: params.n_bands ?? 5,
      log_bands: params.log_bands ?? false,
      norm: params.norm ?? 'frac',
    });
  },

  /**
   * Lag (seconds) vs energy, optionally against an explicit reference band.
   * ref_min/ref_max must be given together or not at all.
   */
  async lagSpectrum(params: {
    event_list_name: string;
    bin_time: number;
    segment_size: number;
    freq_min: number;
    freq_max: number;
    energy_min: number;
    energy_max: number;
    n_bands?: number;
    log_bands?: boolean;
    ref_min?: number | null;
    ref_max?: number | null;
  }): Promise<ApiResponse<LagSpectrumData>> {
    return apiClient.post('/api/varenergy/lag-spectrum', {
      event_list_name: params.event_list_name,
      bin_time: params.bin_time,
      segment_size: params.segment_size,
      freq_min: params.freq_min,
      freq_max: params.freq_max,
      energy_min: params.energy_min,
      energy_max: params.energy_max,
      n_bands: params.n_bands ?? 5,
      log_bands: params.log_bands ?? false,
      ref_min: params.ref_min ?? null,
      ref_max: params.ref_max ?? null,
    });
  },

  /**
   * Excess variance vs energy. No freq_min/freq_max/segment_size: stingray's
   * ExcessVarianceSpectrum ignores all three (see backend contract notes).
   */
  async excessVariance(params: {
    event_list_name: string;
    bin_time: number;
    energy_min: number;
    energy_max: number;
    n_bands?: number;
    log_bands?: boolean;
    normalization?: string;
  }): Promise<ApiResponse<ExcessVarianceData>> {
    return apiClient.post('/api/varenergy/excess-variance', {
      event_list_name: params.event_list_name,
      bin_time: params.bin_time,
      energy_min: params.energy_min,
      energy_max: params.energy_max,
      n_bands: params.n_bands ?? 5,
      log_bands: params.log_bands ?? false,
      normalization: params.normalization ?? 'fvar',
    });
  },

  /**
   * Composite endpoint: counts + rms + lag panels vs energy from shared
   * parameters. No norm field: rms is always fractional. ref_band affects
   * the lag panel only.
   */
  async variableEnergySpectrum(params: {
    event_list_name: string;
    bin_time: number;
    segment_size: number;
    freq_min: number;
    freq_max: number;
    energy_min: number;
    energy_max: number;
    n_bands?: number;
    log_bands?: boolean;
    ref_min?: number | null;
    ref_max?: number | null;
  }): Promise<ApiResponse<VariableEnergySpectrumData>> {
    return apiClient.post('/api/varenergy/variable-energy-spectrum', {
      event_list_name: params.event_list_name,
      bin_time: params.bin_time,
      segment_size: params.segment_size,
      freq_min: params.freq_min,
      freq_max: params.freq_max,
      energy_min: params.energy_min,
      energy_max: params.energy_max,
      n_bands: params.n_bands ?? 5,
      log_bands: params.log_bands ?? false,
      ref_min: params.ref_min ?? null,
      ref_max: params.ref_max ?? null,
    });
  },

  /**
   * Unsegmented covariance spectrum: one segment spanning the longest GTI
   * (n_segments_hint is always 1). No segment_size field — it is derived
   * server-side.
   */
  async covarianceSpectrum(params: {
    event_list_name: string;
    bin_time: number;
    freq_min: number;
    freq_max: number;
    energy_min: number;
    energy_max: number;
    n_bands?: number;
    log_bands?: boolean;
    ref_min?: number | null;
    ref_max?: number | null;
    norm?: string;
  }): Promise<ApiResponse<CovarianceSpectrumData>> {
    return apiClient.post('/api/varenergy/covariance-spectrum', {
      event_list_name: params.event_list_name,
      bin_time: params.bin_time,
      freq_min: params.freq_min,
      freq_max: params.freq_max,
      energy_min: params.energy_min,
      energy_max: params.energy_max,
      n_bands: params.n_bands ?? 5,
      log_bands: params.log_bands ?? false,
      ref_min: params.ref_min ?? null,
      ref_max: params.ref_max ?? null,
      norm: params.norm ?? 'abs',
    });
  },

  /**
   * Segmented (averaged) covariance spectrum: identical contract to
   * covarianceSpectrum plus a required segment_size.
   */
  async avgCovarianceSpectrum(params: {
    event_list_name: string;
    bin_time: number;
    segment_size: number;
    freq_min: number;
    freq_max: number;
    energy_min: number;
    energy_max: number;
    n_bands?: number;
    log_bands?: boolean;
    ref_min?: number | null;
    ref_max?: number | null;
    norm?: string;
  }): Promise<ApiResponse<CovarianceSpectrumData>> {
    return apiClient.post('/api/varenergy/avg-covariance-spectrum', {
      event_list_name: params.event_list_name,
      bin_time: params.bin_time,
      segment_size: params.segment_size,
      freq_min: params.freq_min,
      freq_max: params.freq_max,
      energy_min: params.energy_min,
      energy_max: params.energy_max,
      n_bands: params.n_bands ?? 5,
      log_bands: params.log_bands ?? false,
      ref_min: params.ref_min ?? null,
      ref_max: params.ref_max ?? null,
      norm: params.norm ?? 'abs',
    });
  },
};

export default varenergyApi;
