import React, { useState } from 'react';
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
} from '@mui/material';
import TerminalIcon from '@mui/icons-material/Terminal';
import BugReportIcon from '@mui/icons-material/BugReport';
import NotificationsIcon from '@mui/icons-material/Notifications';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import ScienceIcon from '@mui/icons-material/Science';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import LogoutIcon from '@mui/icons-material/Logout';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import SettingsIcon from '@mui/icons-material/Settings';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import InfoIcon from '@mui/icons-material/Info';
import DeveloperModeIcon from '@mui/icons-material/DeveloperMode';
import { useUIStore, Notification } from '@/store/uiStore';
import { useLogStore } from '@/store/logStore';

const TOOLBAR_WIDTH = 52;

interface RightToolbarProps {
  visible?: boolean;
}

/**
 * Right toolbar with quick actions and status indicators
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
  } = useUIStore();

  const { togglePanel: toggleLogPanel, isOpen: logPanelOpen } = useLogStore();

  // Menu states
  const [notificationsAnchor, setNotificationsAnchor] = useState<null | HTMLElement>(null);
  const [profileAnchor, setProfileAnchor] = useState<null | HTMLElement>(null);
  const [debugAnchor, setDebugAnchor] = useState<null | HTMLElement>(null);

  // Notification detail dialog state
  const [selectedNotification, setSelectedNotification] = useState<Notification | null>(null);

  const handleOpenDocs = async (): Promise<void> => {
    if (window.electronAPI) {
      await window.electronAPI.openExternal('https://docs.stingray.science/');
    }
  };

  const handleOpenStingray = async (): Promise<void> => {
    if (window.electronAPI) {
      await window.electronAPI.openExternal('https://github.com/StingraySoftware/stingray');
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

  if (!visible) {
    return null;
  }

  return (
    <Box
      sx={{
        width: TOOLBAR_WIDTH,
        height: 'calc(100vh - 64px - 40px)', // Header height - Footer height
        backgroundColor: 'background.paper',
        borderLeft: '1px solid',
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        py: 1,
        gap: 0.5,
        position: 'fixed',
        top: 64, // Header height
        right: 0,
        zIndex: 1100,
        overflowY: 'auto',
        overflowX: 'hidden',
      }}
    >
      {/* Processing indicator */}
      <Tooltip
        title={isProcessing ? processingMessage || 'Processing...' : 'System idle'}
        placement="left"
      >
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
              <CircularProgress
                size={20}
                variant="determinate"
                value={processingProgress}
              />
            ) : (
              <CircularProgress size={20} />
            )
          ) : (
            <HourglassEmptyIcon fontSize="small" />
          )}
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

      {/* Science / Stingray */}
      <Tooltip title="Stingray GitHub" placement="left">
        <IconButton onClick={handleOpenStingray} size="small">
          <ScienceIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Documentation */}
      <Tooltip title="Documentation" placement="left">
        <IconButton onClick={handleOpenDocs} size="small">
          <HelpOutlineIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Divider sx={{ width: '80%', my: 0.5 }} />

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

      {/* Profile */}
      <Tooltip title="Profile & Preferences" placement="left">
        <IconButton
          onClick={(e) => setProfileAnchor(e.currentTarget)}
          size="small"
        >
          <AccountCircleIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Quit / Close */}
      <Tooltip title="Quit application" placement="left">
        <IconButton onClick={handleQuitApp} size="small" color="error">
          <LogoutIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      {/* Notifications Menu */}
      <Menu
        anchorEl={notificationsAnchor}
        open={Boolean(notificationsAnchor)}
        onClose={() => setNotificationsAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        PaperProps={{
          sx: { width: 320, maxHeight: 400 },
        }}
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
      </Menu>

      {/* Profile Menu */}
      <Menu
        anchorEl={profileAnchor}
        open={Boolean(profileAnchor)}
        onClose={() => setProfileAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Box sx={{ px: 2, py: 1 }}>
          <Typography variant="subtitle2">Stingray Explorer</Typography>
          <Typography variant="caption" color="text.secondary">Desktop Application</Typography>
        </Box>
        <Divider />
        <MenuItem onClick={() => setProfileAnchor(null)}>
          <ListItemIcon>
            <SettingsIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Preferences</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { handleQuitApp(); setProfileAnchor(null); }}>
          <ListItemIcon>
            <LogoutIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText>Quit</ListItemText>
        </MenuItem>
      </Menu>

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
