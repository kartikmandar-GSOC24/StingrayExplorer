/**
 * API functions for EventList data operations
 */

import { apiClient, ApiResponse } from './client';

// Types

/** Validation check result from data quality checks */
export interface ValidationIssue {
  type: string;
  name?: string;
  description?: string;
  status: 'pass' | 'fail' | 'skip';
  severity: 'error' | 'warning' | 'pass' | 'skip';
  message: string;
  count?: number;
  total?: number;
}

/** Per-GTI rate information */
export interface PerGtiRate {
  start: number;
  stop: number;
  events: number;
  duration: number;
  rate: number;
}

/** FITS header information extracted from the event file */
export interface FitsHeaderInfo {
  object?: string;
  obs_id?: string;
  ra_nom?: number;
  dec_nom?: number;
  ra_obj?: number;
  dec_obj?: number;
  exposure?: number;
  ontime?: number;
  livetime?: number;
  date_obs?: string;
  date_end?: string;
  tstart?: number;
  tstop?: number;
  creator?: string;
  telescop?: string;
  instrume?: string;
  datamode?: string;
  observer?: string;
  raw_header?: Record<string, string>;
}

export interface EventListSummary {
  name: string;
  n_events: number;
  time_range: [number, number];
  has_energy?: boolean;
  has_pi?: boolean;
  gti_count?: number;
  gti_warnings?: string[] | null;
  stingray_warnings?: string[] | null;
  validation_issues?: ValidationIssue[] | null;
  notes?: string | null;
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
  mean_time_diff?: number;
  median_time_diff?: number;
  std_time_diff?: number;
  // Per-GTI rates
  per_gti_rates?: PerGtiRate[];
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
  // These are inherited from EventListSummary but explicitly listed for clarity:
  // validation_issues?: ValidationIssue[] | null;
  // notes?: string | null;
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

// Batch loading types
export interface SingleFileConfig {
  file_path: string;
  name: string;
  fmt?: string;
  rmf_file?: string;
  additional_columns?: string[];
  high_precision?: boolean;
  skip_checks?: boolean;
  use_partial_loading?: boolean;
  partial_mode?: 'time_range' | 'event_count';
  time_range_start?: number;
  time_range_end?: number;
  event_start_index?: number;
  event_count?: number;
  notes?: string;
}

export interface BatchLoadRequest {
  files: SingleFileConfig[];
  use_same_settings: boolean;
  // Shared settings (used when use_same_settings=true)
  shared_fmt?: string;
  shared_rmf_file?: string;
  shared_additional_columns?: string[];
  shared_high_precision?: boolean;
  shared_skip_checks?: boolean;
  shared_use_partial_loading?: boolean;
  shared_partial_mode?: 'time_range' | 'event_count';
  shared_time_range_start?: number;
  shared_time_range_end?: number;
  shared_event_start_index?: number;
  shared_event_count?: number;
}

export interface BatchLoadSuccessItem {
  name: string;
  file_path: string;
  data: EventListSummary | null;
  message?: string;
}

export interface BatchLoadFailedItem {
  name: string;
  file_path: string;
  error: string;
}

export interface BatchLoadSummary {
  total_files: number;
  success_count: number;
  failure_count: number;
  total_events_loaded: number;
  total_time_ms: number;
  workers_used: number;
}

export interface BatchLoadResult {
  successful: BatchLoadSuccessItem[];
  failed: BatchLoadFailedItem[];
  summary: BatchLoadSummary;
}

export interface BatchFileSizeInfo {
  file_path: string;
  file_name: string;
  size_mb: number;
  estimated_ram_mb: number;
  ram_percent: number;
  risk_level: 'safe' | 'caution' | 'risky' | 'critical';
  error?: string;
}

export interface BatchSizeTotals {
  size_mb: number;
  estimated_ram_mb: number;
  ram_percent: number;
  risk_level: 'safe' | 'caution' | 'risky' | 'critical';
}

export interface BatchSizeResult {
  files: BatchFileSizeInfo[];
  total: BatchSizeTotals;
  available_ram_mb: number;
  file_count: number;
  recommend_partial_loading: boolean;
}

// SSE Streaming types for batch loading
export interface BatchStreamEventFileComplete {
  type: 'file_complete';
  name: string;
  file_path: string;
  success: boolean;
  completed: number;
  total: number;
  data?: EventListSummary;
  error?: string;
}

export interface BatchStreamEventComplete {
  type: 'complete';
  total_time_ms: number;
  success_count: number;
  failure_count: number;
  total_events: number;
  workers_used: number;
}

export interface BatchStreamEventError {
  type: 'error';
  error: string;
}

export type BatchStreamEvent =
  | BatchStreamEventFileComplete
  | BatchStreamEventComplete
  | BatchStreamEventError;

// URL Download SSE Streaming types
export interface UrlDownloadProgressEvent {
  type: 'progress';
  bytes_downloaded: number;
  total_bytes: number;
  percent: number;
}

export interface UrlDownloadProcessingEvent {
  type: 'processing';
  message: string;
}

export interface UrlDownloadCompleteEvent {
  type: 'complete';
  data: EventListSummary;
  message: string;
}

export interface UrlDownloadErrorEvent {
  type: 'error';
  error: string;
}

export type UrlDownloadStreamEvent =
  | UrlDownloadProgressEvent
  | UrlDownloadProcessingEvent
  | UrlDownloadCompleteEvent
  | UrlDownloadErrorEvent;

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
  // Enhanced time statistics
  median_time_diff?: number | null;
  std_time_diff?: number | null;
  // Per-GTI rates
  per_gti_rates?: PerGtiRate[] | null;
  // Additional columns
  additional_columns: string[];
  // User notes
  notes?: string | null;
  // Data validation
  validation_issues?: ValidationIssue[] | null;
  // FITS header information
  header_info?: FitsHeaderInfo | null;
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
    notes?: string;
  }): Promise<ApiResponse<EventListSummary>> {
    return apiClient.post('/api/data/load', {
      file_path: params.file_path,
      name: params.name,
      fmt: params.fmt || 'ogip',
      rmf_file: params.rmf_file,
      additional_columns: params.additional_columns,
      high_precision: params.high_precision || false,
      skip_checks: params.skip_checks || false,
      notes: params.notes,
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
    notes?: string;
  }): Promise<ApiResponse<EventListSummary>> {
    return apiClient.post('/api/data/load-url', {
      url: params.url,
      name: params.name,
      fmt: params.fmt || 'ogip',
      rmf_file: params.rmf_file,
      additional_columns: params.additional_columns,
      high_precision: params.high_precision || false,
      skip_checks: params.skip_checks || false,
      notes: params.notes,
    });
  },

  /**
   * Load an EventList from a URL with SSE streaming for progress updates.
   *
   * This function returns an async generator that yields UrlDownloadStreamEvent
   * objects as the download progresses. This allows the UI to show real-time
   * download progress.
   *
   * @param params - URL loading parameters
   * @yields UrlDownloadStreamEvent - Progress, processing, complete, or error events
   */
  async *loadEventListFromUrlSSE(params: {
    url: string;
    name: string;
    fmt?: string;
    rmf_file?: string;
    additional_columns?: string[];
    high_precision?: boolean;
    skip_checks?: boolean;
    notes?: string;
  }): AsyncGenerator<UrlDownloadStreamEvent, void, unknown> {
    const port = await apiClient.getPort();
    const url = `http://127.0.0.1:${port}/api/data/load-url-stream`;

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: params.url,
        name: params.name,
        fmt: params.fmt || 'ogip',
        rmf_file: params.rmf_file,
        additional_columns: params.additional_columns,
        high_precision: params.high_precision || false,
        skip_checks: params.skip_checks || false,
        notes: params.notes,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body available for streaming');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE format: "data: {...}\n\n"
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            try {
              const event = JSON.parse(jsonStr) as UrlDownloadStreamEvent;
              yield event;
            } catch (parseError) {
              console.error('Failed to parse SSE event:', parseError, jsonStr);
            }
          }
        }
      }

      // Process remaining buffer
      if (buffer.trim() && buffer.startsWith('data: ')) {
        const jsonStr = buffer.slice(6).trim();
        if (jsonStr) {
          try {
            const event = JSON.parse(jsonStr) as UrlDownloadStreamEvent;
            yield event;
          } catch (parseError) {
            console.error('Failed to parse final SSE event:', parseError, jsonStr);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
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
      fmt: params.fmt || 'hdf5',
    });
  },

  /**
   * Delete an EventList from state
   */
  async deleteEventList(name: string): Promise<ApiResponse<{ name: string }>> {
    return apiClient.delete(`/api/data/${encodeURIComponent(name)}`);
  },

  /**
   * Get information about an EventList
   */
  async getEventListInfo(name: string): Promise<ApiResponse<EventListInfo>> {
    return apiClient.get(`/api/data/${encodeURIComponent(name)}`);
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
    return apiClient.get(`/api/data/${encodeURIComponent(name)}/full-preview${params}`);
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
    notes?: string;
  }): Promise<ApiResponse<EventListLazyLoadedSummary>> {
    return apiClient.post('/api/data/load-by-time-range', {
      file_path: params.file_path,
      name: params.name,
      start_time: params.start_time,
      end_time: params.end_time,
      fmt: params.fmt || 'ogip',
      notes: params.notes,
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
    notes?: string;
  }): Promise<ApiResponse<EventListLazyLoadedSummary>> {
    return apiClient.post('/api/data/load-by-event-count', {
      file_path: params.file_path,
      name: params.name,
      start_index: params.start_index ?? 0,
      count: params.count ?? 10000,
      fmt: params.fmt || 'ogip',
      notes: params.notes,
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

  // =========================================================================
  // BATCH LOADING API FUNCTIONS
  // Load multiple files in parallel
  // =========================================================================

  /**
   * Check sizes of multiple files and estimate total memory usage.
   * Returns per-file and total memory estimates with risk levels.
   */
  async checkBatchFileSize(
    file_paths: string[]
  ): Promise<ApiResponse<BatchSizeResult>> {
    return apiClient.post('/api/data/check-batch-size', { file_paths });
  },

  /**
   * Load multiple EventLists in parallel using threads.
   *
   * @param params.files - Array of file configurations
   * @param params.use_same_settings - If true, use shared_* settings for all files
   * @param params.shared_* - Shared settings applied when use_same_settings=true
   */
  async loadBatchEventLists(
    params: BatchLoadRequest
  ): Promise<ApiResponse<BatchLoadResult>> {
    return apiClient.post('/api/data/load-batch', {
      files: params.files,
      use_same_settings: params.use_same_settings,
      shared_fmt: params.shared_fmt || 'ogip',
      shared_rmf_file: params.shared_rmf_file,
      shared_additional_columns: params.shared_additional_columns,
      shared_high_precision: params.shared_high_precision || false,
      shared_skip_checks: params.shared_skip_checks || false,
      shared_use_partial_loading: params.shared_use_partial_loading || false,
      shared_partial_mode: params.shared_partial_mode || 'time_range',
      shared_time_range_start: params.shared_time_range_start,
      shared_time_range_end: params.shared_time_range_end,
      shared_event_start_index: params.shared_event_start_index,
      shared_event_count: params.shared_event_count,
    });
  },

  /**
   * Load multiple EventLists with SSE streaming for real-time progress.
   *
   * This function returns an async generator that yields BatchStreamEvent
   * objects as each file completes loading. This allows the UI to update
   * immediately when each file finishes rather than waiting for all files.
   *
   * @param params - Same parameters as loadBatchEventLists
   * @yields BatchStreamEvent - Events for each file completion and final summary
   */
  async *loadBatchEventListsSSE(
    params: BatchLoadRequest
  ): AsyncGenerator<BatchStreamEvent, void, unknown> {
    const port = await apiClient.getPort();
    const url = `http://127.0.0.1:${port}/api/data/load-batch-stream`;

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        files: params.files,
        use_same_settings: params.use_same_settings,
        shared_fmt: params.shared_fmt || 'ogip',
        shared_rmf_file: params.shared_rmf_file,
        shared_additional_columns: params.shared_additional_columns,
        shared_high_precision: params.shared_high_precision || false,
        shared_skip_checks: params.shared_skip_checks || false,
        shared_use_partial_loading: params.shared_use_partial_loading || false,
        shared_partial_mode: params.shared_partial_mode || 'time_range',
        shared_time_range_start: params.shared_time_range_start,
        shared_time_range_end: params.shared_time_range_end,
        shared_event_start_index: params.shared_event_start_index,
        shared_event_count: params.shared_event_count,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body available for streaming');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE format: "data: {...}\n\n"
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || ''; // Keep incomplete chunk

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            try {
              const event = JSON.parse(jsonStr) as BatchStreamEvent;
              yield event;
            } catch (parseError) {
              console.error('Failed to parse SSE event:', parseError, jsonStr);
            }
          }
        }
      }

      // Process any remaining data in the buffer
      if (buffer.trim() && buffer.startsWith('data: ')) {
        const jsonStr = buffer.slice(6).trim();
        if (jsonStr) {
          try {
            const event = JSON.parse(jsonStr) as BatchStreamEvent;
            yield event;
          } catch (parseError) {
            console.error('Failed to parse final SSE event:', parseError, jsonStr);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};

export default dataApi;
