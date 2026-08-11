import { EventEmitter } from 'node:events';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  spawn: vi.fn(),
}));

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getAppPath: () => '/test-app',
  },
}));
vi.mock('child_process', () => ({
  default: { spawn: mocks.spawn },
  spawn: mocks.spawn,
}));
vi.mock('http', () => ({
  default: { request: mocks.request },
  request: mocks.request,
}));

import {
  DEFAULT_BACKEND_PORT,
  parseBackendPortAnnouncement,
  PythonManager,
} from '../../electron/pythonManager';

class FakeChild extends EventEmitter {
  readonly stdout = new EventEmitter();
  readonly stderr = new EventEmitter();
  readonly kill = vi.fn((signal?: string) => {
    queueMicrotask(() => this.emit('exit', null, signal ?? 'SIGTERM'));
    return true;
  });
}

function installHttpResponses(statusFor: (options: { port?: number; path?: string }) => number) {
  mocks.request.mockImplementation((options: { port?: number; path?: string }, callback) => {
    const request = new EventEmitter() as EventEmitter & {
      end: () => void;
      destroy: () => void;
    };
    request.end = () => {
      queueMicrotask(() => {
        const response = new EventEmitter() as EventEmitter & {
          statusCode: number;
          resume: () => void;
        };
        response.statusCode = statusFor(options);
        response.resume = () => undefined;
        callback(response);
      });
    };
    request.destroy = () => undefined;
    return request;
  });
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('PythonManager backend announcement protocol', () => {
  it.each([
    ['BACKEND_PORT:1', 1],
    ['BACKEND_PORT:8765', 8765],
    ['BACKEND_PORT:65535', 65535],
  ])('accepts canonical port line %s', (line, expected) => {
    expect(parseBackendPortAnnouncement(line)).toBe(expected);
  });

  it.each([
    'BACKEND_PORT:0',
    'BACKEND_PORT:65536',
    'BACKEND_PORT:+1',
    'BACKEND_PORT:01',
    'BACKEND_PORT:8765 ',
    'BACKEND_PORT:８７６５',
    'BACKEND_PORT:8765:extra',
  ])('rejects malformed port line %s', (line) => {
    expect(parseBackendPortAnnouncement(line)).toBeNull();
  });

  it('does not send credentials to the hostile default port before announcement', async () => {
    const child = new FakeChild();
    installHttpResponses((options) => {
      if (options.path === '/health') return 404;
      if (options.path === '/api/status' && options.port === 54321) return 200;
      throw new Error(`unexpected request ${options.path}:${options.port}`);
    });
    mocks.spawn.mockImplementation(() => {
      setTimeout(() => {
        child.stdout.emit('data', Buffer.from('BACKEND_'));
        child.stdout.emit('data', Buffer.from('PORT:54321\r\n'));
      }, 10);
      return child;
    });

    const manager = new PythonManager();
    const start = manager.start();
    await new Promise((resolve) => setTimeout(resolve, 1));
    expect(manager.getPort()).toBe(DEFAULT_BACKEND_PORT);
    expect(() => manager.getBackendSessionSecret()).toThrow();
    await start;

    const calls = mocks.request.mock.calls.map(([options]) => options as {
      port?: number;
      path?: string;
      headers?: Record<string, string>;
    });
    expect(calls[0]).toMatchObject({ port: DEFAULT_BACKEND_PORT, path: '/health' });
    expect(calls[0].headers).toBeUndefined();
    expect(calls.filter((options) => options.path === '/health')).toHaveLength(1);
    const authenticated = calls.find((options) => options.path === '/api/status');
    expect(authenticated).toMatchObject({ port: 54321 });
    expect(authenticated?.headers).toHaveProperty('X-Stingray-Session');
    expect(manager.getPort()).toBe(54321);
    expect(manager.getIsRunning()).toBe(true);
  });

  it('rejects an external backend on the default port without spawning', async () => {
    installHttpResponses((options) => (options.path === '/health' ? 200 : 500));
    const manager = new PythonManager();

    await expect(manager.start()).rejects.toThrow(
      'Electron did not launch it and cannot authenticate it'
    );
    expect(mocks.spawn).not.toHaveBeenCalled();
    expect(() => manager.getBackendSessionSecret()).toThrow();
  });

  it.each(['BACKEND_PORT:0\n', 'BACKEND_PORT:8765\nBACKEND_PORT:8766\n'])(
    'terminates startup for invalid or duplicate announcements',
    async (output) => {
      const child = new FakeChild();
      installHttpResponses((options) => (options.path === '/health' ? 404 : 500));
      mocks.spawn.mockImplementation(() => {
        setTimeout(() => child.stdout.emit('data', Buffer.from(output)), 0);
        return child;
      });

      const manager = new PythonManager();
      await expect(manager.start()).rejects.toThrow();
      expect(child.kill).toHaveBeenCalled();
      expect(manager.getPort()).toBe(DEFAULT_BACKEND_PORT);
      expect(manager.getIsRunning()).toBe(false);
      expect(() => manager.getBackendSessionSecret()).toThrow();
    }
  );

  it('reports an unexpected child exit after authenticated readiness', async () => {
    const child = new FakeChild();
    const unexpectedExit = vi.fn();
    installHttpResponses((options) => {
      if (options.path === '/health') return 404;
      if (options.path === '/api/status' && options.port === 54321) return 200;
      return 500;
    });
    mocks.spawn.mockImplementation(() => {
      setTimeout(() => child.stdout.emit('data', Buffer.from('BACKEND_PORT:54321\n')), 0);
      return child;
    });

    const manager = new PythonManager();
    manager.setUnexpectedExitCallback(unexpectedExit);
    await manager.start();

    child.emit('exit', 137, null);

    expect(unexpectedExit).toHaveBeenCalledOnce();
    expect(unexpectedExit).toHaveBeenCalledWith({ code: 137, signal: null });
    expect(manager.getIsRunning()).toBe(false);
    expect(manager.getPort()).toBe(DEFAULT_BACKEND_PORT);
  });

  it('does not report a deliberate stop as an unexpected exit', async () => {
    const child = new FakeChild();
    const unexpectedExit = vi.fn();
    installHttpResponses((options) => {
      if (options.path === '/health') return 404;
      if (options.path === '/api/status' && options.port === 54321) return 200;
      return 500;
    });
    mocks.spawn.mockImplementation(() => {
      setTimeout(() => child.stdout.emit('data', Buffer.from('BACKEND_PORT:54321\n')), 0);
      return child;
    });

    const manager = new PythonManager();
    manager.setUnexpectedExitCallback(unexpectedExit);
    await manager.start();
    await manager.stop();

    expect(unexpectedExit).not.toHaveBeenCalled();
    expect(manager.getIsRunning()).toBe(false);
  });

  it('does not report the expected stop inside restart and reaches ready again', async () => {
    const firstChild = new FakeChild();
    const secondChild = new FakeChild();
    const unexpectedExit = vi.fn();
    installHttpResponses((options) => {
      if (options.path === '/health') return 404;
      if (options.path === '/api/status') return 200;
      return 500;
    });
    mocks.spawn
      .mockImplementationOnce(() => {
        setTimeout(
          () => firstChild.stdout.emit('data', Buffer.from('BACKEND_PORT:54321\n')),
          0
        );
        return firstChild;
      })
      .mockImplementationOnce(() => {
        setTimeout(
          () => secondChild.stdout.emit('data', Buffer.from('BACKEND_PORT:54322\n')),
          0
        );
        return secondChild;
      });

    const manager = new PythonManager();
    manager.setUnexpectedExitCallback(unexpectedExit);
    await manager.start();
    await manager.restart();

    expect(unexpectedExit).not.toHaveBeenCalled();
    expect(manager.getIsRunning()).toBe(true);
    expect(manager.getPort()).toBe(54322);
    await manager.stop();
  });

  it('leaves pre-readiness startup exits to the start rejection path', async () => {
    const child = new FakeChild();
    const unexpectedExit = vi.fn();
    installHttpResponses((options) => (options.path === '/health' ? 404 : 500));
    mocks.spawn.mockImplementation(() => {
      setTimeout(() => child.emit('exit', 1, null), 0);
      return child;
    });

    const manager = new PythonManager();
    manager.setUnexpectedExitCallback(unexpectedExit);

    await expect(manager.start()).rejects.toThrow(
      'Python backend process exited before becoming ready'
    );
    expect(unexpectedExit).not.toHaveBeenCalled();
  });
});
