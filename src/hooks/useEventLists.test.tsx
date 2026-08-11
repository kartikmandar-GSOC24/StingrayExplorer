import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...args: unknown[]) => listEventLists(...args) },
}));

import { useEventLists } from './useEventLists';

/** Mint a fresh QueryClient per test, outside the wrapper render path. */
const createWrapper = (): React.FC<{ children: React.ReactNode }> => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

describe('useEventLists', () => {
  beforeEach(() => listEventLists.mockReset());

  it('returns event list summaries on success', async () => {
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'ev1', n_events: 10, time_range: [0, 1] }],
      message: '',
      error: null,
    });
    const { result } = renderHook(() => useEventLists(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].name).toBe('ev1');
  });

  it('surfaces a success:false response as a query error', async () => {
    listEventLists.mockResolvedValue({ success: false, data: null, message: 'boom', error: 'boom' });
    const { result } = renderHook(() => useEventLists(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toBe('boom');
  });
});
