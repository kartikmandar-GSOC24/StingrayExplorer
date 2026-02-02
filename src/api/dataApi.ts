/**
 * API functions for EventList data operations
 */

import { apiClient, ApiResponse } from './client';

// Types
export interface EventListSummary {
  name: string;
  n_events: number;
  time_range: [number, number];
  has_energy?: boolean;
  has_pi?: boolean;
  gti_count?: number;
  gti_warnings?: string[] | null;
}

export interface EventListInfo extends EventListSummary {
  duration: number;
  mjdref: number | null;
  // GTI details
  gti_list?: [number, number][];
  total_gti_time?: number;
  // Energy/PI range
  energy_range?: [number, number];
  pi_range?: [number, number];
  // Mission metadata
  mission?: string;
  instrument?: string;
  // Time statistics
  mean_count_rate?: number;
  min_time_diff?: number;
  max_time_diff?: number;
}

export interface MemoryInfo {
  total_mb: number;
  available_mb: number;
  used_mb: number;
  percent: number;
  process_mb: number;
}

export interface FileSizeInfo {
  file_size_bytes: number;
  file_size_mb: number;
  file_size_gb: number;
  risk_level: 'safe' | 'caution' | 'risky' | 'critical';
  recommend_lazy: boolean;
  estimated_memory_mb?: number;
  memory_info?: MemoryInfo;
}

export interface LoadingInfo {
  method: 'standard' | 'standard_risky';
  file_size_mb: number;
  file_size_gb: number;
  estimated_memory_mb: number;
  memory_safe: boolean;
  available_memory_mb: number;
}

export interface EventListLazySummary extends EventListSummary {
  loading_info?: LoadingInfo;
}

export interface PreviewInfo {
  preview_duration: number;
  total_duration: number;
  file_size_mb: number;
  is_preview: boolean;
}

export interface EventListPreviewSummary extends EventListSummary {
  preview_info?: PreviewInfo;
}

export interface EventListFullPreview {
  name: string;
  // Core data
  times_preview: number[];
  n_events: number;
  time_range: [number, number];
  duration: number;
  // Energy data
  has_energy: boolean;
  energy_preview: number[] | null;
  energy_range: [number, number] | null;
  // PI data
  has_pi: boolean;
  pi_preview: number[] | null;
  pi_range: [number, number] | null;
  // GTI data
  gti_count: number;
  gti_list: [number, number][] | null;
  total_gti_time: number | null;
  // Reference time
  mjdref: number | null;
  // Metadata
  mission: string | null;
  instrument: string | null;
  detector_id: string | null;
  ephem: string | null;
  timeref: string | null;
  timesys: string | null;
  // Statistics
  mean_count_rate: number | null;
  min_time_diff: number | null;
  max_time_diff: number | null;
  mean_time_diff?: number | null;
  // Additional columns
  additional_columns: string[];
}

// API functions
export const dataApi = {
  /**
   * Load an EventList from a file
   */
  async loadEventList(params: {
    file_path: string;
    name: string;
    fmt?: string;
    rmf_file?: string;
    additional_columns?: string[];
  }): Promise<ApiResponse<EventListSummary>> {
    return apiClient.post('/api/data/load', {
      file_path: params.file_path,
      name: params.name,
      fmt: params.fmt || 'ogip',
      rmf_file: params.rmf_file,
      additional_columns: params.additional_columns,
    });
  },

  /**
   * Load an EventList from a URL
   */
  async loadEventListFromUrl(params: {
    url: string;
    name: string;
    fmt?: string;
  }): Promise<ApiResponse<EventListSummary>> {
    return apiClient.post('/api/data/load-url', {
      url: params.url,
      name: params.name,
      fmt: params.fmt || 'ogip',
    });
  },

  /**
   * Save an EventList to disk
   */
  async saveEventList(params: {
    name: string;
    file_path: string;
    fmt?: string;
  }): Promise<ApiResponse<{ file_path: string }>> {
    return apiClient.post('/api/data/save', {
      name: params.name,
      file_path: params.file_path,
      fmt: params.fmt || 'ogip',
    });
  },

  /**
   * Delete an EventList from state
   */
  async deleteEventList(name: string): Promise<ApiResponse<{ name: string }>> {
    return apiClient.delete(`/api/data/${name}`);
  },

  /**
   * Get information about an EventList
   */
  async getEventListInfo(name: string): Promise<ApiResponse<EventListInfo>> {
    return apiClient.get(`/api/data/${name}`);
  },

  /**
   * List all loaded EventLists
   */
  async listEventLists(): Promise<ApiResponse<EventListSummary[]>> {
    return apiClient.get('/api/data/');
  },

  /**
   * Check file size and get loading recommendations
   */
  async checkFileSize(file_path: string): Promise<ApiResponse<FileSizeInfo>> {
    return apiClient.post('/api/data/check-size', { file_path });
  },

  /**
   * Clear all loaded EventLists from memory
   */
  async clearAllEventLists(): Promise<ApiResponse<{ count: number }>> {
    return apiClient.delete('/api/data/');
  },

  /**
   * Load an EventList using lazy loading for large files
   */
  async loadEventListLazy(params: {
    file_path: string;
    name: string;
    fmt?: string;
    rmf_file?: string;
    additional_columns?: string[];
    safety_margin?: number;
  }): Promise<ApiResponse<EventListLazySummary>> {
    return apiClient.post('/api/data/load-lazy', {
      file_path: params.file_path,
      name: params.name,
      fmt: params.fmt || 'ogip',
      rmf_file: params.rmf_file,
      additional_columns: params.additional_columns,
      safety_margin: params.safety_margin ?? 0.5,
    });
  },

  /**
   * Load only the first segment of a large file as a preview
   */
  async loadEventListPreview(params: {
    file_path: string;
    name: string;
    preview_duration?: number;
    fmt?: string;
  }): Promise<ApiResponse<EventListPreviewSummary>> {
    return apiClient.post('/api/data/load-preview', {
      file_path: params.file_path,
      name: params.name,
      preview_duration: params.preview_duration ?? 100.0,
      fmt: params.fmt || 'ogip',
    });
  },

  /**
   * Get full preview of an EventList with all attributes
   */
  async getEventListFullPreview(
    name: string,
    timeLimit?: number
  ): Promise<ApiResponse<EventListFullPreview>> {
    const params = timeLimit ? `?time_limit=${timeLimit}` : '';
    return apiClient.get(`/api/data/${name}/full-preview${params}`);
  },
};

export default dataApi;
