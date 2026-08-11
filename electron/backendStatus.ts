import type { BackendStatus } from '../src/types/backendStatus';

export type BackendStatusTransition =
  | { phase: 'starting' }
  | { phase: 'ready'; port: number }
  | { phase: 'error'; error: string }
  | { phase: 'stopped' };

type BackendStatusListener = (status: BackendStatus) => void;

/** Main-process owner for the renderer-visible backend lifecycle snapshot. */
export class BackendStatusStore {
  private status: BackendStatus = {
    revision: 0,
    phase: 'stopped',
    port: null,
    error: null,
  };

  constructor(private readonly notify: BackendStatusListener) {}

  getSnapshot(): BackendStatus {
    return { ...this.status };
  }

  publish(transition: BackendStatusTransition): BackendStatus {
    const revision = this.status.revision + 1;

    switch (transition.phase) {
      case 'ready':
        this.status = {
          revision,
          phase: 'ready',
          port: transition.port,
          error: null,
        };
        break;
      case 'error':
        this.status = {
          revision,
          phase: 'error',
          port: null,
          error: transition.error,
        };
        break;
      case 'starting':
      case 'stopped':
        this.status = {
          revision,
          phase: transition.phase,
          port: null,
          error: null,
        };
        break;
    }

    const snapshot = this.getSnapshot();
    this.notify(snapshot);
    return snapshot;
  }
}
