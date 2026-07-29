import { spawn, ChildProcess } from 'child_process';
import path from 'path';
import { app } from 'electron';
import http from 'http';

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
  private port: number = 8765;
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
  private externalBackend: boolean = false; // True if backend was started externally
  private logCallback: LogCallback | null = null;

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

    // First check if backend is already running (started by dev.sh or externally)
    const alreadyRunning = await this.checkHealth();
    if (alreadyRunning) {
      this.sendLog('info', 'Python backend is already running externally, connecting to it...');
      this.isRunning = true;
      this.externalBackend = true;
      return;
    }

    // Not running, start it ourselves
    const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;
    const { pythonPath, args } = this.getPythonCommand();

    this.sendLog('info', `Starting Python backend: ${pythonPath} ${args.join(' ')}`);

    this.process = spawn(pythonPath, args, {
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
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    // Handle stdout
    this.process.stdout?.on('data', (data: Buffer) => {
      const lines = data.toString().trim().split('\n');
      for (const line of lines) {
        if (line) {
          // Check for port announcement
          const portMatch = line.match(/^BACKEND_PORT:(\d+)$/);
          if (portMatch) {
            this.port = parseInt(portMatch[1], 10);
            this.sendLog('info', `Backend will use port ${this.port}`);
          }

          // Detect log level from message content
          const level = this.detectLogLevel(line);
          this.sendLog(level, line);
        }
      }
    });

    // Handle stderr
    this.process.stderr?.on('data', (data: Buffer) => {
      const lines = data.toString().trim().split('\n');
      for (const line of lines) {
        if (line) {
          // Stderr messages are typically warnings or errors
          const level = this.detectLogLevel(line, 'warn');
          this.sendLog(level, line);
        }
      }
    });

    // Handle process exit
    this.process.on('exit', (code, signal) => {
      const message = `Python backend exited with code ${code}, signal ${signal}`;
      this.sendLog(code === 0 ? 'info' : 'error', message);
      this.isRunning = false;
      this.process = null;
    });

    // Handle process error
    this.process.on('error', (error) => {
      this.sendLog('error', `Failed to start Python backend: ${error.message}`);
      this.isRunning = false;
    });

    // Wait for backend to be ready
    await this.waitForReady();
    this.isRunning = true;
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
   * Request the backend to shutdown via API
   */
  private async requestShutdown(): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.request(
        {
          hostname: '127.0.0.1',
          port: this.port,
          path: '/api/shutdown',
          method: 'POST',
          timeout: 2000,
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

  /**
   * Wait for the backend to stop
   */
  private async waitForStop(): Promise<void> {
    for (let i = 0; i < 20; i++) {
      const isRunning = await this.checkHealth();
      if (!isRunning) {
        return;
      }
      await this.sleep(250);
    }
  }

  /**
   * Stop the Python backend process
   */
  async stop(): Promise<void> {
    this.sendLog('info', 'Stopping Python backend...');

    // If it was external, request shutdown via API
    if (this.externalBackend) {
      const shutdownRequested = await this.requestShutdown();
      if (shutdownRequested) {
        await this.waitForStop();
        this.sendLog('info', 'External backend stopped via API');
      }
      this.isRunning = false;
      this.externalBackend = false;
      return;
    }

    // If we spawned it, kill the process
    if (!this.process) {
      this.isRunning = false;
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
        this.process = null;
        this.isRunning = false;
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
      if (!this.process) {
        throw new Error('Python backend process exited before becoming ready');
      }

      try {
        if (await this.checkHealth()) {
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
  private checkHealth(): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.request(
        {
          hostname: '127.0.0.1',
          port: this.port,
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
    return this.port;
  }

  /**
   * Check if the Python backend is running
   */
  getIsRunning(): boolean {
    return this.isRunning;
  }

  /**
   * Restart the Python backend
   */
  async restart(): Promise<void> {
    await this.stop();
    await this.start();
  }
}
