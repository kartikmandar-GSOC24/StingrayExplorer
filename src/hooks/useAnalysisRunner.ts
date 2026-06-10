import { useCallback, useState } from 'react';
import { ApiResponse } from '@/api/client';
import { useUIStore } from '@/store/uiStore';

interface AnalysisRunnerState<T> {
  result: T | null;
  running: boolean;
  error: string | null;
}

/**
 * Owns the lifecycle of a single analysis request: running flag, last
 * successful result, last error, and success/error notifications.
 * On failure the previous result is kept so the plot doesn't vanish.
 */
export function useAnalysisRunner<T>(label: string) {
  const addNotification = useUIStore((s) => s.addNotification);
  const [state, setState] = useState<AnalysisRunnerState<T>>({
    result: null,
    running: false,
    error: null,
  });

  const run = useCallback(
    async (call: () => Promise<ApiResponse<T>>): Promise<void> => {
      setState((s) => ({ ...s, running: true, error: null }));
      try {
        const res = await call();
        if (res.success && res.data != null) {
          setState({ result: res.data, running: false, error: null });
          addNotification({ type: 'success', title: label, message: res.message || 'Done' });
        } else {
          const msg = res.error || res.message || 'Operation failed';
          setState((s) => ({ ...s, running: false, error: msg }));
          addNotification({ type: 'error', title: label, message: msg });
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setState((s) => ({ ...s, running: false, error: msg }));
        addNotification({ type: 'error', title: label, message: msg });
      }
    },
    [label, addNotification]
  );

  const reset = useCallback((): void => {
    setState({ result: null, running: false, error: null });
  }, []);

  return { ...state, run, reset };
}
