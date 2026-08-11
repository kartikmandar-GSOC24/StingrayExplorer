import { describe, expect, it, vi } from 'vitest';
import { BackendStatusStore } from '../../electron/backendStatus';

describe('BackendStatusStore', () => {
  it('owns an atomic, monotonically revisioned lifecycle snapshot', () => {
    const notify = vi.fn();
    const store = new BackendStatusStore(notify);

    expect(store.getSnapshot()).toEqual({
      revision: 0,
      phase: 'stopped',
      port: null,
      error: null,
    });

    expect(store.publish({ phase: 'starting' })).toEqual({
      revision: 1,
      phase: 'starting',
      port: null,
      error: null,
    });
    expect(store.publish({ phase: 'ready', port: 54321 })).toEqual({
      revision: 2,
      phase: 'ready',
      port: 54321,
      error: null,
    });
    expect(store.publish({ phase: 'error', error: 'backend failed' })).toEqual({
      revision: 3,
      phase: 'error',
      port: null,
      error: 'backend failed',
    });

    expect(notify).toHaveBeenCalledTimes(3);
    expect(notify).toHaveBeenLastCalledWith(store.getSnapshot());
  });

  it('does not expose its stored snapshot for external mutation', () => {
    const store = new BackendStatusStore(() => undefined);
    const snapshot = store.publish({ phase: 'ready', port: 49152 });
    snapshot.phase = 'stopped';
    snapshot.port = null;

    expect(store.getSnapshot()).toEqual({
      revision: 1,
      phase: 'ready',
      port: 49152,
      error: null,
    });
  });
});
