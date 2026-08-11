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
});
