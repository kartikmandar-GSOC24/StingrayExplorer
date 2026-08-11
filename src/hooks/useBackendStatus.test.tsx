import { StrictMode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useBackendStatus } from './useBackendStatus';
import type { BackendStatus, BackendStatusSource } from '@/types/backendStatus';

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

class FakeBackendStatusSource implements BackendStatusSource {
  readonly listeners = new Set<(status: BackendStatus) => void>();
  readonly getBackendStatus: BackendStatusSource['getBackendStatus'];
  readonly onBackendStatus = vi.fn((callback: (status: BackendStatus) => void) => {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  });

  constructor(getBackendStatus: BackendStatusSource['getBackendStatus']) {
    this.getBackendStatus = vi.fn(getBackendStatus);
  }

  emit(status: BackendStatus): void {
    for (const listener of this.listeners) listener(status);
  }
}

describe('useBackendStatus', () => {
  it('recovers ready state from the snapshot when the ready event already occurred', async () => {
    const source = new FakeBackendStatusSource(async () => ({
      revision: 4,
      phase: 'ready',
      port: 54321,
      error: null,
    }));

    const { result } = renderHook(() => useBackendStatus(source));

    await waitFor(() => {
      expect(result.current).toEqual({ port: 54321, isReady: true, error: null });
    });
    expect(source.onBackendStatus.mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(source.getBackendStatus).mock.invocationCallOrder[0]
    );
  });

  it('does not let a delayed older snapshot overwrite a newer ready event', async () => {
    const snapshot = deferred<BackendStatus>();
    const source = new FakeBackendStatusSource(() => snapshot.promise);
    const { result } = renderHook(() => useBackendStatus(source));

    act(() => {
      source.emit({ revision: 8, phase: 'ready', port: 52123, error: null });
    });
    expect(result.current).toEqual({ port: 52123, isReady: true, error: null });

    await act(async () => {
      snapshot.resolve({ revision: 7, phase: 'starting', port: null, error: null });
      await snapshot.promise;
    });
    expect(result.current).toEqual({ port: 52123, isReady: true, error: null });
  });

  it('recovers from an exit error through restart starting and ready updates', async () => {
    const source = new FakeBackendStatusSource(async () => ({
      revision: 1,
      phase: 'error',
      port: null,
      error: 'The Python backend exited unexpectedly.',
    }));
    const { result } = renderHook(() => useBackendStatus(source));
    await waitFor(() => {
      expect(result.current.error).toBe('The Python backend exited unexpectedly.');
    });

    act(() => {
      source.emit({ revision: 2, phase: 'starting', port: null, error: null });
    });
    expect(result.current).toEqual({ port: null, isReady: false, error: null });

    act(() => {
      source.emit({ revision: 3, phase: 'ready', port: 52001, error: null });
    });
    expect(result.current).toEqual({ port: 52001, isReady: true, error: null });
  });

  it('restores an unexpected-exit error from the atomic snapshot after reload', async () => {
    const source = new FakeBackendStatusSource(async () => ({
      revision: 12,
      phase: 'error',
      port: null,
      error: 'The Python backend exited unexpectedly (signal SIGKILL).',
    }));

    const { result } = renderHook(() => useBackendStatus(source));

    await waitFor(() => {
      expect(result.current).toEqual({
        port: null,
        isReady: false,
        error: 'The Python backend exited unexpectedly (signal SIGKILL).',
      });
    });
  });

  it('maps backend errors to a not-ready state with the supplied error', async () => {
    const source = new FakeBackendStatusSource(async () => ({
      revision: 1,
      phase: 'starting',
      port: null,
      error: null,
    }));
    const { result } = renderHook(() => useBackendStatus(source));
    await waitFor(() => expect(source.getBackendStatus).toHaveBeenCalledOnce());

    act(() => {
      source.emit({
        revision: 2,
        phase: 'error',
        port: null,
        error: 'Authenticated readiness failed',
      });
    });
    expect(result.current).toEqual({
      port: null,
      isReady: false,
      error: 'Authenticated readiness failed',
    });
  });

  it('ignores an abandoned Strict Mode snapshot and removes both listeners', async () => {
    const firstSnapshot = deferred<BackendStatus>();
    const secondSnapshot = deferred<BackendStatus>();
    let snapshotCalls = 0;
    const source = new FakeBackendStatusSource(() => {
      snapshotCalls += 1;
      return snapshotCalls === 1 ? firstSnapshot.promise : secondSnapshot.promise;
    });

    const { result, unmount } = renderHook(() => useBackendStatus(source), {
      wrapper: StrictMode,
    });
    await waitFor(() => expect(source.onBackendStatus).toHaveBeenCalledTimes(2));
    expect(source.listeners.size).toBe(1);

    await act(async () => {
      secondSnapshot.resolve({ revision: 5, phase: 'ready', port: 53001, error: null });
      await secondSnapshot.promise;
    });
    expect(result.current).toEqual({ port: 53001, isReady: true, error: null });

    await act(async () => {
      firstSnapshot.resolve({
        revision: 99,
        phase: 'error',
        port: null,
        error: 'abandoned effect',
      });
      await firstSnapshot.promise;
    });
    expect(result.current).toEqual({ port: 53001, isReady: true, error: null });

    unmount();
    expect(source.listeners.size).toBe(0);
    expect(source.onBackendStatus.mock.results).toHaveLength(2);
  });

  it('handles a rejected snapshot without an unhandled rejection', async () => {
    const unhandledRejection = vi.fn();
    window.addEventListener('unhandledrejection', unhandledRejection);
    const source = new FakeBackendStatusSource(() =>
      Promise.reject(new Error('temporary IPC failure'))
    );

    const { result } = renderHook(() => useBackendStatus(source));
    await waitFor(() => expect(source.getBackendStatus).toHaveBeenCalledOnce());
    await act(async () => Promise.resolve());

    expect(result.current).toEqual({ port: null, isReady: false, error: null });
    expect(unhandledRejection).not.toHaveBeenCalled();
    window.removeEventListener('unhandledrejection', unhandledRejection);
  });
});
