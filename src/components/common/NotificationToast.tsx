/**
 * NotificationToast - Auto-popup toast notifications
 *
 * Displays a Snackbar toast whenever a new notification is added to the store.
 * Notifications slide in from the right side and auto-dismiss after a few seconds.
 */

import React, { useEffect, useState } from 'react';
import {
  Snackbar,
  Alert,
  AlertTitle,
  IconButton,
  Typography,
  Slide,
  SlideProps,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useUIStore, Notification } from '@/store/uiStore';

// Slide transition from right
function SlideTransition(props: SlideProps) {
  return <Slide {...props} direction="left" />;
}

// Auto-hide duration based on notification type (ms)
const AUTO_HIDE_DURATION: Record<Notification['type'], number> = {
  info: 4000,
  success: 3000,
  warning: 5000,
  error: 6000,
};

const NotificationToast: React.FC = () => {
  const { notifications, markNotificationRead } = useUIStore();
  const [open, setOpen] = useState(false);
  const [currentNotification, setCurrentNotification] = useState<Notification | null>(null);
  const [lastNotificationId, setLastNotificationId] = useState<string | null>(null);

  // Watch for new notifications
  useEffect(() => {
    if (notifications.length > 0) {
      const latestNotification = notifications[0];

      // Only show toast for new, unread notifications
      if (latestNotification.id !== lastNotificationId && !latestNotification.read) {
        setCurrentNotification(latestNotification);
        setLastNotificationId(latestNotification.id);
        setOpen(true);
      }
    }
  }, [notifications, lastNotificationId]);

  const handleClose = (_event?: React.SyntheticEvent | Event, reason?: string): void => {
    // Don't close on clickaway - only on explicit close or timeout
    if (reason === 'clickaway') {
      return;
    }
    setOpen(false);
  };

  const handleExited = (): void => {
    // Mark as read when the toast closes
    if (currentNotification) {
      markNotificationRead(currentNotification.id);
    }
  };

  if (!currentNotification) {
    return null;
  }

  return (
    <Snackbar
      open={open}
      autoHideDuration={AUTO_HIDE_DURATION[currentNotification.type]}
      onClose={handleClose}
      TransitionComponent={SlideTransition}
      TransitionProps={{
        onExited: handleExited,
      }}
      anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      sx={{
        mt: 8, // Below header
        mr: 7, // Account for right toolbar
      }}
    >
      <Alert
        severity={currentNotification.type}
        variant="filled"
        onClose={handleClose}
        sx={{
          minWidth: 300,
          maxWidth: 450,
          boxShadow: 6,
          '& .MuiAlert-message': {
            width: '100%',
          },
        }}
        action={
          <IconButton
            size="small"
            aria-label="close"
            color="inherit"
            onClick={handleClose}
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        }
      >
        <AlertTitle sx={{ fontWeight: 600 }}>
          {currentNotification.title}
        </AlertTitle>
        <Typography
          variant="body2"
          sx={{
            opacity: 0.9,
            // Limit message length for toast
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {currentNotification.message}
        </Typography>
      </Alert>
    </Snackbar>
  );
};

export default NotificationToast;
