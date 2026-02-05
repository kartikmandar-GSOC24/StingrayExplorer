import { app, BrowserWindow, dialog, shell, ipcMain } from 'electron';
import path from 'path';
import { PythonManager, LogLevel, LogSource, LogMessage } from './pythonManager';
import { setupIpcHandlers } from './ipcHandlers';
import { createAppMenu } from './menu';

let mainWindow: BrowserWindow | null = null;
let pythonManager: PythonManager | null = null;
let rendererReady = false;
const logHistory: LogMessage[] = [];  // Persistent history for replay
const MAX_LOG_HISTORY = 100;

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

/**
 * Send a log message to the renderer process
 * Always stores in history for replay on new connections
 */
function sendLog(level: LogLevel, message: string, source: LogSource = 'electron'): void {
  console.log(`[${source}] ${message}`);
  const logMessage: LogMessage = { level, source, message };

  // Always store in history for replay
  logHistory.push(logMessage);
  if (logHistory.length > MAX_LOG_HISTORY) {
    logHistory.shift();
  }

  // Send immediately if renderer ready
  if (rendererReady && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('log:message', logMessage);
  }
}

async function createWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 768,
    show: false, // Don't show until ready
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    icon: isDev
      ? path.join(__dirname, '../resources/icon.png')
      : path.join(process.resourcesPath, 'icon.png'),
    backgroundColor: '#ffffff',
  });

  // Set up the application menu
  createAppMenu(mainWindow);

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
    // DevTools can be opened manually with Ctrl+Shift+I or View menu
  });

  // Handle external links
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Add right-click context menu for copy/paste
  mainWindow.webContents.on('context-menu', (_event, params) => {
    const { Menu, MenuItem } = require('electron');
    const menu = new Menu();

    // Add "Copy" if text is selected
    if (params.selectionText) {
      menu.append(new MenuItem({
        label: 'Copy',
        role: 'copy',
      }));
    }

    // Add "Paste" if in an editable field
    if (params.isEditable) {
      menu.append(new MenuItem({
        label: 'Paste',
        role: 'paste',
      }));
    }

    // Add "Cut" if text is selected and in editable field
    if (params.selectionText && params.isEditable) {
      menu.insert(0, new MenuItem({
        label: 'Cut',
        role: 'cut',
      }));
    }

    // Add "Select All" for editable fields
    if (params.isEditable) {
      menu.append(new MenuItem({
        label: 'Select All',
        role: 'selectAll',
      }));
    }

    // Only show menu if it has items
    if (menu.items.length > 0) {
      menu.popup();
    }
  });

  // Load the app
  if (isDev) {
    await mainWindow.loadURL('http://localhost:5173');
  } else {
    await mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

async function initializeApp(): Promise<void> {
  try {
    // Start Python backend
    pythonManager = new PythonManager();

    // Set the log callback so pythonManager uses our buffered logging
    pythonManager.setLogCallback((level, message, source) => {
      sendLog(level, message, source);
    });

    // Notify renderer that we're starting Python
    mainWindow?.webContents.send('python:starting');
    sendLog('info', 'Starting Python backend...');

    await pythonManager.start();

    // Notify renderer that Python is ready
    mainWindow?.webContents.send('python:ready', pythonManager.getPort());

    sendLog('info', `Python backend started successfully on port ${pythonManager.getPort()}`);
  } catch (error) {
    sendLog('error', `Failed to start Python backend: ${error}`);
    mainWindow?.webContents.send('python:error', String(error));

    // Show error dialog
    dialog.showErrorBox(
      'Python Backend Error',
      `Failed to start the Python backend. Please ensure Python and required dependencies are installed.\n\nError: ${error}`
    );
  }
}

// Handle renderer ready signal
ipcMain.on('log:rendererReady', () => {
  rendererReady = true;
  // Note: We no longer replay log history here to avoid duplicate logs.
  // Early startup logs are visible in the terminal.
  // Real-time logs come through the Python SSE stream once the backend is ready.
});

// App lifecycle
app.whenReady().then(async () => {
  // Set the application name (important for Linux desktop integration)
  app.setName('Stingray Explorer');

  // Set up IPC handlers before creating window
  setupIpcHandlers(() => pythonManager);

  await createWindow();
  await initializeApp();

  app.on('activate', async () => {
    // On macOS, re-create window when dock icon is clicked
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});

app.on('window-all-closed', async () => {
  // Stop Python backend
  if (pythonManager) {
    await pythonManager.stop();
    pythonManager = null;
  }

  // On macOS, don't quit when all windows are closed
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', async () => {
  // Ensure Python backend is stopped
  if (pythonManager) {
    await pythonManager.stop();
    pythonManager = null;
  }
});

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
  sendLog('error', `Uncaught exception: ${error.message}`);
  dialog.showErrorBox('Unexpected Error', `An unexpected error occurred:\n\n${error.message}`);
});

process.on('unhandledRejection', (reason) => {
  sendLog('error', `Unhandled rejection: ${reason}`);
});
