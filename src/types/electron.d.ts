/**
 * Type definitions for Electron API exposed via preload script
 */

export interface ElectronAPI {
  // File System Operations
  openFile: (options?: {
    title?: string;
    filters?: { name: string; extensions: string[] }[];
    multiple?: boolean;
  }) => Promise<string[] | null>;

  saveFile: (options?: {
    title?: string;
    defaultPath?: string;
    filters?: { name: string; extensions: string[] }[];
  }) => Promise<string | null>;

  openDirectory: () => Promise<string | null>;

  readFile: (filePath: string) => Promise<ArrayBuffer>;

  writeFile: (filePath: string, data: ArrayBuffer | string) => Promise<void>;

  fileExists: (filePath: string) => Promise<boolean>;

  // Python Backend Communication
  getBackendPort: () => Promise<number>;

  isPythonRunning: () => Promise<boolean>;

  restartPython: () => Promise<void>;

  onPythonReady: (callback: (port: number) => void) => () => void;

  onPythonStarting: (callback: () => void) => () => void;

  onPythonError: (callback: (error: string) => void) => () => void;

  // Application Info
  getAppVersion: () => Promise<string>;

  getAppName: () => Promise<string>;

  getPlatform: () => Promise<string>;

  isDev: () => Promise<boolean>;

  // Window Controls
  minimizeWindow: () => void;

  maximizeWindow: () => void;

  closeWindow: () => void;

  toggleFullscreen: () => void;

  openDevTools: () => void;

  // Shell Operations
  openExternal: (url: string) => Promise<void>;

  showItemInFolder: (path: string) => void;

  // Clipboard Operations
  copyToClipboard: (text: string) => void;

  readFromClipboard: () => Promise<string>;

  // Log Events
  onLog: (
    callback: (log: {
      level: 'info' | 'warn' | 'error' | 'debug';
      source: 'python' | 'electron';
      message: string;
    }) => void
  ) => () => void;

  sendLog: (log: { level: 'info' | 'warn' | 'error' | 'debug'; message: string }) => void;

  signalLogReady: () => void;

  // Resource Monitoring
  getElectronResources: () => Promise<{
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
  }>;
}

declare global {
  interface Window {
    electronAPI: ElectronAPI;
  }
}

export {};
