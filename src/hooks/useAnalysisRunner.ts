import { useCallback, useState } from 'react';
import { ApiResponse } from '@/api/client';
import { useUIStore } from '@/store/uiStore';

interface AnalysisRunnerState<T> {
  result: T | null;
  running: boolean;
  error: string | null;
  warnings: string[];
}

function dataWarnings(value: unknown): string[] {
  if (typeof value !== 'object' || value === null || !('warnings' in value)) return [];
  const warnings = (value as { warnings?: unknown }).warnings;
  return Array.isArray(warnings)
    ? warnings.filter((warning): warning is string => typeof warning === 'string')
    : [];
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
    warnings: [],
  });

  const run = useCallback(
    async (call: () => Promise<ApiResponse<T>>): Promise<void> => {
      setState((s) => ({ ...s, running: true, error: null, warnings: [] }));
      try {
        const res = await call();
        if (res.success && res.data != null) {
          const embeddedWarnings = dataWarnings(res.data);
          setState({
            result: res.data,
            running: false,
            error: null,
            warnings: (res.warnings ?? []).filter(
              (warning) => !embeddedWarnings.includes(warning)
            ),
          });
          addNotification({ type: 'success', title: label, message: res.message || 'Done' });
        } else {
          const msg = res.error || res.message || 'Operation failed';
          setState((s) => ({
            ...s,
            running: false,
            error: msg,
            warnings: res.warnings ?? [],
          }));
          addNotification({ type: 'error', title: label, message: msg });
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setState((s) => ({ ...s, running: false, error: msg, warnings: [] }));
        addNotification({ type: 'error', title: label, message: msg });
      }
    },
    [label, addNotification]
  );

  const reset = useCallback((): void => {
    setState({ result: null, running: false, error: null, warnings: [] });
  }, []);

  return { ...state, run, reset };
}
