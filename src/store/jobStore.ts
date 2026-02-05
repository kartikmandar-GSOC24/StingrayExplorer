/**
 * Zustand store for managing background job state.
 *
 * This store tracks all jobs in the queue, including their status,
 * progress, and results. It receives updates from the SSE stream
 * and provides methods for managing jobs.
 */

import { create } from 'zustand';
import type { Job, JobStatus, JobStreamEvent } from '@/types/job';

interface JobStore {
  /** All jobs indexed by ID */
  jobs: Record<string, Job>;

  /** Whether the SSE connection is active */
  isConnected: boolean;

  /** Connection error message, if any */
  connectionError: string | null;

  /** Reconnection attempt count */
  reconnectAttempts: number;

  // Actions

  /** Set SSE connection status */
  setConnected: (connected: boolean, error?: string | null) => void;

  /** Increment reconnection attempts */
  incrementReconnectAttempts: () => void;

  /** Reset reconnection attempts */
  resetReconnectAttempts: () => void;

  /** Add or update a job */
  upsertJob: (job: Job) => void;

  /** Update an existing job */
  updateJob: (jobId: string, updates: Partial<Job>) => void;

  /** Remove a job */
  removeJob: (jobId: string) => void;

  /** Handle an SSE event */
  handleEvent: (event: JobStreamEvent) => void;

  /** Clear all completed/failed/cancelled jobs */
  clearCompletedJobs: () => void;

  /** Set multiple jobs at once (for initial state) */
  setJobs: (jobs: Job[]) => void;

  // Computed selectors (as functions)

  /** Get all jobs as an array, sorted by creation time (newest first) */
  getJobsArray: () => Job[];

  /** Get active (pending or running) jobs */
  getActiveJobs: () => Job[];

  /** Get completed jobs (completed, failed, or cancelled) */
  getCompletedJobs: () => Job[];

  /** Get count of active jobs */
  getActiveJobCount: () => number;

  /** Get a specific job by ID */
  getJob: (jobId: string) => Job | undefined;
}

const isActiveStatus = (status: JobStatus): boolean => {
  return status === 'pending' || status === 'running';
};

const isCompletedStatus = (status: JobStatus): boolean => {
  return status === 'completed' || status === 'failed' || status === 'cancelled';
};

export const useJobStore = create<JobStore>((set, get) => ({
  // Initial state
  jobs: {},
  isConnected: false,
  connectionError: null,
  reconnectAttempts: 0,

  // Actions
  setConnected: (connected: boolean, error: string | null = null): void => {
    set({ isConnected: connected, connectionError: error });
  },

  incrementReconnectAttempts: (): void => {
    set((state) => ({ reconnectAttempts: state.reconnectAttempts + 1 }));
  },

  resetReconnectAttempts: (): void => {
    set({ reconnectAttempts: 0 });
  },

  upsertJob: (job: Job): void => {
    set((state) => ({
      jobs: { ...state.jobs, [job.id]: job },
    }));
  },

  updateJob: (jobId: string, updates: Partial<Job>): void => {
    set((state) => {
      const existing = state.jobs[jobId];
      if (!existing) return state;

      return {
        jobs: {
          ...state.jobs,
          [jobId]: { ...existing, ...updates },
        },
      };
    });
  },

  removeJob: (jobId: string): void => {
    set((state) => {
      const { [jobId]: _, ...rest } = state.jobs;
      return { jobs: rest };
    });
  },

  handleEvent: (event: JobStreamEvent): void => {
    const { type } = event;

    switch (type) {
      case 'initial_state': {
        // Set all jobs from initial state
        const jobsMap: Record<string, Job> = {};
        for (const job of event.jobs) {
          jobsMap[job.id] = job;
        }
        set({ jobs: jobsMap });
        break;
      }

      case 'job_created':
      case 'job_started':
      case 'job_progress':
      case 'job_completed':
      case 'job_failed':
      case 'job_cancelled': {
        // Update the job
        set((state) => ({
          jobs: { ...state.jobs, [event.job.id]: event.job },
        }));
        break;
      }

      case 'heartbeat':
        // Heartbeat doesn't change state, just confirms connection is alive
        break;

      default:
        console.warn('[JobStore] Unknown event type:', type);
    }
  },

  clearCompletedJobs: (): void => {
    set((state) => {
      const filtered: Record<string, Job> = {};
      for (const [id, job] of Object.entries(state.jobs)) {
        if (!isCompletedStatus(job.status)) {
          filtered[id] = job;
        }
      }
      return { jobs: filtered };
    });
  },

  setJobs: (jobs: Job[]): void => {
    const jobsMap: Record<string, Job> = {};
    for (const job of jobs) {
      jobsMap[job.id] = job;
    }
    set({ jobs: jobsMap });
  },

  // Computed selectors
  getJobsArray: (): Job[] => {
    const { jobs } = get();
    return Object.values(jobs).sort((a, b) => {
      // Sort by created_at descending (newest first)
      return b.created_at.localeCompare(a.created_at);
    });
  },

  getActiveJobs: (): Job[] => {
    const { jobs } = get();
    return Object.values(jobs)
      .filter((job) => isActiveStatus(job.status))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
  },

  getCompletedJobs: (): Job[] => {
    const { jobs } = get();
    return Object.values(jobs)
      .filter((job) => isCompletedStatus(job.status))
      .sort((a, b) => {
        // Sort by completed_at descending (newest first)
        const aTime = a.completed_at || a.created_at;
        const bTime = b.completed_at || b.created_at;
        return bTime.localeCompare(aTime);
      });
  },

  getActiveJobCount: (): number => {
    const { jobs } = get();
    return Object.values(jobs).filter((job) => isActiveStatus(job.status)).length;
  },

  getJob: (jobId: string): Job | undefined => {
    return get().jobs[jobId];
  },
}));

export default useJobStore;
