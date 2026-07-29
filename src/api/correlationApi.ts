/**
 * API functions for correlation analysis operations (auto-correlation / cross-correlation)
 */

import { apiClient, ApiResponse } from './client';

// Types

/**
 * Shared response shape for both /api/correlation/auto-correlation and
 * /api/correlation/cross-correlation.
 *
 * Sign convention (cross-correlation only): time_shift > 0 means the first
 * event list lags the second; time_shift < 0 means the first list leads.
 * For auto-correlation the backend returns 0.0 (the peak is at zero lag by
 * construction) -- not null. time_shift is null only when corr contains NaN,
 * which can happen on either endpoint with norm='variance'.
 *
 * dt is the bin size actually used, which is always the dt requested: both
 * endpoints bin onto their own grid rather than going through
 * EventList.to_lc, which would snap dt to the instrument time resolution.
 */
export interface CorrelationData {
  time_lags: Array<number | null>;
  corr: Array<number | null>;
  time_shift: number | null;
  dt: number;
  n: number;
  mode: string;
  norm: string;
  warnings: string[];
}

// API functions
export const correlationApi = {
  /**
   * Compute the auto-correlation of a single event list.
   */
  async autoCorrelation(params: {
    event_list_name: string;
    dt: number;
    mode?: string;
    norm?: string;
  }): Promise<ApiResponse<CorrelationData>> {
    return apiClient.post('/api/correlation/auto-correlation', {
      event_list_name: params.event_list_name,
      dt: params.dt,
      mode: params.mode ?? 'same',
      norm: params.norm ?? 'none',
    });
  },

  /**
   * Compute the cross-correlation between two event lists.
   */
  async crossCorrelation(params: {
    event_list_1_name: string;
    event_list_2_name: string;
    dt: number;
    mode?: string;
    norm?: string;
  }): Promise<ApiResponse<CorrelationData>> {
    return apiClient.post('/api/correlation/cross-correlation', {
      event_list_1_name: params.event_list_1_name,
      event_list_2_name: params.event_list_2_name,
      dt: params.dt,
      mode: params.mode ?? 'same',
      norm: params.norm ?? 'none',
    });
  },
};

export default correlationApi;
