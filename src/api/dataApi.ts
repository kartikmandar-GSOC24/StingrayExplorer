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
  ram_usage_percent?: number;
  memory_info?: MemoryInfo;
}

// Lazy loading types
export interface LazyLoadingInfo {
  method: 'time_range' | 'event_count';
  // For time_range method
  requested_range?: [number, number];
  actual_range?: [number, number];
  loaded_duration?: number;
  // For event_count method
  start_index?: number;
  end_index?: number;
  events_requested?: number;
  events_loaded?: number;
  // Common fields
  total_file_duration: number;
  total_file_events: number;
  events_loaded_percent: number;
}

export interface EventListLazyLoadedSummary extends EventListSummary {
  lazy_loading_info?: LazyLoadingInfo;
}

export interface LoadingRecommendation {
  can_load_full: boolean;
  recommend_lazy: boolean;
  suggested_chunk_size: number | null;
  suggested_time_chunk: number | null;
  strategy: 'full' | 'time_range' | 'event_count';
}

export interface FileMetadata {
  file_path: string;
  file_size_mb: number;
  file_size_gb: number;
  risk_level: 'safe' | 'caution' | 'risky' | 'critical';
  total_events: number;
  time_range: [number | null, number | null];
  duration: number;
  gti_count: number;
  total_gti_time: number | null;
  gti_list: [number, number][] | null;
  mjdref: number | null;
  mission: string | null;
  instrument: string | null;
  available_columns: string[];
  recommended_loading: LoadingRecommendation;
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
    high_precision?: boolean;
    skip_checks?: boolean;
  }): Promise<ApiResponse<EventListSummary>> {
    return apiClient.post('/api/data/load', {
      file_path: params.file_path,
      name: params.name,
      fmt: params.fmt || 'ogip',
      rmf_file: params.rmf_file,
      additional_columns: params.additional_columns,
      high_precision: params.high_precision || false,
      skip_checks: params.skip_checks || false,
    });
  },

  /**
   * Load an EventList from a URL
   */
  async loadEventListFromUrl(params: {
    url: string;
    name: string;
    fmt?: string;
    rmf_file?: string;
    additional_columns?: string[];
    high_precision?: boolean;
    skip_checks?: boolean;
  }): Promise<ApiResponse<EventListSummary>> {
    return apiClient.post('/api/data/load-url', {
      url: params.url,
      name: params.name,
      fmt: params.fmt || 'ogip',
      rmf_file: params.rmf_file,
      additional_columns: params.additional_columns,
      high_precision: params.high_precision || false,
      skip_checks: params.skip_checks || false,
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
   * Get full preview of an EventList with all attributes
   */
  async getEventListFullPreview(
    name: string,
    timeLimit?: number
  ): Promise<ApiResponse<EventListFullPreview>> {
    const params = timeLimit ? `?time_limit=${timeLimit}` : '';
    return apiClient.get(`/api/data/${name}/full-preview${params}`);
  },

  // =========================================================================
  // TRUE LAZY LOADING API FUNCTIONS
  // These use FITSTimeseriesReader for genuine lazy/streaming I/O
  // =========================================================================

  /**
   * Load events within a specific time range using true lazy loading.
   * Only reads the events within the time window from disk.
   */
  async loadEventListByTimeRange(params: {
    file_path: string;
    name: string;
    start_time: number;
    end_time: number;
    fmt?: string;
  }): Promise<ApiResponse<EventListLazyLoadedSummary>> {
    return apiClient.post('/api/data/load-by-time-range', {
      file_path: params.file_path,
      name: params.name,
      start_time: params.start_time,
      end_time: params.end_time,
      fmt: params.fmt || 'ogip',
    });
  },

  /**
   * Load a specific number of events using true lazy loading.
   * Only reads the requested event range from disk.
   */
  async loadEventListByEventCount(params: {
    file_path: string;
    name: string;
    start_index?: number;
    count?: number;
    fmt?: string;
  }): Promise<ApiResponse<EventListLazyLoadedSummary>> {
    return apiClient.post('/api/data/load-by-event-count', {
      file_path: params.file_path,
      name: params.name,
      start_index: params.start_index ?? 0,
      count: params.count ?? 10000,
      fmt: params.fmt || 'ogip',
    });
  },

  /**
   * Get file metadata without loading the full data.
   * Returns event count, time range, GTI, and loading recommendations.
   */
  async getFileMetadata(params: {
    file_path: string;
    fmt?: string;
  }): Promise<ApiResponse<FileMetadata>> {
    return apiClient.post('/api/data/metadata', {
      file_path: params.file_path,
      fmt: params.fmt || 'ogip',
    });
  },
};

export default dataApi;
