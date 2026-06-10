/**
 * API functions for Lightcurve operations
 */

import { apiClient, ApiResponse } from './client';

// Types
export interface LightcurveData {
  name: string;
  time: number[];
  counts: number[];
  dt: number;
  n_bins: number;
  plot_stride?: number;
  time_range?: [number, number];
  count_rate_mean?: number;
  count_stats?: {
    mean: number;
    std: number;
    min: number;
    max: number;
  };
}

export interface LightcurveSummary {
  name: string;
  n_bins: number;
  dt: number;
  time_range: [number, number];
}

// API functions
export const lightcurveApi = {
  /**
   * Create a Lightcurve from an EventList
   */
  async createFromEventList(params: {
    event_list_name: string;
    dt: number;
    output_name: string;
    gti?: number[][];
    max_points?: number;
  }): Promise<ApiResponse<LightcurveData>> {
    return apiClient.post('/api/lightcurve/from-event-list', {
      event_list_name: params.event_list_name,
      dt: params.dt,
      output_name: params.output_name,
      gti: params.gti,
      max_points: params.max_points,
    });
  },

  /**
   * Create a Lightcurve from arrays
   */
  async createFromArrays(params: {
    times: number[];
    counts: number[];
    dt: number;
    output_name: string;
  }): Promise<ApiResponse<LightcurveData>> {
    return apiClient.post('/api/lightcurve/from-arrays', params);
  },

  /**
   * Rebin a lightcurve
   */
  async rebin(params: {
    name: string;
    rebin_factor: number;
    output_name: string;
    max_points?: number;
  }): Promise<ApiResponse<LightcurveData>> {
    return apiClient.post('/api/lightcurve/rebin', {
      name: params.name,
      rebin_factor: params.rebin_factor,
      output_name: params.output_name,
      max_points: params.max_points,
    });
  },

  /**
   * Get lightcurve data for plotting
   */
  async getLightcurveData(
    name: string,
    maxPoints?: number
  ): Promise<ApiResponse<LightcurveData>> {
    const query = maxPoints ? `?max_points=${maxPoints}` : '';
    return apiClient.get(`/api/lightcurve/${name}${query}`);
  },

  /**
   * List all loaded lightcurves
   */
  async listLightcurves(): Promise<ApiResponse<LightcurveSummary[]>> {
    return apiClient.get('/api/lightcurve/');
  },

  /**
   * Delete a lightcurve from state
   */
  async deleteLightcurve(name: string): Promise<ApiResponse<{ name: string }>> {
    return apiClient.delete(`/api/lightcurve/${name}`);
  },
};

export default lightcurveApi;
