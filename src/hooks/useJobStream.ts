/**
 * React hook for managing the SSE connection to the job stream.
 *
 * This hook establishes and maintains a persistent SSE connection to
 * receive real-time job updates. It handles connection lifecycle,
 * automatic reconnection on disconnect, and updates the job store.
 * It also triggers detailed notifications when jobs complete or fail,
 * including individual error notifications for batch job failures.
 */

import { useEffect, useRef, useCallback } from 'react';
import { useJobStore } from '@/store/jobStore';
import { useUIStore, NotificationType } from '@/store/uiStore';
import { useBackendContext } from '@/App';
import { jobApi } from '@/api/jobApi';
import type { Job, JobStreamEvent } from '@/types/job';

/**
 * Interface for a failed file in a batch job result.
 */
interface BatchFailedFile {
  name: string;
  file_path: string;
  error: string;
}

/**
 * Interface for a successful file in a batch job result.
 */
interface BatchSuccessfulFile {
  name: string;
  file_path: string;
  data?: {
    n_events?: number;
    gti_warnings?: string[];
    stingray_warnings?: string[];
    validation_issues?: string[];
  };
}

/**
 * Interface for batch job result structure.
 */
interface BatchJobResult {
  successful?: BatchSuccessfulFile[];
  failed?: BatchFailedFile[];
  success_count?: number;
  failure_count?: number;
  total_files?: number;
}

/** Reconnection delay in milliseconds */
const RECONNECT_DELAY = 5000;

/** Maximum reconnection attempts before giving up */
const MAX_RECONNECT_ATTEMPTS = 10;

/**
 * Build a detailed notification message from a completed job.
 */
function buildCompletionMessage(job: Job): string {
  const result = job.result || {};
  const parts: string[] = [];

  // Add event count if available
  if (typeof result.event_count === 'number') {
    parts.push(`${result.event_count.toLocaleString()} events`);
  }

  // Add time range if available
  if (typeof result.time_start === 'number' && typeof result.time_end === 'number') {
    const duration = (result.time_end as number) - (result.time_start as number);
    parts.push(`${duration.toFixed(2)}s duration`);
  }

  // Add warnings count if any
  if (Array.isArray(result.warnings) && result.warnings.length > 0) {
    parts.push(`${result.warnings.length} warning${result.warnings.length > 1 ? 's' : ''}`);
  }

  // For batch jobs, show success/total counts
  if (job.type === 'load_batch' && typeof result.success_count === 'number') {
    const total = result.total_files || job.total_items;
    parts.push(`${result.success_count}/${total} files loaded`);
  }

  if (parts.length > 0) {
    return `${job.display_name} (${parts.join(', ')})`;
  }

  return job.display_name;
}

/**
 * Extract filename from a file path for display in notifications.
 */
function getFilename(filePath: string): string {
  return filePath.split('/').pop() || filePath;
}

/**
 * Handle batch job warnings and failures by creating individual notifications.
 *
 * For batch jobs that complete with partial failures:
 * - Creates an error notification for each failed file with its specific error
 * - Optionally could surface GTI/stingray warnings from successful files
 */
function handleBatchWarnings(
  job: Job,
  addNotification: (notification: { type: NotificationType; title: string; message: string }) => void
): void {
  const result = job.result as BatchJobResult | null;

  if (!result) {
    return;
  }

  const failed = result.failed;

  // Create individual error notifications for each failed file
  if (Array.isArray(failed) && failed.length > 0) {
    for (const failedFile of failed) {
      const filename = getFilename(failedFile.file_path);
      addNotification({
        type: 'error',
        title: `Failed: ${filename}`,
        message: failedFile.error || 'Unknown error occurred',
      });
    }
  }

  // Optionally surface significant warnings from successful files
  // This is commented out by default to avoid notification overload,
  // but can be enabled if users want to see all warnings
  /*
  const successful = result.successful;
  if (Array.isArray(successful)) {
    for (const successFile of successful) {
      const warnings = [
        ...(successFile.data?.gti_warnings || []),
        ...(successFile.data?.stingray_warnings || []),
      ];

      if (warnings.length > 0) {
        const filename = getFilename(successFile.file_path);
        addNotification({
          type: 'warning',
          title: `Warnings: ${filename}`,
          message: `${warnings.length} warning(s): ${warnings[0]}${warnings.length > 1 ? '...' : ''}`,
        });
      }
    }
  }
  */
}

/**
 * Hook to manage the job stream SSE connection.
 *
 * Should be called once at the app root level to establish and
 * maintain the connection throughout the app lifecycle.
 */
