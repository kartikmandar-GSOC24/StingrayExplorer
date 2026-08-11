import { app, Menu, shell, BrowserWindow, MenuItemConstructorOptions } from 'electron';

const isMac = process.platform === 'darwin';

/**
 * Create the application menu
 */
export function createAppMenu(mainWindow: BrowserWindow): void {
  const template: MenuItemConstructorOptions[] = [
    // App menu (macOS only)
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: 'about' as const },
              { type: 'separator' as const },
              {
                label: 'Preferences...',
                accelerator: 'CmdOrCtrl+,',
                click: (): void => {
                  mainWindow.webContents.send('menu:preferences');
                },
              },
              { type: 'separator' as const },
              { role: 'services' as const },
              { type: 'separator' as const },
              { role: 'hide' as const },
              { role: 'hideOthers' as const },
              { role: 'unhide' as const },
              { type: 'separator' as const },
              { role: 'quit' as const },
            ],
          },
        ]
      : []),

    // File menu
    {
      label: 'File',
      submenu: [
        {
          label: 'Open File...',
          accelerator: 'CmdOrCtrl+O',
          click: (): void => {
            mainWindow.webContents.send('menu:openFile');
          },
        },
        {
          label: 'Open Recent',
          role: 'recentDocuments' as const,
          submenu: [
            {
              label: 'Clear Recent',
              role: 'clearRecentDocuments' as const,
            },
          ],
        },
        { type: 'separator' },
        {
          label: 'Save',
          accelerator: 'CmdOrCtrl+S',
          click: (): void => {
            mainWindow.webContents.send('menu:save');
          },
        },
        {
          label: 'Save As...',
          accelerator: 'CmdOrCtrl+Shift+S',
          click: (): void => {
            mainWindow.webContents.send('menu:saveAs');
          },
        },
        {
          label: 'Export...',
          accelerator: 'CmdOrCtrl+E',
          click: (): void => {
            mainWindow.webContents.send('menu:export');
          },
        },
        { type: 'separator' },
        isMac ? { role: 'close' as const } : { role: 'quit' as const },
      ],
    },

    // Edit menu
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        ...(isMac
          ? [
              { role: 'pasteAndMatchStyle' as const },
              { role: 'delete' as const },
              { role: 'selectAll' as const },
            ]
          : [{ role: 'delete' as const }, { type: 'separator' as const }, { role: 'selectAll' as const }]),
      ],
    },

    // View menu
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { type: 'separator' },
        {
          label: 'Toggle Sidebar',
          accelerator: 'CmdOrCtrl+B',
          click: (): void => {
            mainWindow.webContents.send('menu:toggleSidebar');
          },
        },
      ],
    },

    // Analysis menu
    {
      label: 'Analysis',
      submenu: [
        {
          label: 'QuickLook',
          submenu: [
            {
              label: 'Power Spectrum',
              click: (): void => {
                mainWindow.webContents.send('menu:navigate', '/quicklook/power-spectrum');
              },
            },
            {
              label: 'Light Curve',
              click: (): void => {
                mainWindow.webContents.send('menu:navigate', '/quicklook/light-curve');
              },
            },
            {
              label: 'Cross Spectrum',
              click: (): void => {
                mainWindow.webContents.send('menu:navigate', '/quicklook/cross-spectrum');
              },
            },
          ],
        },
        {
          label: 'Pulsar',
          submenu: [
            {
              label: 'Period Search',
              click: (): void => {
                mainWindow.webContents.send('menu:navigate', '/pulsar/search');
              },
            },
            {
              label: 'Phase Folding',
              click: (): void => {
                mainWindow.webContents.send('menu:navigate', '/pulsar/folding');
              },
            },
          ],
        },
        {
          label: 'Modeling',
          submenu: [
            {
              label: 'Model Builder',
              click: (): void => {
                mainWindow.webContents.send('menu:navigate', '/modeling/builder');
              },
            },
            {
              label: 'MCMC Fitting',
              click: (): void => {
                mainWindow.webContents.send('menu:navigate', '/modeling/mcmc');
              },
            },
          ],
        },
        { type: 'separator' },
        {
          label: 'Simulator',
          click: (): void => {
            mainWindow.webContents.send('menu:navigate', '/simulator');
          },
        },
      ],
    },

    // Window menu
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        ...(isMac
          ? [{ type: 'separator' as const }, { role: 'front' as const }, { type: 'separator' as const }, { role: 'window' as const }]
          : [{ role: 'close' as const }]),
      ],
    },

    // Help menu
    {
      role: 'help',
      submenu: [
        {
          label: 'Stingray Documentation',
          click: async (): Promise<void> => {
            await shell.openExternal('https://docs.stingray.science/');
          },
        },
        {
          label: 'Stingray Explorer Wiki',
          click: async (): Promise<void> => {
            await shell.openExternal('https://github.com/kartikmandar-GSOC24/StingrayExplorer/wiki');
          },
        },
        { type: 'separator' },
        {
          label: 'Report Issue',
          click: async (): Promise<void> => {
            await shell.openExternal('https://github.com/kartikmandar-GSOC24/StingrayExplorer/issues');
          },
        },
        { type: 'separator' },
        {
          label: 'About Stingray',
          click: async (): Promise<void> => {
            await shell.openExternal('https://stingray.science/');
          },
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}
