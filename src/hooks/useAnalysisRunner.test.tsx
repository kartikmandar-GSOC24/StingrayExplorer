import { beforeEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useAnalysisRunner } from './useAnalysisRunner';
import { useUIStore } from '@/store/uiStore';

describe('useAnalysisRunner', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
  });

  it('stores the result and pushes a success notification', async () => {
    const { result } = renderHook(() => useAnalysisRunner<{ v: number }>('Test Op'));
    await act(async () => {
      await result.current.run(async () => ({
        success: true,
        data: { v: 42 },
        message: 'computed',
        error: null,
      }));
    });
    expect(result.current.result?.v).toBe(42);
    expect(result.current.running).toBe(false);
    expect(result.current.error).toBeNull();
    const notes = useUIStore.getState().notifications;
    expect(notes[0].type).toBe('success');
    expect(notes[0].title).toBe('Test Op');
  });

  it('captures success:false as an error and keeps the previous result', async () => {
    const { result } = renderHook(() => useAnalysisRunner<{ v: number }>('Test Op'));
    await act(async () => {
      await result.current.run(async () => ({
        success: true,
        data: { v: 1 },
        message: '',
        error: null,
      }));
    });
    await act(async () => {
      await result.current.run(async () => ({
        success: false,
        data: null,
        message: 'bad dt',
        error: 'bad dt',
      }));
    });
    expect(result.current.error).toBe('bad dt');
    expect(result.current.result?.v).toBe(1);
    expect(useUIStore.getState().notifications[0].type).toBe('error');
  });

  it('captures thrown errors (network failures)', async () => {
    const { result } = renderHook(() => useAnalysisRunner('Test Op'));
    await act(async () => {
      await result.current.run(async () => {
        throw new Error('connection refused');
      });
    });
    expect(result.current.error).toBe('connection refused');
  });
});
