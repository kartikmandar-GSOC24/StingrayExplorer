/**
 * Job Status Panel for the sidebar.
 *
 * Displays active and recently completed background jobs with
 * real-time progress updates. Persists across page navigation.
 */

import React, { useState, useContext } from 'react';
import {
  Box,
  Typography,
  IconButton,
  Collapse,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  Badge,
  Tooltip,
  Divider,
  Button,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import CancelIcon from '@mui/icons-material/Cancel';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import SyncIcon from '@mui/icons-material/Sync';
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';
import CloseIcon from '@mui/icons-material/Close';
import WifiIcon from '@mui/icons-material/Wifi';
import WifiOffIcon from '@mui/icons-material/WifiOff';
import { useJobStore } from '@/store/jobStore';
import { jobApi } from '@/api/jobApi';
import { ThemeContext } from '@/App';
import type { Job, JobStatus } from '@/types/job';

interface JobStatusPanelProps {
  /** Whether the sidebar is expanded */
  sidebarOpen: boolean;
}

/**
 * Get icon for job status.
 */
const getStatusIcon = (status: JobStatus): React.ReactNode => {
  switch (status) {
    case 'pending':
      return <HourglassEmptyIcon fontSize="small" color="action" />;
    case 'running':
      return <SyncIcon fontSize="small" color="primary" sx={{ animation: 'spin 1s linear infinite' }} />;
    case 'completed':
      return <CheckCircleIcon fontSize="small" color="success" />;
    case 'failed':
      return <ErrorIcon fontSize="small" color="error" />;
    case 'cancelled':
      return <CancelIcon fontSize="small" color="disabled" />;
    default:
      return null;
  }
};

/**
 * Format relative time (e.g., "2m ago").
 */
const formatRelativeTime = (isoString: string): string => {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
};

/**
 * Single job item component.
 */
const JobItem: React.FC<{ job: Job; onCancel: (id: string) => void }> = ({ job, onCancel }) => {
  const isActive = job.status === 'pending' || job.status === 'running';

  return (
    <ListItem
      sx={{
        py: 1,
        px: 1.5,
        flexDirection: 'column',
        alignItems: 'stretch',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', width: '100%' }}>
        {getStatusIcon(job.status)}
        <ListItemText
          primary={job.display_name}
          secondary={job.progress_message}
          primaryTypographyProps={{
            variant: 'body2',
            noWrap: true,
            sx: { ml: 1, maxWidth: '140px' },
          }}
          secondaryTypographyProps={{
            variant: 'caption',
            noWrap: true,
            sx: { ml: 1 },
          }}
        />
        {isActive && job.status === 'pending' && (
          <ListItemSecondaryAction>
            <Tooltip title="Cancel job">
              <IconButton size="small" onClick={() => onCancel(job.id)}>
                <CloseIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </ListItemSecondaryAction>
        )}
      </Box>

      {job.status === 'running' && job.total_items > 1 && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, ml: 3 }}>
          {job.completed_items}/{job.total_items} files
        </Typography>
      )}

      {!isActive && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, ml: 3 }}>
          {formatRelativeTime(job.completed_at || job.created_at)}
        </Typography>
      )}
    </ListItem>
  );
};

/**
 * Job Status Panel component.
 */
const JobStatusPanel: React.FC<JobStatusPanelProps> = ({ sidebarOpen }) => {
  const { darkMode } = useContext(ThemeContext);
  const [expanded, setExpanded] = useState(true);
  const [showCompleted, setShowCompleted] = useState(false);

  const {
    isConnected,
    getActiveJobs,
    getCompletedJobs,
    getActiveJobCount,
    clearCompletedJobs,
  } = useJobStore();

  const activeJobs = getActiveJobs();
  const completedJobs = getCompletedJobs();
  const activeCount = getActiveJobCount();

  const handleCancel = async (jobId: string): Promise<void> => {
    try {
      await jobApi.cancelJob(jobId);
    } catch (error) {
      console.error('Failed to cancel job:', error);
    }
  };

  const handleClearCompleted = (): void => {
    clearCompletedJobs();
    // Also clear on backend
    jobApi.clearCompletedJobs().catch(console.error);
  };

  // Don't render if sidebar is collapsed
  if (!sidebarOpen) {
    return null;
  }

  const hasJobs = activeJobs.length > 0 || completedJobs.length > 0;

  return (
    <Box
      sx={{
        borderTop: '1px solid',
        borderColor: 'divider',
        backgroundColor: darkMode ? 'rgba(0, 212, 170, 0.02)' : 'rgba(13, 155, 122, 0.02)',
        position: 'relative',
        '&::before': {
          content: '""',
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: '1px',
          background: darkMode
            ? 'linear-gradient(to right, rgba(0, 212, 170, 0.2), transparent)'
            : 'linear-gradient(to right, rgba(13, 155, 122, 0.2), transparent)',
        },
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1,
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Badge badgeContent={activeCount} color="primary" max={99}>
            <Typography variant="subtitle2" sx={{ fontFamily: '"JetBrains Mono", monospace', fontWeight: 600, fontSize: '0.75rem' }}>
              Jobs
            </Typography>
          </Badge>
          <Tooltip title={isConnected ? 'Connected' : 'Disconnected'}>
            {isConnected ? (
              <WifiIcon fontSize="small" color="success" sx={{ fontSize: 14, filter: darkMode ? 'drop-shadow(0 0 4px rgba(34, 197, 94, 0.4))' : 'none' }} />
            ) : (
              <WifiOffIcon fontSize="small" color="error" sx={{ fontSize: 14 }} />
            )}
          </Tooltip>
        </Box>
        <IconButton size="small">
          {expanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
      </Box>

      {/* Content */}
      <Collapse in={expanded}>
        <Box sx={{ maxHeight: 300, overflow: 'auto' }}>
          {/* Active Jobs */}
          {activeJobs.length > 0 && (
            <List dense disablePadding>
              {activeJobs.map((job) => (
                <JobItem key={job.id} job={job} onCancel={handleCancel} />
              ))}
            </List>
          )}

          {/* Completed Jobs Toggle */}
          {completedJobs.length > 0 && (
            <>
              <Divider />
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  px: 1.5,
                  py: 0.5,
                }}
              >
                <Button
                  size="small"
                  onClick={() => setShowCompleted(!showCompleted)}
                  sx={{ textTransform: 'none', fontSize: '0.75rem' }}
                >
                  {showCompleted ? 'Hide' : 'Show'} completed ({completedJobs.length})
                </Button>
                {showCompleted && (
                  <Tooltip title="Clear completed jobs">
                    <IconButton size="small" onClick={handleClearCompleted}>
                      <DeleteSweepIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                )}
              </Box>

              <Collapse in={showCompleted}>
                <List dense disablePadding>
                  {completedJobs.slice(0, 10).map((job) => (
                    <JobItem key={job.id} job={job} onCancel={handleCancel} />
                  ))}
                  {completedJobs.length > 10 && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block', textAlign: 'center', py: 1 }}
                    >
                      +{completedJobs.length - 10} more
                    </Typography>
                  )}
                </List>
              </Collapse>
            </>
          )}

          {/* Empty state - no jobs at all */}
          {!hasJobs && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', textAlign: 'center', py: 2 }}
            >
              No jobs running or completed
            </Typography>
          )}

          {/* Empty state for active (when there are completed jobs) */}
          {activeJobs.length === 0 && completedJobs.length > 0 && !showCompleted && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', textAlign: 'center', py: 2 }}
            >
              No active jobs
            </Typography>
          )}
        </Box>
      </Collapse>

    </Box>
  );
};

export default JobStatusPanel;
