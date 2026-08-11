import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest';
import {
  dataApi,
  type BatchFileSizeInfo,
  type BatchLoadFailedItem,
  type BatchLoadSuccessItem,
  type BatchStreamEventFileComplete,
  type FileMetadata,
} from './dataApi';
import { jobApi } from './jobApi';
import type { Job, SubmitBatchJobParams, SubmitLoadJobParams } from '@/types/job';

const clientMocks = vi.hoisted(() => ({
  post: vi.fn(),
  getPort: vi.fn().mockResolvedValue(8765),
}));

vi.mock('./client', () => ({
  apiClient: {
    post: clientMocks.post,
    getPort: clientMocks.getPort,
  },
}));

const response = { success: true, data: {}, message: '', error: null };

describe('legacy native-file grant request contracts', () => {
  beforeEach(() => {
    clientMocks.post.mockReset().mockResolvedValue(response);
  });

  it('sends a distinct grant for a local source and its optional RMF', async () => {
    await dataApi.loadEventList({
      file_path: '/science/events.fits',
      file_grant: 'event-grant',
      name: 'events',
      fmt: 'ogip',
      rmf_file: '/calibration/response.rmf',
      rmf_grant: 'rmf-grant',
    });

    expect(clientMocks.post).toHaveBeenCalledWith(
      '/api/data/load',
      expect.objectContaining({
        file_path: '/science/events.fits',
        file_grant: 'event-grant',
        rmf_file: '/calibration/response.rmf',
        rmf_grant: 'rmf-grant',
      })
    );

    await dataApi.loadEventListFromUrl({
      url: 'https://example.test/events.fits',
      name: 'remote-events',
      rmf_file: '/calibration/response.rmf',
      rmf_grant: 'remote-rmf-grant',
    });
    expect(clientMocks.post).toHaveBeenLastCalledWith(
      '/api/data/load-url',
      expect.objectContaining({
        rmf_file: '/calibration/response.rmf',
        rmf_grant: 'remote-rmf-grant',
      })
    );
  });

  it('grants size, metadata, partial, and every batch source independently', async () => {
    const first = { file_path: '/science/a.fits', file_grant: 'grant-a' };
    const second = { file_path: '/science/b.hdf5', file_grant: 'grant-b' };

    await dataApi.checkFileSize(first);
    await dataApi.getFileMetadata({ ...first, fmt: 'ogip' });
    await dataApi.loadEventListByTimeRange({
      ...first,
      name: 'a',
      start_time: 0,
      end_time: 10,
      fmt: 'ogip',
    });
    await dataApi.loadEventListByEventCount({
      ...first,
      name: 'a-partial',
      start_index: 0,
      count: 100,
      fmt: 'ogip',
    });
    await dataApi.checkBatchFileSize([first, second]);
    await dataApi.loadBatchEventLists({
      files: [
        { ...first, name: 'a', fmt: 'ogip' },
        { ...second, name: 'b', fmt: 'hdf5' },
      ],
      use_same_settings: true,
      shared_rmf_file: '/calibration/shared.rmf',
      shared_rmf_grant: 'shared-rmf-grant',
    });

    expect(clientMocks.post).toHaveBeenNthCalledWith(1, '/api/data/check-size', first);
    expect(clientMocks.post).toHaveBeenNthCalledWith(
      2,
      '/api/data/metadata',
      expect.objectContaining(first)
    );
    expect(clientMocks.post).toHaveBeenNthCalledWith(
      3,
      '/api/data/load-by-time-range',
      expect.objectContaining(first)
    );
    expect(clientMocks.post).toHaveBeenNthCalledWith(
      4,
      '/api/data/load-by-event-count',
      expect.objectContaining(first)
    );
    expect(clientMocks.post).toHaveBeenNthCalledWith(5, '/api/data/check-batch-size', {
      files: [first, second],
    });
    expect(clientMocks.post).toHaveBeenNthCalledWith(
      6,
      '/api/data/load-batch',
      expect.objectContaining({
        files: [expect.objectContaining(first), expect.objectContaining(second)],
        shared_rmf_grant: 'shared-rmf-grant',
      })
    );
  });

  it('includes source and RMF grants in single, batch, and URL job submissions', async () => {
    const single: SubmitLoadJobParams = {
      file_path: '/science/events.fits',
      file_grant: 'event-grant',
      name: 'events',
      rmf_file: '/calibration/response.rmf',
      rmf_grant: 'rmf-grant',
    };
    const batch: SubmitBatchJobParams = {
      files: [
        {
          file_path: '/science/events.fits',
          file_grant: 'event-grant',
          name: 'events',
        },
      ],
      use_same_settings: true,
      shared_rmf_file: '/calibration/response.rmf',
      shared_rmf_grant: 'shared-rmf-grant',
    };

    await jobApi.submitLoadJob(single);
    await jobApi.submitBatchJob(batch);
    await jobApi.submitUrlJob({
      url: 'https://example.test/events.fits',
      name: 'remote',
      rmf_file: '/calibration/response.rmf',
      rmf_grant: 'url-rmf-grant',
    });

    expect(clientMocks.post).toHaveBeenNthCalledWith(
      1,
      '/api/jobs/submit-load',
      expect.objectContaining({ file_grant: 'event-grant', rmf_grant: 'rmf-grant' })
    );
    expect(clientMocks.post).toHaveBeenNthCalledWith(
      2,
      '/api/jobs/submit-batch',
      expect.objectContaining({
        files: [expect.objectContaining({ file_grant: 'event-grant' })],
        shared_rmf_grant: 'shared-rmf-grant',
      })
    );
    expect(clientMocks.post).toHaveBeenNthCalledWith(
      3,
      '/api/jobs/submit-url',
      expect.objectContaining({ rmf_grant: 'url-rmf-grant' })
    );
  });

  it('models metadata, batch results, and batch SSE as redacted response DTOs', () => {
    expectTypeOf<FileMetadata>().not.toHaveProperty('file_path');
    expectTypeOf<BatchFileSizeInfo>().not.toHaveProperty('file_path');
    expectTypeOf<BatchLoadSuccessItem>().not.toHaveProperty('file_path');
    expectTypeOf<BatchLoadFailedItem>().not.toHaveProperty('file_path');
    expectTypeOf<BatchStreamEventFileComplete>().not.toHaveProperty('file_path');

    const orderedSize: BatchFileSizeInfo = {
      file_name: 'shared.fits',
      size_mb: 1,
      estimated_ram_mb: 2,
      ram_percent: 3,
      risk_level: 'safe',
    };
    const completeEvent: BatchStreamEventFileComplete = {
      type: 'file_complete',
      name: 'events',
      success: true,
      completed: 1,
      total: 1,
    };

    expect(orderedSize).toEqual(expect.objectContaining({ file_name: 'shared.fits' }));
    expect(completeEvent).not.toHaveProperty('file_path');
  });

  it('models public jobs without request parameters or native authority', () => {
    const job: Job = {
      id: 'job-id',
      type: 'load_batch',
      status: 'completed',
      progress: 1,
      progress_message: 'Complete',
      total_items: 1,
      completed_items: 1,
      created_at: '2026-08-11T00:00:00Z',
      started_at: '2026-08-11T00:00:01Z',
      completed_at: '2026-08-11T00:00:02Z',
      result: { success_count: 1, total_files: 1 },
      error: null,
      display_name: 'Batch load',
    };

    expect(job).not.toHaveProperty('params');

    const assertInvalidContracts = (): void => {
      // @ts-expect-error Local jobs require a source grant.
      void jobApi.submitLoadJob({ file_path: '/science/a.fits', name: 'a' });
      // @ts-expect-error RMF paths and grants must be supplied together.
      void jobApi.submitLoadJob({
        file_path: '/science/a.fits',
        file_grant: 'grant-a',
        name: 'a',
        rmf_file: '/calibration/a.rmf',
      });
      void jobApi.submitLoadJob({
        file_path: '/science/a.pkl',
        file_grant: 'grant-a',
        name: 'a',
        // @ts-expect-error Pickle is not an accepted event input format.
        fmt: 'pickle',
      });
      // @ts-expect-error Public job DTOs never expose submission parameters.
      const leakedJob: Job = { ...job, params: { file_grant: 'secret' } };
      void leakedJob;
    };
    void assertInvalidContracts;
  });
});