export function useJobStream(): void {
  const { isReady: backendReady, port } = useBackendContext();
  const {
    setConnected,
    handleEvent,
    incrementReconnectAttempts,
    resetReconnectAttempts,
    reconnectAttempts,
  } = useJobStore();
  const addNotification = useUIStore((state) => state.addNotification);

  // Track if we should be connected
  const shouldConnectRef = useRef(false);

  // Track the abort controller for cleanup
  const abortControllerRef = useRef<AbortController | null>(null);

  // Track reconnection timeout
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track which jobs we've already notified to avoid duplicates on reconnection
  const notifiedJobsRef = useRef<Set<string>>(new Set());

  /**
   * Handle job completion/failure notifications.
   * Only triggers notifications for jobs we haven't already notified about.
   */
  const handleJobNotification = useCallback((event: JobStreamEvent): void => {
    // Only handle completion and failure events
    if (event.type !== 'job_completed' && event.type !== 'job_failed') {
      return;
    }

    const job = event.job;

    // Skip if we've already notified about this job
    if (notifiedJobsRef.current.has(job.id)) {
      return;
    }

    // Mark as notified
    notifiedJobsRef.current.add(job.id);

    // Clean up old entries (keep last 100 to avoid memory leak)
    if (notifiedJobsRef.current.size > 100) {
      const entries = Array.from(notifiedJobsRef.current);
      notifiedJobsRef.current = new Set(entries.slice(-100));
    }

    if (event.type === 'job_completed') {
      const message = buildCompletionMessage(job);
      addNotification({
        type: 'success',
        title: 'Data Loaded',
        message,
      });

      // For batch jobs, show individual error notifications for failed files
      if (job.type === 'load_batch') {
        handleBatchWarnings(job, addNotification);
      }
    } else if (event.type === 'job_failed') {
      addNotification({
        type: 'error',
        title: 'Load Failed',
        message: job.error || `Failed to load: ${job.display_name}`,
      });
    }
  }, [addNotification]);

  const connect = useCallback(async () => {
    if (!backendReady || !port) {
      console.log('[JobStream] Backend not ready, waiting...');
      return;
    }

    if (!shouldConnectRef.current) {
      console.log('[JobStream] Connection not requested');
      return;
    }

    // Cancel any pending reconnection
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Create new abort controller
    abortControllerRef.current = new AbortController();

    console.log('[JobStream] Connecting to job stream...');

    try {
      // Process events from the stream
      for await (const event of jobApi.streamJobUpdates()) {
        // Check if we should stop
        if (abortControllerRef.current?.signal.aborted) {
          console.log('[JobStream] Connection aborted');
          break;
        }

        // On first event, mark as connected
        setConnected(true, null);
        resetReconnectAttempts();

        // Handle the event (update job store)
        handleEvent(event);

        // Trigger notifications for completed/failed jobs
        handleJobNotification(event);

        // Log non-heartbeat events for debugging
        if (event.type !== 'heartbeat') {
          console.log('[JobStream] Event:', event.type);
        }
      }

      // Stream ended normally
      console.log('[JobStream] Stream ended');
      setConnected(false, null);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      console.error('[JobStream] Connection error:', errorMessage);
      setConnected(false, errorMessage);
    }

    // Schedule reconnection if we should still be connected
    if (shouldConnectRef.current && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      incrementReconnectAttempts();
      const delay = RECONNECT_DELAY * Math.min(reconnectAttempts + 1, 3); // Exponential backoff up to 3x
      console.log(`[JobStream] Reconnecting in ${delay}ms (attempt ${reconnectAttempts + 1}/${MAX_RECONNECT_ATTEMPTS})`);
      reconnectTimeoutRef.current = setTimeout(connect, delay);
    } else if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error('[JobStream] Max reconnection attempts reached, giving up');
      setConnected(false, 'Max reconnection attempts reached');
    }
  }, [
    backendReady,
    port,
    setConnected,
    handleEvent,
    handleJobNotification,
    incrementReconnectAttempts,
    resetReconnectAttempts,
    reconnectAttempts,
  ]);

  const disconnect = useCallback(() => {
    shouldConnectRef.current = false;

    // Cancel pending reconnection
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Abort current connection
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setConnected(false, null);
    console.log('[JobStream] Disconnected');
  }, [setConnected]);

  // Connect when backend becomes ready
  useEffect(() => {
    if (backendReady && port) {
      shouldConnectRef.current = true;
      connect();
    }

    return () => {
      disconnect();
    };
  }, [backendReady, port, connect, disconnect]);

  // Reconnect when reconnectAttempts changes (for reconnection loop)
  // This effect is intentionally left with an empty dep array to avoid loops
}

export default useJobStream;
