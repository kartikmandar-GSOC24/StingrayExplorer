import { spawn, ChildProcess } from 'child_process';
import { randomBytes } from 'crypto';
import path from 'path';
import { app } from 'electron';
import http from 'http';
import {
  MAX_FILE_GRANT_RESPONSE_BYTES,
  parseFileGrantResponse,
  type NativeFileGrant,
} from './fileGrantResponse';
export type { NativeFileGrant } from './fileGrantResponse';

const FILE_GRANT_ENDPOINT = '/internal/file-grants/issue';
const BACKEND_SESSION_HEADER = 'X-Stingray-Session';
const FILE_GRANT_ISSUER_HEADER = 'X-Stingray-Grant-Issuer';
const FILE_GRANT_REQUEST_TIMEOUT_MS = 5000;
const MAX_SELECTED_PATH_LENGTH = 4096;
const MAX_FILE_GRANT_REQUEST_BYTES = 16 * 1024;
export const DEFAULT_BACKEND_PORT = 8765;

/** Parse the backend's stdout protocol without accepting ambiguous port text. */
export function parseBackendPortAnnouncement(line: string): number | null {
  const match = /^BACKEND_PORT:([1-9][0-9]{0,4})$/.exec(line);
  if (!match) return null;
  const port = Number(match[1]);
  return port >= 1 && port <= 65535 ? port : null;
}

export type LogLevel = 'info' | 'warn' | 'error' | 'debug';
export type LogSource = 'python' | 'electron';

export interface LogMessage {
  level: LogLevel;
  source: LogSource;
  message: string;
}

export type LogCallback = (level: LogLevel, message: string, source: LogSource) => void;

export class PythonManager {
  private process: ChildProcess | null = null;
  private port: number = DEFAULT_BACKEND_PORT;
  private announcedPort: number | null = null;
  private retryInterval: number = 500; // ms between health checks
  // Soft threshold after which the wait for /health is logged as a warning.
  // A cold first launch imports the full scientific stack (stingray, numba,
  // astropy, scipy) and warms numba's compile cache — ~60s normally, but a
  // loaded machine can push it well past any fixed cap, so we never give up
  // while the child process is still alive (see waitForReady). A genuine
  // startup crash still surfaces quickly because the process exits.
  private slowStartWarnMs: number = 180000; // 3 minutes
  private progressLogIntervalMs: number = 15000; // emit a "still waiting" log every 15s
  private isRunning: boolean = false;
  private startupError: Error | null = null;
  private logCallback: LogCallback | null = null;
  // Shared only with Electron main and the child backend. The renderer never
  // receives this credential; main adds it to trusted loopback requests.
  private readonly backendSessionSecret: string = randomBytes(32).toString('hex');
  // Shared only with the spawned loopback backend. Renderer code receives
  // short-lived HMAC grants, never this secret, so it cannot substitute a
  // manually typed path for one selected in an owned native dialog.
  private readonly fileGrantSecret: string = randomBytes(32).toString('hex');

  /**
   * Set the log callback for sending logs to the renderer
   */
  setLogCallback(callback: LogCallback): void {
    this.logCallback = callback;
  }

  /**
   * Send a log message via the callback
   */
  private sendLog(level: LogLevel, message: string): void {
    if (this.logCallback) {
      this.logCallback(level, message, 'python');
    } else {
      console.log(`[Python] ${message}`);
    }
  }

