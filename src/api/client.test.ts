import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from './client';

describe('apiClient validation errors', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('surfaces actionable FastAPI field details instead of a generic status', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: 'Unprocessable Entity',
        json: vi.fn().mockResolvedValue({
          detail: [
            {
              loc: ['body', 'probability'],
              msg: 'Input should be less than 1',
            },
          ],
        }),
      })
    );

    const result = await apiClient.post('/api/utilities/statistics/gaussian', {
      probability: 2,
    });

    expect(result.success).toBe(false);
    expect(result.message).toBe('probability: Input should be less than 1');
    expect(result.error).toBe('probability: Input should be less than 1');
  });

  it('preserves scientific warnings returned with a non-2xx response', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: 'Unprocessable Entity',
        json: vi.fn().mockResolvedValue({
          message: 'RXTE conversion could not run',
          error: 'Observation epoch is required',
          warnings: [
            'Approximate conversion was not performed.',
            42,
          ],
        }),
      })
    );

    const result = await apiClient.post('/api/utilities/mission-io/convert-pi', {});

    expect(result.success).toBe(false);
    expect(result.error).toBe('Observation epoch is required');
    expect(result.warnings).toEqual(['Approximate conversion was not performed.']);
  });

  it('parses authenticated fetch streams without placing credentials in the URL', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"first"}\n\n'));
        controller.enqueue(encoder.encode('data: {"type":"second"}\r\n\r\n'));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      body: stream,
    });
    vi.stubGlobal('fetch', fetchMock);

    const events = [];
    for await (const event of apiClient.stream<{ type: string }>('/api/jobs/stream')) {
      events.push(event);
    }

    expect(events).toEqual([{ type: 'first' }, { type: 'second' }]);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/jobs/stream',
      expect.objectContaining({
        method: 'GET',
        headers: { Accept: 'text/event-stream' },
      })
    );
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('session');
  });
});
