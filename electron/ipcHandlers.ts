import { ipcMain, dialog, app, shell, clipboard, BrowserWindow } from 'electron';
import fs from 'fs/promises';
import path from 'path';
import { PythonManager } from './pythonManager';

type PythonManagerGetter = () => PythonManager | null;

/**
 * Set up all IPC handlers for communication between main and renderer processes
 */
export function setupIpcHandlers(getPythonManager: PythonManagerGetter): void {
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
        properties: options?.multiple ? ['openFile', 'multiSelections'] as const : ['openFile'] as const,
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

  ipcMain.handle('dialog:openDirectory', (event) => {
    const parentWindow = BrowserWindow.fromWebContents(event.sender);

    const dialogOptions = {
      title: 'Select Directory',
      properties: ['openDirectory'] as const,
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

  ipcMain.handle('file:read', async (_event, filePath: string) => {
    try {
      const buffer = await fs.readFile(filePath);
      return buffer.buffer;
    } catch (error) {
      throw new Error(`Failed to read file: ${error}`);
    }
  });

  ipcMain.handle('file:write', async (_event, filePath: string, data: ArrayBuffer | string) => {
    try {
      const buffer = typeof data === 'string' ? data : Buffer.from(data);
      await fs.writeFile(filePath, buffer);
    } catch (error) {
      throw new Error(`Failed to write file: ${error}`);
    }
  });

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

  ipcMain.handle('python:restart', async () => {
    const pythonManager = getPythonManager();
    if (pythonManager) {
      await pythonManager.restart();
    }
  });

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
}
