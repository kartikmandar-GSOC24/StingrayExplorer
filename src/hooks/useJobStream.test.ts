import { describe, expect, it, vi } from 'vitest';
import { buildCompletionMessage, handleBatchWarnings } from './useJobStream';
import type { Job } from '@/types/job';

const baseJob: Job = {
  id: 'job-id',
  type: 'load_event_list',
  status: 'completed',
  progress: 1,
  progress_message: 'Completed',
  total_items: 1,
  completed_items: 1,
  created_at: '2026-08-11T00:00:00Z',
  started_at: '2026-08-11T00:00:01Z',
  completed_at: '2026-08-11T00:00:02Z',
  result: null,
  error: null,
  display_name: 'Load events',
};

describe('redacted job stream presentation', () => {
  it('builds completion text from the allowlisted single-result summary', () => {
    const message = buildCompletionMessage({
      ...baseJob,
      result: {
        event_count: 12_345,
        time_start: 10,
        time_end: 15.5,
        warnings: ['GTI validation reported warnings'],
      },
    });

    expect(message).toBe('Load events (12,345 events, 5.50s duration, 1 warning)');
  });

  it('uses redacted batch names and generic errors without requiring a path', () => {
    const addNotification = vi.fn();
    const job: Job = {
      ...baseJob,
      type: 'load_batch',
      display_name: 'Batch load',
      total_items: 2,
      result: {
        successful: [{ name: 'first' }],
        failed: [
          { name: 'second', error: 'The selected file could not be loaded' },
        ],
        success_count: 1,
        failure_count: 1,
        total_files: 2,
      },
    };

    expect(buildCompletionMessage(job)).toBe('Batch load (1/2 files loaded)');
    handleBatchWarnings(job, addNotification);
    expect(addNotification).toHaveBeenCalledWith({
      type: 'error',
      title: 'Failed: second',
      message: 'The selected file could not be loaded',
    });
    expect(JSON.stringify(job)).not.toMatch(/file_path|grant|url|params/);
  });
});
