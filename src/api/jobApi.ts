/**
 * API functions for background job operations.
 */

import { apiClient, ApiResponse } from './client';
import type {
  Job,
  JobStreamEvent,
  NameConflictResult,
  SubmitLoadJobParams,
  SubmitBatchJobParams,
  SubmitUrlJobParams,
} from '@/types/job';

export const jobApi = {
  /**
   * Submit a single file load job.
   *
   * Returns immediately with the job ID. The actual loading happens
   * asynchronously in a background thread.
   */
  async submitLoadJob(params: SubmitLoadJobParams): Promise<ApiResponse<Job>> {
    return apiClient.post('/api/jobs/submit-load', {
      file_path: params.file_path,
      name: params.name,
      fmt: params.fmt || 'ogip',
      rmf_file: params.rmf_file,
      additional_columns: params.additional_columns,
      high_precision: params.high_precision || false,
      skip_checks: params.skip_checks || false,
      notes: params.notes,
      use_partial_loading: params.use_partial_loading || false,
      partial_mode: params.partial_mode || 'time_range',
      time_range_start: params.time_range_start,
      time_range_end: params.time_range_end,
      event_start_index: params.event_start_index,
      event_count: params.event_count,
    });
  },

  /**
   * Submit a batch load job for multiple files.
   *
   * Returns immediately with the job ID. The actual loading happens
   * asynchronously in a background thread.
   */
  async submitBatchJob(params: SubmitBatchJobParams): Promise<ApiResponse<Job>> {
    return apiClient.post('/api/jobs/submit-batch', {
      files: params.files,
      use_same_settings: params.use_same_settings ?? true,
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
   * Submit a URL download and load job.
   *
   * Returns immediately with the job ID. The actual download and loading
   * happens asynchronously in a background thread.
   */
  async submitUrlJob(params: SubmitUrlJobParams): Promise<ApiResponse<Job>> {
    return apiClient.post('/api/jobs/submit-url', {
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
   * List all jobs.
   *
   * @param includeCompleted - Include completed/failed/cancelled jobs
   * @param limit - Maximum number of jobs to return
   */
  async listJobs(
    includeCompleted: boolean = true,
    limit: number = 50
  ): Promise<ApiResponse<Job[]>> {
    return apiClient.get(
      `/api/jobs/?include_completed=${includeCompleted}&limit=${limit}`
    );
  },

  /**
   * Get all active (pending or running) jobs.
   */
  async getActiveJobs(): Promise<ApiResponse<Job[]>> {
    return apiClient.get('/api/jobs/active');
  },

  /**
   * Get a specific job by ID.
   */
  async getJob(jobId: string): Promise<ApiResponse<Job>> {
    return apiClient.get(`/api/jobs/${jobId}`);
  },

  /**
   * Cancel a pending job.
   *
   * Only pending jobs can be cancelled. Running jobs cannot be interrupted.
   */
  async cancelJob(jobId: string): Promise<ApiResponse<void>> {
    return apiClient.post(`/api/jobs/${jobId}/cancel`);
  },

  /**
   * Check if a name conflicts with existing data or pending jobs.
   */
  async checkNameConflict(name: string): Promise<ApiResponse<NameConflictResult>> {
    return apiClient.post('/api/jobs/check-name', { name });
  },

  /**
   * Clear all completed/failed/cancelled jobs.
   */
  async clearCompletedJobs(): Promise<ApiResponse<{ cleared_count: number }>> {
    return apiClient.delete('/api/jobs/completed');
  },

  /**
   * Create an SSE stream for job updates.
   *
   * This function returns an async generator that yields JobStreamEvent
   * objects as jobs are created, updated, and completed.
   *
   * @yields JobStreamEvent - Events for job updates
   */
  async *streamJobUpdates(): AsyncGenerator<JobStreamEvent, void, unknown> {
    const port = await apiClient.getPort();
    const url = `http://localhost:${port}/api/jobs/stream`;

    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'text/event-stream' },
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
              const event = JSON.parse(jsonStr) as JobStreamEvent;
              yield event;
            } catch (parseError) {
              console.error('[JobApi] Failed to parse SSE event:', parseError, jsonStr);
            }
          }
        }
      }

      // Process any remaining data in the buffer
      if (buffer.trim() && buffer.startsWith('data: ')) {
        const jsonStr = buffer.slice(6).trim();
        if (jsonStr) {
          try {
            const event = JSON.parse(jsonStr) as JobStreamEvent;
            yield event;
          } catch (parseError) {
            console.error('[JobApi] Failed to parse final SSE event:', parseError, jsonStr);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};

export default jobApi;
