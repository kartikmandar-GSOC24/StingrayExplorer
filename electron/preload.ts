import { contextBridge, ipcRenderer } from 'electron';

/**
 * Electron API exposed to the renderer process via context bridge
 * All communication between renderer and main process goes through here
 */
const electronAPI = {
  // ============================================
  // File System Operations
  // ============================================

  /** Open native-selected files with short-lived backend-verifiable grants. */
  openGrantedFile: (options?: {
    title?: string;
    filters?: { name: string; extensions: string[] }[];
    multiple?: boolean;
  }): Promise<{ path: string; grant: string }[] | null> =>
    ipcRenderer.invoke('dialog:openGrantedFile', options),

  /** Select an export destination and bind a write grant to that exact path. */
  saveGrantedFile: (options?: {
    title?: string;
    defaultPath?: string;
    filters?: { name: string; extensions: string[] }[];
  }): Promise<{ path: string; grant: string } | null> =>
    ipcRenderer.invoke('dialog:saveGrantedFile', options),

  // ============================================
  // Python Backend Communication
  // ============================================

  /**
   * Get the port the Python backend is running on
   */
  getBackendPort: (): Promise<number> => ipcRenderer.invoke('python:getPort'),

  /**
   * Check if Python backend is running
   */
  isPythonRunning: (): Promise<boolean> => ipcRenderer.invoke('python:isRunning'),

  /**
   * Restart the Python backend
   */
  restartPython: (): Promise<void> => ipcRenderer.invoke('python:restart'),

  /**
   * Subscribe to Python backend ready event
   */
  onPythonReady: (callback: (port: number) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, port: number): void => callback(port);
    ipcRenderer.on('python:ready', handler);
    return () => ipcRenderer.removeListener('python:ready', handler);
  },

  /**
   * Subscribe to Python backend starting event
   */
  onPythonStarting: (callback: () => void): (() => void) => {
    const handler = (): void => callback();
    ipcRenderer.on('python:starting', handler);
    return () => ipcRenderer.removeListener('python:starting', handler);
  },

  /**
   * Subscribe to Python backend error event
   */
  onPythonError: (callback: (error: string) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, error: string): void => callback(error);
    ipcRenderer.on('python:error', handler);
    return () => ipcRenderer.removeListener('python:error', handler);
  },

  // ============================================
  // Application Info
  // ============================================

  /**
   * Get the application version
   */
  getAppVersion: (): Promise<string> => ipcRenderer.invoke('app:getVersion'),

  /**
   * Get the application name
   */
  getAppName: (): Promise<string> => ipcRenderer.invoke('app:getName'),

  /**
   * Get platform information
   */
  getPlatform: (): Promise<string> => ipcRenderer.invoke('app:getPlatform'),

  /**
   * Check if running in development mode
   */
  isDev: (): Promise<boolean> => ipcRenderer.invoke('app:isDev'),

  // ============================================
  // Window Controls
  // ============================================

  /**
   * Minimize the window
   */
  minimizeWindow: (): void => ipcRenderer.send('window:minimize'),

  /**
   * Maximize/restore the window
   */
  maximizeWindow: (): void => ipcRenderer.send('window:maximize'),

  /**
   * Close the window
   */
  closeWindow: (): void => ipcRenderer.send('window:close'),

  /**
   * Toggle fullscreen mode
   */
  toggleFullscreen: (): void => ipcRenderer.send('window:toggleFullscreen'),

  /**
   * Open Chrome DevTools
   */
  openDevTools: (): void => ipcRenderer.send('window:openDevTools'),

  // ============================================
  // Shell Operations
  // ============================================

  /**
   * Open a URL in the default browser
   */
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('shell:openExternal', url),

  // ============================================
  // Clipboard Operations
  // ============================================

  /**
   * Copy text to clipboard
   */
  copyToClipboard: (text: string): void => ipcRenderer.send('clipboard:copy', text),

  /**
   * Read text from clipboard
   */
  readFromClipboard: (): Promise<string> => ipcRenderer.invoke('clipboard:read'),

  // ============================================
  // Log Events
  // ============================================

  /**
   * Subscribe to log messages from main process
   */
  onLog: (
    callback: (log: { level: 'info' | 'warn' | 'error' | 'debug'; source: 'python' | 'electron'; message: string }) => void
  ): (() => void) => {
    const handler = (
      _event: Electron.IpcRendererEvent,
      log: { level: 'info' | 'warn' | 'error' | 'debug'; source: 'python' | 'electron'; message: string }
    ): void => callback(log);
    ipcRenderer.on('log:message', handler);
    return () => ipcRenderer.removeListener('log:message', handler);
  },

  /**
   * Send a log message from renderer to main (for aggregation)
   */
  sendLog: (log: { level: 'info' | 'warn' | 'error' | 'debug'; message: string }): void => {
    ipcRenderer.send('log:fromRenderer', log);
  },

  /**
   * Signal that the renderer is ready to receive logs
   */
  signalLogReady: (): void => {
    ipcRenderer.send('log:rendererReady');
  },

  // ============================================
  // Resource Monitoring
  // ============================================

  /**
   * Get Electron process resource usage (main + renderer)
   */
  getElectronResources: (): Promise<{
    main: {
      memory_mb: number;
      heap_used_mb: number;
      heap_total_mb: number;
      cpu_percent?: number;
    };
    renderer: {
      memory_mb: number;
      cpu_percent: number;
    } | null;
    timestamp: number;
  }> => ipcRenderer.invoke('resources:getElectronUsage'),
};

// Expose the API to the renderer process
contextBridge.exposeInMainWorld('electronAPI', electronAPI);

// Type declaration for the exposed API
export type ElectronAPI = typeof electronAPI;