  /**
   * Start the Python backend process
   */
  async start(): Promise<void> {
    if (this.isRunning) {
      this.sendLog('info', 'Python backend is already running');
      return;
    }

    this.announcedPort = null;
    this.port = DEFAULT_BACKEND_PORT;
    this.isRunning = false;
    this.startupError = null;

    // An external backend cannot prove that it shares this launch credential.
    // Refuse it instead of silently attaching to an unauthenticated process.
    const alreadyRunning = await this.checkHealth(DEFAULT_BACKEND_PORT);
    if (alreadyRunning) {
      throw new Error(
        `A backend is already responding on 127.0.0.1:${this.port}, but Electron did not launch it and cannot authenticate it. ` +
        'Stop the external backend, then restart Stingray Explorer.'
      );
    }

    // Not running, start it ourselves
    const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
    const { pythonPath, args } = this.getPythonCommand();

    this.sendLog('info', `Starting Python backend: ${pythonPath} ${args.join(' ')}`);

    const child = spawn(pythonPath, args, {
      cwd: isDev ? path.join(app.getAppPath(), 'python-backend') : undefined,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        PYTHONDONTWRITEBYTECODE: '1',
        // Python 3.14+: make warnings.catch_warnings state context-local instead
        // of process-global, so the concurrent warning capture in
        // services/analysis_helpers.py (collect_warnings) can run lock-free.
        // Unknown to older interpreters, which simply ignore it; analysis_helpers
        // falls back to a serializing lock whenever the flag is not active.
        // Requires that any global warnings.showwarning replacement chain to the
        // handler it displaced - utils/log_stream.py does, and
        // tests/test_analysis_helpers.py keeps it that way.
        PYTHON_CONTEXT_AWARE_WARNINGS: '1',
        STINGRAY_BACKEND_SESSION_SECRET: this.backendSessionSecret,
        STINGRAY_FILE_GRANT_SECRET: this.fileGrantSecret,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    this.process = child;

    let stdoutBuffer = '';
    let stderrBuffer = '';
    const handleOutput = (
      chunk: Buffer | string,
      defaultLevel: LogLevel,
      stream: 'stdout' | 'stderr'
    ) => {
      const buffer = stream === 'stdout' ? stdoutBuffer : stderrBuffer;
      const lines = (buffer + chunk.toString()).split('\n');
      const partial = lines.pop() ?? '';
      if (stream === 'stdout') stdoutBuffer = partial;
      else stderrBuffer = partial;
      for (const rawLine of lines) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
        if (!line) continue;
        if (defaultLevel === 'info' && line.startsWith('BACKEND_PORT:')) {
          const parsedPort = parseBackendPortAnnouncement(line);
          if (parsedPort === null || this.announcedPort !== null) {
            this.startupError = new Error('Python backend announced an invalid or duplicate port');
            if (this.process === child) child.kill('SIGTERM');
          } else {
            this.announcedPort = parsedPort;
            this.port = parsedPort;
            this.sendLog('info', `Backend will use port ${parsedPort}`);
          }
        }
        const level = this.detectLogLevel(line, defaultLevel);
        this.sendLog(level, line);
      }
    };

    // Handle stdout
    child.stdout?.on('data', (data: Buffer) => handleOutput(data, 'info', 'stdout'));

    // Handle stderr
    child.stderr?.on('data', (data: Buffer) => handleOutput(data, 'warn', 'stderr'));

    // Handle process exit
    child.on('exit', (code, signal) => {
      const message = `Python backend exited with code ${code}, signal ${signal}`;
      this.sendLog(code === 0 ? 'info' : 'error', message);
      if (this.process === child) {
        this.isRunning = false;
        this.announcedPort = null;
        this.port = DEFAULT_BACKEND_PORT;
        this.process = null;
      }
    });

    // Handle process error
    child.on('error', (error) => {
      this.sendLog('error', `Failed to start Python backend: ${error.message}`);
      if (this.process === child) {
        this.isRunning = false;
        this.announcedPort = null;
        this.port = DEFAULT_BACKEND_PORT;
        this.startupError = error;
      }
    });

    // Wait for backend to be ready
    try {
      await this.waitForReady();
      if (this.process === child && this.announcedPort !== null) {
        this.isRunning = true;
      }
    } catch (error) {
      if (this.process === child) {
        await this.stop();
      }
      throw error;
    }
  }

  /**
   * Detect log level from message content
   */
  private detectLogLevel(message: string, defaultLevel: LogLevel = 'info'): LogLevel {
    const lowerMessage = message.toLowerCase();

    // Check for explicit level prefixes (uvicorn style: "INFO:", "WARNING:", etc.)
    if (lowerMessage.startsWith('info:') || lowerMessage.includes('info:    ')) {
      return 'info';
    }
    if (lowerMessage.startsWith('debug:')) {
      return 'debug';
    }

    // Check for error indicators
    if (lowerMessage.startsWith('error:') || lowerMessage.includes('error') ||
        lowerMessage.includes('exception') || lowerMessage.includes('traceback')) {
      return 'error';
    }

    // Check for warning indicators
    if (lowerMessage.startsWith('warning:') || lowerMessage.startsWith('warn:') ||
        lowerMessage.includes('warning') || lowerMessage.includes('warn')) {
      return 'warn';
    }

    return defaultLevel;
  }

  /**
   * Stop the Python backend process
   */
  async stop(): Promise<void> {
    this.sendLog('info', 'Stopping Python backend...');

    // If we spawned it, kill the process
    this.announcedPort = null;
    this.port = DEFAULT_BACKEND_PORT;
    this.isRunning = false;
    if (!this.process) {
      return;
    }

    return new Promise((resolve) => {
      // Capture the process we are stopping: this.process gets reassigned by a
      // subsequent start(), and an uncancelled timer reading this.process would
      // SIGKILL the freshly started replacement backend (seen during restart()).
      const proc = this.process;
      if (!proc) {
        resolve();
        return;
      }

      // Force kill after 5 seconds if this same process is still running
      const forceKillTimer = setTimeout(() => {
        if (this.process === proc) {
          this.sendLog('warn', 'Force killing Python backend...');
          proc.kill('SIGKILL');
        }
      }, 5000);

      // Try graceful shutdown first
      proc.once('exit', () => {
        clearTimeout(forceKillTimer);
        if (this.process === proc) {
          this.process = null;
          this.announcedPort = null;
          this.port = DEFAULT_BACKEND_PORT;
          this.isRunning = false;
        }
        this.sendLog('info', 'Python backend stopped');
        resolve();
      });

      // Send SIGTERM for graceful shutdown
      proc.kill('SIGTERM');
    });
  }

  /**
   * Get the Python command and arguments based on environment
   */
  private getPythonCommand(): { pythonPath: string; args: string[] } {
    const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

    if (isDev) {
      // Development: run main.py from python-backend directory
      // The cwd is set to python-backend in the spawn call
      // Use pixi environment Python if available, otherwise fall back to system python
      const pixiPython = path.join(app.getAppPath(), '.pixi', 'envs', 'default', 'bin', 'python');
      return {
        pythonPath: pixiPython,
        args: ['main.py'],
      };
    } else {
      // Production: use bundled executable
      const platform = process.platform;
      let executableName = 'stingray-backend';

      if (platform === 'win32') {
        executableName = 'stingray-backend.exe';
      }

      const executablePath = path.join(process.resourcesPath, 'python-backend', executableName);

      return {
        pythonPath: executablePath,
        args: [],
      };
    }
  }

  /**
   * Wait for the Python backend to be ready
   */
  private async waitForReady(): Promise<void> {
    this.sendLog(
      'info',
      'Waiting for Python backend to be ready (first launch can take ~60s while the scientific stack and numba caches warm up)...'
    );

    const startTime = Date.now();
    let lastProgressLog = startTime;
    let slowStartWarned = false;

    // Poll until the backend is healthy or the process dies. There is no hard
    // deadline: a fixed cap (previously 180s) was observed expiring while the
    // child was alive and still importing, leaving the app stuck in an error
    // state even though the backend became healthy seconds later. A live
    // process is either booting or serving — only a dead one is a failure.
    for (;;) {
      // If we spawned the process and it has already exited, fail fast so the
      // real error (crash, missing dependency, etc.) surfaces immediately.
      // The exit handler in start() sets this.process to null on child exit.
      if (this.startupError) {
        throw this.startupError;
      }
      if (!this.process) {
        throw new Error('Python backend process exited before becoming ready');
      }

      try {
        const announcedPort = this.announcedPort;
        if (announcedPort !== null && await this.checkAuthenticatedReady(announcedPort)) {
          const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
          this.sendLog('info', `Python backend is ready! (took ${elapsed}s)`);
          return;
        }
      } catch {
        // Ignore errors, keep trying
      }

      // Periodic progress so a slow cold start doesn't look like a hang, with
      // a one-time escalation to warn once the start is unusually slow.
      if (Date.now() - lastProgressLog >= this.progressLogIntervalMs) {
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        if (!slowStartWarned && Date.now() - startTime >= this.slowStartWarnMs) {
          slowStartWarned = true;
          this.sendLog(
            'warn',
            `Python backend is taking unusually long to start (${elapsed}s); continuing to wait while the process is alive. Use the restart button if it never comes up.`
          );
        } else {
          this.sendLog('info', `Still waiting for Python backend... (${elapsed}s elapsed)`);
        }
        lastProgressLog = Date.now();
      }

      await this.sleep(this.retryInterval);
    }
  }

  /**
   * Check if the backend is healthy
   */
  private checkHealth(port: number = this.getPort()): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.request(
        {
          hostname: '127.0.0.1',
          port,
          path: '/health',
          method: 'GET',
          timeout: 1000,
        },
        (res) => {
          resolve(res.statusCode === 200);
        }
      );

      req.on('error', () => {
        resolve(false);
      });

      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });

      req.end();
    });
  }

  /** Confirm that the child received this launch's private session credential. */
  private checkAuthenticatedReady(port: number): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.request(
        {
          hostname: '127.0.0.1',
          port,
          path: '/api/status',
          method: 'GET',
          headers: { [BACKEND_SESSION_HEADER]: this.backendSessionSecret },
          timeout: 1000,
        },
        (res) => {
          res.resume();
          resolve(res.statusCode === 200);
        }
      );

      req.on('error', () => resolve(false));
      req.on('timeout', () => {
        req.destroy();
        resolve(false);
      });
      req.end();
    });
  }

  /**
   * Sleep for a specified number of milliseconds
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Get the port the Python backend is running on
   */
  getPort(): number {
    return this.announcedPort ?? DEFAULT_BACKEND_PORT;
  }

  /**
   * Check if the Python backend is running
   */
  getIsRunning(): boolean {
    return this.isRunning;
  }

  /** Credential available to Electron main for trusted backend requests only. */
  getBackendSessionSecret(): string {
    if (!this.process || this.announcedPort === null || !this.isRunning) {
      throw new Error('Backend session authentication is unavailable before startup');
    }
    return this.backendSessionSecret;
  }

  /**
   * Exchange an exact native-dialog selection for a short-lived backend grant.
   * Both credentials remain in Electron main; renderer requests never receive
   * either header and cannot ask the backend to authorize an arbitrary path.
   */
  issueFileGrant(selectedPath: string, access: 'read' | 'write'): Promise<NativeFileGrant> {
    if (!this.process || !this.isRunning) {
      return Promise.reject(
        new Error(
          'Native file authorization is unavailable until the Electron-managed backend is ready. Wait for startup to finish, then select the file again.'
        )
      );
    }
    if (
      typeof selectedPath !== 'string' ||
      selectedPath.length === 0 ||
      selectedPath.length > MAX_SELECTED_PATH_LENGTH ||
      selectedPath.includes('\0')
    ) {
      return Promise.reject(new Error('The native file dialog returned an invalid path'));
    }

    const requestBody = Buffer.from(JSON.stringify({ path: selectedPath, access }), 'utf8');
    if (requestBody.byteLength > MAX_FILE_GRANT_REQUEST_BYTES) {
      return Promise.reject(new Error('The selected path is too long to authorize safely'));
    }

    return new Promise((resolve, reject) => {
      let settled = false;
      let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
      const fail = (message: string) => {
        if (settled) return;
        settled = true;
        if (deadlineTimer) clearTimeout(deadlineTimer);
        reject(new Error(message));
      };
      const succeed = (grant: NativeFileGrant) => {
        if (settled) return;
        settled = true;
        if (deadlineTimer) clearTimeout(deadlineTimer);
        resolve(grant);
      };

      const req = http.request(
        {
          hostname: '127.0.0.1',
          port: this.getPort(),
          path: FILE_GRANT_ENDPOINT,
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'Content-Length': requestBody.byteLength,
            [BACKEND_SESSION_HEADER]: this.backendSessionSecret,
            [FILE_GRANT_ISSUER_HEADER]: this.fileGrantSecret,
          },
          timeout: FILE_GRANT_REQUEST_TIMEOUT_MS,
        },
        (res) => {
          const advertisedLength = Number(res.headers['content-length']);
          if (
            Number.isFinite(advertisedLength) &&
            advertisedLength > MAX_FILE_GRANT_RESPONSE_BYTES
          ) {
            res.destroy();
            fail('The backend returned an oversized native file authorization response');
            return;
          }

          let responseBytes = 0;
          const chunks: Buffer[] = [];
          res.on('data', (chunk: Buffer | string) => {
            if (settled) return;
            const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
            responseBytes += bytes.byteLength;
            if (responseBytes > MAX_FILE_GRANT_RESPONSE_BYTES) {
              res.destroy();
              fail('The backend returned an oversized native file authorization response');
              return;
            }
            chunks.push(bytes);
          });
          res.on('error', () => {
            fail(
              'Native file authorization was interrupted. Restart Stingray Explorer and select the file again.'
            );
          });
          res.on('end', () => {
            if (settled) return;
            const statusCode = res.statusCode ?? 0;
            if (statusCode !== 200) {
              res.resume();
              if (statusCode === 401 || statusCode === 403) {
                fail(
                  'The backend refused native file authorization. Restart Stingray Explorer and select the file again.'
                );
              } else if (statusCode === 400 || statusCode === 422) {
                fail(
                  'The backend could not authorize that selection. Choose an existing input file or a writable destination.'
                );
              } else if (statusCode === 503) {
                fail(
                  'The backend is not ready to authorize native files. Wait for startup to finish and try again.'
                );
              } else {
                fail(
                  'The backend could not authorize the native file selection. Restart Stingray Explorer and try again.'
                );
              }
              return;
            }

            try {
              const grant = parseFileGrantResponse(Buffer.concat(chunks).toString('utf8'));
              succeed(grant);
            } catch {
              fail(
                'The Electron-managed backend returned an invalid native file authorization response. Restart Stingray Explorer and select the file again.'
              );
            }
          });
        }
      );

      req.on('timeout', () => {
        req.destroy();
        fail(
          'Native file authorization timed out. Check that the backend is running, then select the file again.'
        );
      });
      req.on('error', () => {
        fail(
          'Native file authorization could not reach the Electron-managed backend. Restart Stingray Explorer and try again.'
        );
      });
      deadlineTimer = setTimeout(() => {
        req.destroy();
        fail(
          'Native file authorization timed out. Check that the backend is running, then select the file again.'
        );
      }, FILE_GRANT_REQUEST_TIMEOUT_MS);
      req.end(requestBody);
    });
  }

  /**
   * Restart the Python backend
   */
  async restart(): Promise<void> {
    await this.stop();
    await this.start();
  }
}
