import {
  ipcMain,
  dialog,
  app,
  shell,
  clipboard,
  BrowserWindow,
  type OpenDialogOptions,
} from 'electron';
import fs from 'fs/promises';
import path from 'path';
import { PythonManager, type NativeFileGrant } from './pythonManager';

type PythonManagerGetter = () => PythonManager | null;
type PythonRestarter = () => Promise<void>;

function requirePythonManager(pythonManager: PythonManager | null): PythonManager {
  if (!pythonManager) {
    throw new Error(
      'Native file authorization is unavailable because the Python backend is not initialized. Wait for startup to finish and select the file again.'
    );
  }
  return pythonManager;
}

/**
 * Set up all IPC handlers for communication between main and renderer processes
 */
export function setupIpcHandlers(
  getPythonManager: PythonManagerGetter,
  restartPython: PythonRestarter
): void {
  // ============================================
  // File Dialog Handlers
  // ============================================

  ipcMain.handle(
    'dialog:openFile',
    (
      event,
      options?: {
        title?: string;
        filters?: { name: string; extensions: string[] }[];
        multiple?: boolean;
      }
    ) => {
      const parentWindow = BrowserWindow.fromWebContents(event.sender);

      const dialogOptions = {
        title: options?.title || 'Open File',
        filters: options?.filters || [
          { name: 'FITS Files', extensions: ['fits', 'fit', 'fts'] },
          { name: 'HDF5 Files', extensions: ['hdf5', 'h5', 'hdf'] },
          { name: 'Text Files', extensions: ['txt', 'csv', 'dat', 'ascii'] },
          { name: 'All Files', extensions: ['*'] },
        ],
        properties: options?.multiple ? (['openFile', 'multiSelections'] as ('openFile' | 'multiSelections')[]) : (['openFile'] as ('openFile')[]),
      };

      const result = parentWindow
        ? dialog.showOpenDialogSync(parentWindow, dialogOptions)
        : dialog.showOpenDialogSync(dialogOptions);

      if (!result || result.length === 0) {
        return null;
      }

      return result;
    }
  );

  ipcMain.handle(
    'dialog:saveFile',
    (
      event,
      options?: {
        title?: string;
        defaultPath?: string;
        filters?: { name: string; extensions: string[] }[];
      }
    ) => {
      const parentWindow = BrowserWindow.fromWebContents(event.sender);

      const dialogOptions = {
        title: options?.title || 'Save File',
        defaultPath: options?.defaultPath,
        filters: options?.filters || [
          { name: 'FITS Files', extensions: ['fits'] },
          { name: 'HDF5 Files', extensions: ['hdf5'] },
          { name: 'CSV Files', extensions: ['csv'] },
          { name: 'All Files', extensions: ['*'] },
        ],
      };

      const result = parentWindow
        ? dialog.showSaveDialogSync(parentWindow, dialogOptions)
        : dialog.showSaveDialogSync(dialogOptions);

      return result || null;
    }
  );

  // Utility pages use signed variants of the native dialogs. The signature is
  // checked by FastAPI and binds each request to this exact path and access
  // mode, rather than trusting an arbitrary renderer-provided path string.
  ipcMain.handle(
    'dialog:openGrantedFile',
    async (
      event,
      options?: {
        title?: string;
        filters?: { name: string; extensions: string[] }[];
        multiple?: boolean;
      }
    ): Promise<NativeFileGrant[] | null> => {
      const parentWindow = BrowserWindow.fromWebContents(event.sender);
      const dialogOptions: OpenDialogOptions = {
        title: options?.title || 'Open Scientific File',
        properties: options?.multiple
          ? (['openFile', 'multiSelections'] as ('openFile' | 'multiSelections')[])
          : (['openFile'] as ('openFile')[]),
      };
      // On macOS, even valid custom scientific extensions can be disabled when
      // NSOpenPanel receives an extension filter. Omit the property entirely
      // for unrestricted pickers; the backend validates the selected format.
      if (options?.filters?.length) dialogOptions.filters = options.filters;
      const selected = parentWindow
        ? dialog.showOpenDialogSync(parentWindow, dialogOptions)
        : dialog.showOpenDialogSync(dialogOptions);
      if (!selected?.length) return null;
      const pythonManager = requirePythonManager(getPythonManager());
      return Promise.all(
        selected.map((selectedPath) => pythonManager.issueFileGrant(selectedPath, 'read'))
      );
    }
  );

  ipcMain.handle(
    'dialog:saveGrantedFile',
    async (
      event,
      options?: {
        title?: string;
        defaultPath?: string;
        filters?: { name: string; extensions: string[] }[];
      }
    ): Promise<NativeFileGrant | null> => {
      const parentWindow = BrowserWindow.fromWebContents(event.sender);
      const dialogOptions = {
        title: options?.title || 'Export Scientific Data',
        defaultPath: options?.defaultPath,
        filters: options?.filters || [
          { name: 'FITS', extensions: ['fits'] },
          { name: 'CSV', extensions: ['csv'] },
          { name: 'ECSV', extensions: ['ecsv'] },
          { name: 'JSON', extensions: ['json'] },
        ],
      };
      const selected = parentWindow
        ? dialog.showSaveDialogSync(parentWindow, dialogOptions)
        : dialog.showSaveDialogSync(dialogOptions);
      if (!selected) return null;
      return requirePythonManager(getPythonManager()).issueFileGrant(selected, 'write');
    }
  );

  ipcMain.handle('dialog:openDirectory', (event) => {
    const parentWindow = BrowserWindow.fromWebContents(event.sender);

    const dialogOptions = {
      title: 'Select Directory',
      properties: ['openDirectory'] as ('openDirectory')[],
    };

    const result = parentWindow
      ? dialog.showOpenDialogSync(parentWindow, dialogOptions)
      : dialog.showOpenDialogSync(dialogOptions);

    if (!result || result.length === 0) {
      return null;
    }

    return result[0];
  });

  // ============================================
  // File System Handlers
  // ============================================

  ipcMain.handle('file:exists', async (_event, filePath: string) => {
    try {
      await fs.access(filePath);
      return true;
    } catch {
      return false;
    }
  });

  // ============================================
  // Python Backend Handlers
  // ============================================

  ipcMain.handle('python:getPort', () => {
    const pythonManager = getPythonManager();
    return pythonManager?.getPort() || 8765;
  });

  ipcMain.handle('python:isRunning', () => {
    const pythonManager = getPythonManager();
    return pythonManager?.getIsRunning() || false;
  });

  // Restart goes through main.ts so the renderer receives the same
  // python:starting/python:ready/python:error events as initial startup —
  // calling pythonManager.restart() directly would leave the renderer's
  // backend status stale until a window reload.
  ipcMain.handle('python:restart', () => restartPython());

  // ============================================
  // Application Info Handlers
  // ============================================

  ipcMain.handle('app:getVersion', () => {
    return app.getVersion();
  });

  ipcMain.handle('app:getName', () => {
    return app.getName();
  });

  ipcMain.handle('app:getPlatform', () => {
    return process.platform;
  });

  ipcMain.handle('app:isDev', () => {
    return process.env.NODE_ENV === 'development' || !app.isPackaged;
  });

  // ============================================
  // Window Control Handlers
  // ============================================

  ipcMain.on('window:minimize', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    window?.minimize();
  });

  ipcMain.on('window:maximize', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (window?.isMaximized()) {
      window.unmaximize();
    } else {
      window?.maximize();
    }
  });

  ipcMain.on('window:close', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    window?.close();
  });

  ipcMain.on('window:toggleFullscreen', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (window) {
      window.setFullScreen(!window.isFullScreen());
    }
  });

  ipcMain.on('window:openDevTools', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (window) {
      window.webContents.openDevTools();
    }
  });

  // ============================================
  // Shell Handlers
  // ============================================

  ipcMain.handle('shell:openExternal', async (_event, url: string) => {
    await shell.openExternal(url);
  });

  ipcMain.on('shell:showItemInFolder', (_event, filePath: string) => {
    shell.showItemInFolder(path.normalize(filePath));
  });

  // ============================================
  // Clipboard Handlers
  // ============================================

  ipcMain.on('clipboard:copy', (_event, text: string) => {
    clipboard.writeText(text);
  });

  ipcMain.handle('clipboard:read', () => {
    return clipboard.readText();
  });

  // ============================================
  // Resource Monitoring Handlers
  // ============================================

  ipcMain.handle('resources:getElectronUsage', (event) => {
    // Get main process metrics
    const mainProcessMemory = process.memoryUsage();
    const mainCpuUsage = process.cpuUsage();

    // Get renderer process metrics
    const window = BrowserWindow.fromWebContents(event.sender);
    let rendererMetrics = null;

    if (window) {
      // Get all app metrics which includes renderer processes
      const appMetrics = app.getAppMetrics();

      // Find the renderer process for this window
      const rendererPid = window.webContents.getOSProcessId();
      const rendererProcess = appMetrics.find(m => m.pid === rendererPid);

      if (rendererProcess) {
        rendererMetrics = {
          memory_mb: rendererProcess.memory.workingSetSize / (1024 * 1024),
          cpu_percent: rendererProcess.cpu.percentCPUUsage,
        };
      }
    }

    // Main process metrics
    const mainMetrics: {
      memory_mb: number;
      heap_used_mb: number;
      heap_total_mb: number;
      cpu_user_ms: number;
      cpu_system_ms: number;
      cpu_percent?: number;
    } = {
      memory_mb: mainProcessMemory.rss / (1024 * 1024),
      heap_used_mb: mainProcessMemory.heapUsed / (1024 * 1024),
      heap_total_mb: mainProcessMemory.heapTotal / (1024 * 1024),
      // CPU usage is cumulative, convert to approximate percent
      // Note: This is microseconds since process start, not a percentage
      cpu_user_ms: mainCpuUsage.user / 1000,
      cpu_system_ms: mainCpuUsage.system / 1000,
    };

    // Get main process CPU percentage from app metrics
    const appMetrics = app.getAppMetrics();
    const mainPid = process.pid;
    const mainAppMetric = appMetrics.find(m => m.pid === mainPid);
    if (mainAppMetric) {
      mainMetrics['cpu_percent'] = mainAppMetric.cpu.percentCPUUsage;
    }

    return {
      main: mainMetrics,
      renderer: rendererMetrics,
      timestamp: Date.now(),
    };
  });
}
