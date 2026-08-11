import { useEffect, useState } from 'react';
import type { BackendStatus, BackendStatusSource } from '@/types/backendStatus';

export interface BackendState {
  port: number | null;
  isReady: boolean;
  error: string | null;
}

export const initialBackendState: BackendState = {
  port: null,
  isReady: false,
  error: null,
};

export function backendStateFromStatus(status: BackendStatus): BackendState {
  switch (status.phase) {
    case 'ready':
      if (status.port === null) {
        return {
          port: null,
          isReady: false,
          error: 'The backend reported readiness without an available port.',
        };
      }
      return { port: status.port, isReady: true, error: null };
    case 'error':
      return {
        port: null,
        isReady: false,
        error: status.error ?? 'The Python backend failed to start.',
      };
    case 'starting':
    case 'stopped':
      return initialBackendState;
  }
}

function getDefaultSource(): BackendStatusSource | null {
  if (typeof window === 'undefined' || !window.electronAPI) return null;
  return window.electronAPI;
}

export function useBackendStatus(source?: BackendStatusSource): BackendState {
  const [backendState, setBackendState] = useState<BackendState>(initialBackendState);
  const statusSource = source ?? getDefaultSource();

  useEffect(() => {
    if (!statusSource) return;

    let active = true;
    let greatestRevision = -1;
    let unsubscribe = (): void => undefined;

    const applyStatus = (status: BackendStatus): void => {
      if (!active || status.revision <= greatestRevision) return;
      greatestRevision = status.revision;
      setBackendState(backendStateFromStatus(status));
    };

    // Subscribe before reading the snapshot so a transition that occurs during
    // the IPC round trip cannot be lost. Revisions keep a delayed snapshot from
    // overwriting a newer event.
    try {
      unsubscribe = statusSource.onBackendStatus(applyStatus);
    } catch {
      // The atomic snapshot can still reconcile a recoverable subscription
      // failure. A later mount or renderer reload will try the handshake again.
    }

    try {
      void statusSource.getBackendStatus().then(applyStatus, () => undefined);
    } catch {
      // Treat a synchronous bridge failure like a rejected IPC request. Keeping
      // the last known state is safer than manufacturing a backend error.
    }

    return () => {
      active = false;
      unsubscribe();
    };
  }, [statusSource]);

  return backendState;
}
