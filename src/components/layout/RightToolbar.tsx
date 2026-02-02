import React, { useState, useEffect } from 'react';
import {
  Box,
  IconButton,
  Tooltip,
  Divider,
  Badge,
  CircularProgress,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Typography,
  List,
  ListItem,
  ListItemButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Popover,
  Stack,
  Slider,
  Chip,
  Link,
} from '@mui/material';
import TerminalIcon from '@mui/icons-material/Terminal';
import BugReportIcon from '@mui/icons-material/BugReport';
import NotificationsIcon from '@mui/icons-material/Notifications';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import LogoutIcon from '@mui/icons-material/Logout';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import InfoIcon from '@mui/icons-material/Info';
import DeveloperModeIcon from '@mui/icons-material/DeveloperMode';
import MemoryIcon from '@mui/icons-material/Memory';
import StorageIcon from '@mui/icons-material/Storage';
import GitHubIcon from '@mui/icons-material/GitHub';
import MenuBookIcon from '@mui/icons-material/MenuBook';
import ForumIcon from '@mui/icons-material/Forum';
import { useUIStore, Notification } from '@/store/uiStore';
import { useLogStore } from '@/store/logStore';
import { useBackendContext } from '@/App';

const TOOLBAR_WIDTH = 52;
const HEADER_HEIGHT = 64;
const LOG_PANEL_COLLAPSED_HEIGHT = 40;

interface RightToolbarProps {
  visible?: boolean;
}

/**
 * Right toolbar with quick actions, status indicators, and system info
 * (Consolidated from previous Footer + RightToolbar)
 */
