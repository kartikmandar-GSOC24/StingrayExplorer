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
  private maxRetries: number = 60; // 30 seconds max wait
  private retryInterval: number = 500; // ms
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
      if (!this.process) {
        resolve();
        return;
      }

      // Try graceful shutdown first
      this.process.once('exit', () => {
        this.process = null;
        this.isRunning = false;
        this.sendLog('info', 'Python backend stopped');
        resolve();
      });

      // Send SIGTERM for graceful shutdown
      this.process.kill('SIGTERM');

      // Force kill after 5 seconds if still running
      setTimeout(() => {
        if (this.process) {
          this.sendLog('warn', 'Force killing Python backend...');
          this.process.kill('SIGKILL');
        }
      }, 5000);
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
    this.sendLog('info', 'Waiting for Python backend to be ready...');

    for (let i = 0; i < this.maxRetries; i++) {
      try {
        const isReady = await this.checkHealth();
        if (isReady) {
          this.sendLog('info', 'Python backend is ready!');
          return;
        }
      } catch {
        // Ignore errors, keep trying
      }

      await this.sleep(this.retryInterval);
    }

    const errorMsg = `Python backend failed to start within ${(this.maxRetries * this.retryInterval) / 1000} seconds`;
    this.sendLog('error', errorMsg);
    throw new Error(errorMsg);
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
