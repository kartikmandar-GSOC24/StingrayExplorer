/**
 * TypeScript types for the background job queue system.
 */

/**
 * Job status enum values.
 */
export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

/**
 * Job type enum values.
 */
export type JobType = 'load_event_list' | 'load_batch' | 'load_from_url';

/**
 * Represents a background job in the queue.
 */
export interface Job {
  /** Unique identifier for the job (UUID) */
  id: string;
  /** Type of job */
  type: JobType;
  /** Current status of the job */
  status: JobStatus;
  /** Progress percentage (0.0 to 1.0) */
  progress: number;
  /** Human-readable progress message */
  progress_message: string;
  /** Total number of items to process (for batch jobs) */
  total_items: number;
  /** Number of items completed */
  completed_items: number;
  /** ISO timestamp when job was created */
  created_at: string;
  /** ISO timestamp when job started running */
  started_at: string | null;
  /** ISO timestamp when job completed/failed/cancelled */
  completed_at: string | null;
  /** Job-specific parameters */
  params: Record<string, unknown>;
  /** Result data on successful completion */
  result: Record<string, unknown> | null;
  /** Error message on failure */
  error: string | null;
  /** Human-readable name for the job (shown in UI) */
  display_name: string;
}

/**
 * SSE event types for job updates.
 */
export type JobEventType =
  | 'initial_state'
  | 'job_created'
  | 'job_started'
  | 'job_progress'
  | 'job_completed'
  | 'job_failed'
  | 'job_cancelled'
  | 'heartbeat';

/**
 * Base SSE event structure.
 */
interface BaseJobStreamEvent {
  type: JobEventType;
  timestamp: string;
}

/**
 * Initial state event sent when SSE connection is established.
 */
export interface InitialStateEvent extends BaseJobStreamEvent {
  type: 'initial_state';
  jobs: Job[];
}

/**
 * Job update event (created, started, progress, completed, failed, cancelled).
 */
export interface JobUpdateEvent extends BaseJobStreamEvent {
  type: 'job_created' | 'job_started' | 'job_progress' | 'job_completed' | 'job_failed' | 'job_cancelled';
  job: Job;
}

/**
 * Heartbeat event to keep connection alive.
 */
export interface HeartbeatEvent extends BaseJobStreamEvent {
  type: 'heartbeat';
}

/**
 * Union type for all SSE events.
 */
export type JobStreamEvent = InitialStateEvent | JobUpdateEvent | HeartbeatEvent;

/**
 * Name conflict check result.
 */
export interface NameConflictResult {
  has_conflict: boolean;
  conflict_source?: 'loaded_data' | 'pending_job';
  job_id?: string;
  suggested_name?: string;
}

/**
 * Request parameters for submitting a single file load job.
 */
export interface SubmitLoadJobParams {
  file_path: string;
  name: string;
  fmt?: string;
  rmf_file?: string;
  additional_columns?: string[];
  high_precision?: boolean;
  skip_checks?: boolean;
  notes?: string;
  use_partial_loading?: boolean;
  partial_mode?: 'time_range' | 'event_count';
  time_range_start?: number;
  time_range_end?: number;
  event_start_index?: number;
  event_count?: number;
}

/**
 * File configuration for batch loading.
 */
export interface BatchFileConfig {
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

/**
 * Request parameters for submitting a batch load job.
 */
export interface SubmitBatchJobParams {
  files: BatchFileConfig[];
  use_same_settings?: boolean;
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

/**
 * Request parameters for submitting a URL load job.
 */
export interface SubmitUrlJobParams {
  url: string;
  name: string;
  fmt?: string;
  rmf_file?: string;
  additional_columns?: string[];
  high_precision?: boolean;
  skip_checks?: boolean;
  notes?: string;
}