const RightToolbar: React.FC<RightToolbarProps> = ({ visible = true }) => {
  const {
    isProcessing,
    processingMessage,
    processingProgress,
    notifications,
    unreadNotificationCount,
    markNotificationRead,
    clearNotifications,
    addNotification,
    systemResources,
    setSystemResources,
  } = useUIStore();

  const { togglePanel: toggleLogPanel, isOpen: logPanelOpen } = useLogStore();
  const { isReady: backendReady, port: backendPort } = useBackendContext();

  // App version
  const [version, setVersion] = useState<string>('');

  // Menu/popover states
  const [notificationsAnchor, setNotificationsAnchor] = useState<null | HTMLElement>(null);
  const [debugAnchor, setDebugAnchor] = useState<null | HTMLElement>(null);
  const [helpAnchor, setHelpAnchor] = useState<null | HTMLElement>(null);
  const [resourcesAnchor, setResourcesAnchor] = useState<null | HTMLElement>(null);

  // Dialog states
  const [selectedNotification, setSelectedNotification] = useState<Notification | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);

  // Resource monitoring state
  const [monitoringActive, setMonitoringActive] = useState<boolean>(false);
  const [maxCpuThreads, setMaxCpuThreads] = useState<number>(4);
  const [maxRamGb, setMaxRamGb] = useState<number>(8);

  // Get app version on mount
  useEffect(() => {
    const getVersion = async (): Promise<void> => {
      if (window.electronAPI) {
        const appVersion = await window.electronAPI.getAppVersion();
        setVersion(appVersion);
      }
    };
    getVersion();
  }, []);

  // Fetch system resources from backend
  const fetchResources = async (): Promise<void> => {
    if (!backendReady || !backendPort) return;

    try {
      const response = await fetch(`http://127.0.0.1:${backendPort}/api/status`);
      if (response.ok) {
        const data = await response.json();
        if (data.memory_usage) {
          setSystemResources({
            cpuPercent: data.memory_usage.cpu_percent || 0,
            memoryUsedGb: (data.memory_usage.memory_used_mb || 0) / 1024,
            memoryTotalGb: (data.memory_usage.memory_total_mb || 0) / 1024,
            memoryPercent: data.memory_usage.memory_percent || 0,
          });
        }
      }
    } catch {
      // Backend might not be ready
    }
  };

  // Poll resources when monitoring is active
  useEffect(() => {
    if (!monitoringActive) return;

    fetchResources();
    const interval = setInterval(fetchResources, 10000);
    return () => clearInterval(interval);
  }, [monitoringActive, backendReady, backendPort]);

  // Toggle resource monitoring
  const handleToggleMonitoring = (): void => {
    if (!monitoringActive) {
      fetchResources();
    }
    setMonitoringActive((prev) => !prev);
  };

  const handleOpenExternal = async (url: string): Promise<void> => {
    if (window.electronAPI) {
      await window.electronAPI.openExternal(url);
    }
  };

  const handleOpenDevTools = (): void => {
    if (window.electronAPI) {
      window.electronAPI.openDevTools();
    }
  };

  const handleToggleTerminal = (): void => {
    toggleLogPanel();
  };

  const handleQuitApp = (): void => {
    if (window.electronAPI) {
      window.electronAPI.closeWindow();
    }
  };

  const handleNotificationClick = (notification: Notification): void => {
    markNotificationRead(notification.id);
    setSelectedNotification(notification);
  };

  const handleCloseNotificationDetail = (): void => {
    setSelectedNotification(null);
  };

  const getNotificationIcon = (type: Notification['type']): React.ReactNode => {
    switch (type) {
      case 'success':
        return <CheckCircleIcon fontSize="small" color="success" />;
      case 'error':
        return <ErrorIcon fontSize="small" color="error" />;
      case 'warning':
        return <WarningIcon fontSize="small" color="warning" />;
      default:
        return <InfoIcon fontSize="small" color="info" />;
    }
  };

  const getResourceColor = (): 'success' | 'warning' | 'error' | 'default' => {
    if (!systemResources || !monitoringActive) return 'default';
    const memPercent = systemResources.memoryPercent;
    if (memPercent > 90) return 'error';
    if (memPercent > 70) return 'warning';
    return 'success';
  };

  if (!visible) {
    return null;
  }

  return (
    <Box
      sx={{
        width: TOOLBAR_WIDTH,
        height: `calc(100vh - ${HEADER_HEIGHT}px - ${LOG_PANEL_COLLAPSED_HEIGHT}px)`,
        backgroundColor: 'background.paper',
        borderLeft: '1px solid',
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        py: 1,
        gap: 0.5,
        position: 'fixed',
        top: HEADER_HEIGHT,
        right: 0,
        zIndex: 1100,
        overflowY: 'auto',
        overflowX: 'hidden',
      }}
    >
      {/* === Status Section === */}

      {/* Processing indicator + Backend status */}
      <Tooltip
        title={
          <Box>
            <Typography variant="caption" display="block">
              {isProcessing ? processingMessage || 'Processing...' : 'System idle'}
            </Typography>
            <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
              Backend: {backendReady ? `Connected (port ${backendPort})` : 'Disconnected'}
            </Typography>
          </Box>
        }
        placement="left"
      >
        <Box sx={{ position: 'relative', display: 'inline-flex' }}>
          <IconButton
            size="small"
            color={isProcessing ? 'primary' : 'default'}
            sx={{
              animation: isProcessing ? 'pulse 1.5s infinite' : 'none',
              '@keyframes pulse': {
                '0%': { opacity: 0.6 },
                '50%': { opacity: 1 },
                '100%': { opacity: 0.6 },
              },
            }}
          >
            {isProcessing ? (
              processingProgress !== null ? (
                <CircularProgress size={20} variant="determinate" value={processingProgress} />
              ) : (
                <CircularProgress size={20} />
              )
            ) : (
              <HourglassEmptyIcon fontSize="small" />
            )}
          </IconButton>
          {/* Backend status dot */}
          <Box
            sx={{
              position: 'absolute',
              bottom: 2,
              right: 2,
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor: backendReady ? 'success.main' : 'error.main',
              border: '1px solid',
              borderColor: 'background.paper',
            }}
          />
        </Box>
      </Tooltip>

      {/* Resource Monitor */}
      <Tooltip title={monitoringActive ? 'System resources (click to configure)' : 'Start resource monitoring'} placement="left">
        <IconButton
          size="small"
          onClick={(e) => setResourcesAnchor(e.currentTarget)}
          color={getResourceColor()}
          sx={{
            animation: monitoringActive ? 'pulse-slow 3s infinite' : 'none',
            '@keyframes pulse-slow': {
              '0%, 100%': { opacity: 1 },
              '50%': { opacity: 0.7 },
            },
          }}
        >
          <MemoryIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Terminal / Log Panel */}
      <Tooltip title={logPanelOpen ? 'Hide console' : 'Show console'} placement="left">
        <IconButton
          onClick={handleToggleTerminal}
          size="small"
          color={logPanelOpen ? 'primary' : 'default'}
        >
          <TerminalIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Divider sx={{ width: '80%', my: 0.5 }} />

      {/* === Actions Section === */}

      {/* Notifications */}
      <Tooltip title="Notifications" placement="left">
        <IconButton
          onClick={(e) => setNotificationsAnchor(e.currentTarget)}
          size="small"
        >
          <Badge badgeContent={unreadNotificationCount} color="error" max={9}>
            <NotificationsIcon fontSize="small" />
          </Badge>
        </IconButton>
      </Tooltip>

      {/* Help & Support */}
      <Tooltip title="Help & Support" placement="left">
        <IconButton
          onClick={(e) => setHelpAnchor(e.currentTarget)}
          size="small"
        >
          <HelpOutlineIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Debug Tools */}
      <Tooltip title="Debug tools" placement="left">
        <IconButton
          onClick={(e) => setDebugAnchor(e.currentTarget)}
          size="small"
        >
          <BugReportIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Spacer */}
      <Box sx={{ flex: 1 }} />

      <Divider sx={{ width: '80%', my: 0.5 }} />

      {/* === Bottom Section === */}

      {/* About */}
      <Tooltip title="About Stingray Explorer" placement="left">
        <IconButton
          onClick={() => setAboutOpen(true)}
          size="small"
        >
          <InfoIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Quit */}
      <Tooltip title="Quit application" placement="left">
        <IconButton onClick={handleQuitApp} size="small" color="error">
          <LogoutIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* === Menus & Dialogs === */}

      {/* Resources Popover */}
      <Popover
        open={Boolean(resourcesAnchor)}
        anchorEl={resourcesAnchor}
        onClose={() => setResourcesAnchor(null)}
        anchorOrigin={{ vertical: 'center', horizontal: 'left' }}
        transformOrigin={{ vertical: 'center', horizontal: 'right' }}
        PaperProps={{ sx: { width: 300, p: 2 } }}
      >
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="subtitle2">System Resources</Typography>
          <Chip
            label={monitoringActive ? 'Active' : 'Paused'}
            size="small"
            color={monitoringActive ? 'success' : 'default'}
            onClick={handleToggleMonitoring}
            sx={{ cursor: 'pointer' }}
          />
        </Box>

        {monitoringActive && systemResources ? (
          <Box sx={{ mb: 2, p: 1.5, bgcolor: 'action.hover', borderRadius: 1 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="body2">CPU</Typography>
              <Typography variant="body2" fontWeight="medium">
                {systemResources.cpuPercent.toFixed(1)}%
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
              <Typography variant="body2">RAM</Typography>
              <Typography variant="body2" fontWeight="medium">
                {systemResources.memoryUsedGb.toFixed(1)} / {systemResources.memoryTotalGb.toFixed(0)} GB
                ({systemResources.memoryPercent.toFixed(1)}%)
              </Typography>
            </Box>
          </Box>
        ) : (
          <Box sx={{ mb: 2, p: 1.5, bgcolor: 'action.hover', borderRadius: 1, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {monitoringActive ? 'Loading...' : 'Click "Paused" to start monitoring'}
            </Typography>
          </Box>
        )}

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          Resource Limits (for analysis tasks)
        </Typography>

        <Stack spacing={2}>
          <Box>
            <Typography variant="body2" gutterBottom>
              Max CPU Threads: {maxCpuThreads}
            </Typography>
            <Slider
              value={maxCpuThreads}
              onChange={(_, value) => setMaxCpuThreads(value as number)}
              step={1}
              marks
              min={1}
              max={16}
              size="small"
              valueLabelDisplay="auto"
            />
          </Box>

          <Box>
            <Typography variant="body2" gutterBottom>
              Max RAM (GB): {maxRamGb}
            </Typography>
            <Slider
              value={maxRamGb}
              onChange={(_, value) => setMaxRamGb(value as number)}
              step={1}
              marks
              min={1}
              max={32}
              size="small"
              valueLabelDisplay="auto"
            />
          </Box>
        </Stack>
      </Popover>

      {/* Notifications Menu */}
      <Menu
        anchorEl={notificationsAnchor}
        open={Boolean(notificationsAnchor)}
        onClose={() => setNotificationsAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        PaperProps={{ sx: { width: 320, maxHeight: 400 } }}
      >
        <Box sx={{ px: 2, py: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="subtitle2">Notifications</Typography>
          {notifications.length > 0 && (
            <Button size="small" onClick={clearNotifications} sx={{ textTransform: 'none' }}>
              Clear All
            </Button>
          )}
        </Box>
        <Divider />
        {notifications.length === 0 ? (
          <Box sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              No notifications
            </Typography>
          </Box>
        ) : (
          <List dense sx={{ py: 0 }}>
            {notifications.slice(0, 10).map((notification) => (
              <ListItem key={notification.id} disablePadding>
                <ListItemButton
                  onClick={() => handleNotificationClick(notification)}
                  sx={{
                    opacity: notification.read ? 0.6 : 1,
                    bgcolor: notification.read ? 'transparent' : 'action.hover',
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 36 }}>
                    {getNotificationIcon(notification.type)}
                  </ListItemIcon>
                  <ListItemText
                    primary={notification.title}
                    secondary={notification.message}
                    primaryTypographyProps={{ variant: 'body2', fontWeight: notification.read ? 400 : 600 }}
                    secondaryTypographyProps={{ variant: 'caption', noWrap: true }}
                  />
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        )}
      </Menu>

      {/* Help Menu */}
      <Menu
        anchorEl={helpAnchor}
        open={Boolean(helpAnchor)}
        onClose={() => setHelpAnchor(null)}
        anchorOrigin={{ vertical: 'center', horizontal: 'left' }}
        transformOrigin={{ vertical: 'center', horizontal: 'right' }}
      >
        <MenuItem onClick={() => { handleOpenExternal('https://docs.stingray.science/'); setHelpAnchor(null); }}>
          <ListItemIcon>
            <MenuBookIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Documentation</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { handleOpenExternal('https://github.com/kartikmandar-GSOC24/StingrayExplorer/issues'); setHelpAnchor(null); }}>
          <ListItemIcon>
            <BugReportIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Report Issue</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { handleOpenExternal('https://github.com/StingraySoftware/stingray/discussions'); setHelpAnchor(null); }}>
          <ListItemIcon>
            <ForumIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Community</ListItemText>
        </MenuItem>
        <Divider />
        <MenuItem onClick={() => { handleOpenExternal('https://github.com/StingraySoftware/stingray'); setHelpAnchor(null); }}>
          <ListItemIcon>
            <GitHubIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Stingray GitHub</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { handleOpenExternal('https://github.com/kartikmandar-GSOC24/StingrayExplorer'); setHelpAnchor(null); }}>
          <ListItemIcon>
            <GitHubIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Explorer GitHub</ListItemText>
        </MenuItem>
      </Menu>

      {/* Debug Menu */}
      <Menu
        anchorEl={debugAnchor}
        open={Boolean(debugAnchor)}
        onClose={() => setDebugAnchor(null)}
        anchorOrigin={{ vertical: 'center', horizontal: 'left' }}
        transformOrigin={{ vertical: 'center', horizontal: 'right' }}
      >
        <MenuItem onClick={() => { handleOpenDevTools(); setDebugAnchor(null); }}>
          <ListItemIcon>
            <DeveloperModeIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Open DevTools</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => {
          addNotification({ type: 'success', title: 'Test', message: 'Test notification sent!' });
          setDebugAnchor(null);
        }}>
          <ListItemIcon>
            <NotificationsIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Test Notification</ListItemText>
        </MenuItem>
        <Divider />
        <MenuItem disabled>
          <ListItemIcon>
            <StorageIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary="Backend"
            secondary={backendReady ? `Port ${backendPort}` : 'Disconnected'}
          />
        </MenuItem>
      </Menu>

      {/* About Dialog */}
      <Dialog
        open={aboutOpen}
        onClose={() => setAboutOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <img
              src="/assets/images/stingray_explorer.png"
              alt="Stingray Explorer"
              style={{ width: 32, height: 32 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            />
            <Box>
              <Typography variant="h6">Stingray Explorer</Typography>
              <Typography variant="caption" color="text.secondary">
                {version ? `Version ${version}` : 'Desktop Application'} | © {new Date().getFullYear()} Kartik Mandar
              </Typography>
            </Box>
          </Box>
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" paragraph>
            Stingray Explorer is a comprehensive data analysis and visualization dashboard for X-ray astronomy
            time series data. Built on top of the{' '}
            <Link component="button" onClick={() => handleOpenExternal('https://github.com/StingraySoftware/stingray')}>
              Stingray
            </Link>{' '}
            Python library for spectral-timing analysis.
          </Typography>

          <Typography variant="subtitle2" gutterBottom sx={{ mt: 2 }}>
            Core Dependencies
          </Typography>
          <Typography variant="body2" component="div">
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://stingray.readthedocs.io/')}>
                  Stingray
                </Link>{' '}
                - Spectral-timing software
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://www.astropy.org/')}>
                  Astropy
                </Link>{' '}
                - Core astronomy library
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://numpy.org/')}>
                  NumPy
                </Link>{' '}
                & SciPy - Scientific computing
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://fastapi.tiangolo.com/')}>
                  FastAPI
                </Link>{' '}
                - Backend framework
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://www.electronjs.org/')}>
                  Electron
                </Link>{' '}
                - Desktop framework
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://react.dev/')}>
                  React
                </Link>{' '}
                & Material UI - Frontend
              </li>
            </ul>
          </Typography>

          <Typography variant="subtitle2" gutterBottom sx={{ mt: 2 }}>
            Acknowledgements
          </Typography>
          <Typography variant="body2">
            This project was developed as part of Google Summer of Code 2024 under the OpenAstronomy
            organization. Special thanks to the Stingray team and mentors for their guidance and support.
          </Typography>

          <Typography variant="subtitle2" gutterBottom sx={{ mt: 2 }}>
            Contact
          </Typography>
          <Typography variant="body2">
            Kartik Mandar -{' '}
            <Link component="button" onClick={() => handleOpenExternal('https://github.com/kartikmandar')}>
              @kartikmandar
            </Link>
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => handleOpenExternal('https://github.com/kartikmandar-GSOC24/StingrayExplorer')}
            startIcon={<GitHubIcon />}
          >
            View on GitHub
          </Button>
          <Button onClick={() => setAboutOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Notification Detail Dialog */}
      <Dialog
        open={Boolean(selectedNotification)}
        onClose={handleCloseNotificationDetail}
        maxWidth="sm"
        fullWidth
      >
        {selectedNotification && (
          <>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {getNotificationIcon(selectedNotification.type)}
              <Typography variant="h6" component="span">
                {selectedNotification.title}
              </Typography>
            </DialogTitle>
            <DialogContent dividers>
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {selectedNotification.message}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
                {new Date(selectedNotification.timestamp).toLocaleString()}
              </Typography>
            </DialogContent>
            <DialogActions>
              <Button onClick={handleCloseNotificationDetail}>Close</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Box>
  );
};

export default RightToolbar;
export { TOOLBAR_WIDTH };
