/**
 * API functions for timing analysis operations
 */

import { apiClient, ApiResponse } from './client';

// Types
export interface BispectrumData {
  name: string | null;
  freq: number[];
  lags: number[];
  bispec_mag: number[][];
  bispec_phase: number[][];
  cum3: number[][];
  maxlag: number;
  scale: string;
  window: string;
}

export interface PowerColorsData {
  name: string | null;
  power_colors: Record<string, Array<number | null>>;
  time: number[];
  freq_ranges: Record<string, [number, number]>;
}

export interface TimeLagsData {
  name: string | null;
  freq: number[];
  time_lags: Array<number | null>;
  time_lags_err?: Array<number | null> | null;
  freq_range: [number, number] | null;
}

export interface CoherenceData {
  name: string | null;
  freq: number[];
  coherence: Array<number | null>;
  coherence_err?: Array<number | null> | null;
  segment_size?: number;
  n_segments?: number | null;
}

// API functions
export const timingApi = {
  /**
   * Create a bispectrum from an EventList
   */
  async createBispectrum(params: {
    event_list_name: string;
    dt: number;
    maxlag?: number;
    scale?: string;
    window?: string;
    output_name?: string;
  }): Promise<ApiResponse<BispectrumData>> {
    return apiClient.post('/api/timing/bispectrum', {
      event_list_name: params.event_list_name,
      dt: params.dt,
      maxlag: params.maxlag || 25,
      scale: params.scale || 'unbiased',
      window: params.window || 'uniform',
      output_name: params.output_name,
    });
  },

  /**
   * Calculate power colors from frequency bands
   */
  async calculatePowerColors(params: {
    event_list_name: string;
    dt: number;
    segment_size: number;
    freq_ranges: Record<string, [number, number]>;
    output_name?: string;
  }): Promise<ApiResponse<PowerColorsData>> {
    return apiClient.post('/api/timing/power-colors', {
      event_list_name: params.event_list_name,
      dt: params.dt,
      segment_size: params.segment_size,
      freq_ranges: params.freq_ranges,
      output_name: params.output_name,
    });
  },

  /**
   * Calculate time lags between two event lists
   */
  async calculateTimeLags(params: {
    event_list_1_name: string;
    event_list_2_name: string;
    dt: number;
    segment_size: number;
    freq_range?: [number, number];
    output_name?: string;
  }): Promise<ApiResponse<TimeLagsData>> {
    return apiClient.post('/api/timing/time-lags', {
      event_list_1_name: params.event_list_1_name,
      event_list_2_name: params.event_list_2_name,
      dt: params.dt,
      segment_size: params.segment_size,
      freq_range: params.freq_range,
      output_name: params.output_name,
    });
  },

  /**
   * Calculate coherence between two event lists
   */
  async calculateCoherence(params: {
    event_list_1_name: string;
    event_list_2_name: string;
    dt: number;
    segment_size: number;
    output_name?: string;
  }): Promise<ApiResponse<CoherenceData>> {
    return apiClient.post('/api/timing/coherence', {
      event_list_1_name: params.event_list_1_name,
      event_list_2_name: params.event_list_2_name,
      dt: params.dt,
      segment_size: params.segment_size,
      output_name: params.output_name,
    });
  },
};

export default timingApi;
