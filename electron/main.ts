import { app, BrowserWindow, dialog, shell, ipcMain } from 'electron';
import path from 'path';
import { pathToFileURL } from 'url';
import { PythonManager, LogLevel, LogSource, LogMessage } from './pythonManager';
import { setupIpcHandlers } from './ipcHandlers';
import { createAppMenu } from './menu';
import {
  BackendStatusStore,
  type BackendStatusTransition,
} from './backendStatus';
import {
  isTrustedRendererLocation,
  shouldAuthenticateBackendRequest,
  withBackendSessionHeader,
} from './backendSessionPolicy';

let mainWindow: BrowserWindow | null = null;
let pythonManager: PythonManager | null = null;
let rendererReady = false;
const logHistory: LogMessage[] = [];  // Persistent history for replay
const MAX_LOG_HISTORY = 100;

const backendStatusStore = new BackendStatusStore((status) => {
  if (!mainWindow || mainWindow.isDestroyed()) return;

  mainWindow.webContents.send('python:status', status);

  // Retain the existing public bridge events for compatibility. The renderer
  // application uses only the atomic python:status contract below.
  switch (status.phase) {
    case 'starting':
      mainWindow.webContents.send('python:starting');
      break;
    case 'ready':
      mainWindow.webContents.send('python:ready', status.port);
      break;
    case 'error':
      mainWindow.webContents.send('python:error', status.error);
      break;
    case 'stopped':
      break;
  }
});

function publishBackendStatus(transition: BackendStatusTransition): void {
  backendStatusStore.publish(transition);
}

function getSafeBackendError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function getUnexpectedExitReason(code: number | null, signal: NodeJS.Signals | null): string {
  if (signal) return `signal ${signal}`;
  return `exit code ${code ?? 'unknown'}`;
}

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
  const rendererEntryUrl = isDev
    ? 'http://localhost:5173'
    : pathToFileURL(path.join(__dirname, '../dist/index.html')).toString();
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 768,
    show: false, // Don't show until ready
    webPreferences: {
      // .cjs extension is load-bearing: see the preload output comment in
      // electron.vite.config.ts ("type": "module" + Electron >= ~29).
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    // Pin the traffic lights (y:24 centers them in the 64px app header) and
    // enable the Window Controls Overlay API so the renderer can size its
    // titlebar inset from env(titlebar-area-x) — which tracks page zoom and
    // fullscreen, unlike any fixed pixel offset.
    trafficLightPosition: { x: 16, y: 24 },
    titleBarOverlay: true,
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
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isTrustedRendererLocation(url, rendererEntryUrl)) event.preventDefault();
  });

  // Authenticate only requests issued by this trusted top-level application
  // document to the exact Electron-managed backend. Renderer JavaScript never
  // receives the per-launch credential, and child/navigated pages are excluded.
  const trustedWindow = mainWindow;
  trustedWindow.webContents.session.webRequest.onBeforeSendHeaders(
    { urls: ['http://127.0.0.1/*'] },
    (details, callback) => {
      const manager = pythonManager;
      const authenticate =
        manager !== null &&
        shouldAuthenticateBackendRequest({
          requestUrl: details.url,
          method: details.method,
          backendPort: manager.getPort(),
          requestWebContentsId: details.webContentsId,
          trustedWebContentsId: trustedWindow.webContents.id,
          isMainFrame:
            details.frame?.frameTreeNodeId ===
            trustedWindow.webContents.mainFrame.frameTreeNodeId,
          frameUrl: details.frame?.url ?? '',
          rendererEntryUrl,
        });
      let secret: string | undefined;
      if (authenticate) {
        try {
          secret = manager.getBackendSessionSecret();
        } catch {
          secret = undefined;
        }
      }
      callback({
        requestHeaders: withBackendSessionHeader(details.requestHeaders, secret),
      });
    }
  );

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
    await mainWindow.loadURL(rendererEntryUrl);
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
    const manager = new PythonManager();
    pythonManager = manager;

    // Set the log callback so pythonManager uses our buffered logging
    manager.setLogCallback((level, message, source) => {
      sendLog(level, message, source);
    });
    manager.setUnexpectedExitCallback(({ code, signal }) => {
      // Ignore a delayed notification from a manager that has since been
      // replaced by a fresh initialization attempt.
      if (pythonManager !== manager) return;
      const reason = getUnexpectedExitReason(code, signal);
      sendLog('error', `Python backend exited unexpectedly with ${reason}`);
      publishBackendStatus({
        phase: 'error',
        error: `The Python backend exited unexpectedly (${reason}). Restart the backend to continue.`,
      });
    });

    publishBackendStatus({ phase: 'starting' });
    sendLog('info', 'Starting Python backend...');

    await manager.start();

    publishBackendStatus({ phase: 'ready', port: manager.getPort() });

    sendLog('info', `Python backend started successfully on port ${manager.getPort()}`);
  } catch (error) {
    sendLog('error', `Failed to start Python backend: ${error}`);
    publishBackendStatus({ phase: 'error', error: getSafeBackendError(error) });

    // Show error dialog
    dialog.showErrorBox(
      'Python Backend Error',
      `Failed to start the Python backend. Please ensure Python and required dependencies are installed.\n\nError: ${error}`
    );
  }
}

/**
 * Restart the Python backend, emitting the same renderer events as initial
 * startup so the backend status in the UI never goes stale. Errors are
 * reported via python:error rather than rethrown — the renderer's restart
 * button awaits the IPC call without a catch.
 */
async function restartBackend(): Promise<void> {
  if (!pythonManager) {
    await initializeApp();
    return;
  }

  publishBackendStatus({ phase: 'starting' });
  sendLog('info', 'Restarting Python backend...');

  try {
    await pythonManager.restart();
    publishBackendStatus({ phase: 'ready', port: pythonManager.getPort() });
    sendLog('info', `Python backend restarted successfully on port ${pythonManager.getPort()}`);
  } catch (error) {
    sendLog('error', `Failed to restart Python backend: ${error}`);
    publishBackendStatus({ phase: 'error', error: getSafeBackendError(error) });
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
  setupIpcHandlers(
    () => pythonManager,
    restartBackend,
    () => backendStatusStore.getSnapshot()
  );

  await createWindow();
  await initializeApp();

  app.on('activate', async () => {
    // On macOS, re-create the window when the dock icon is clicked.
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();

      // The freshly-loaded renderer subscribes and reads the authoritative
      // snapshot, so a ready notification does not need to be timed around its
      // mount. Reinitialize only if the process is no longer running.
      if (!pythonManager || !pythonManager.getIsRunning()) {
        await initializeApp();
      }
    }
  });
});

app.on('window-all-closed', async () => {
  // On macOS the app (and its Python backend) stays alive when all windows are
  // closed — the user reopens via the dock and we want the backend still there
  // to reconnect to. Tearing it down here meant a reopened window had no backend
  // and got stuck on "Starting...". Only fully shut down on platforms where
  // closing the last window means quitting; final cleanup lives in 'before-quit'.
  if (process.platform !== 'darwin') {
    if (pythonManager) {
      await pythonManager.stop();
      pythonManager = null;
      publishBackendStatus({ phase: 'stopped' });
    }
    app.quit();
  }
});

app.on('before-quit', async () => {
  // Ensure Python backend is stopped
  if (pythonManager) {
    await pythonManager.stop();
    pythonManager = null;
    publishBackendStatus({ phase: 'stopped' });
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
