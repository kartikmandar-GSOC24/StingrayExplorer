import React, { useEffect, useRef, useState } from 'react';
import {
  Box,
  Collapse,
  IconButton,
  Typography,
  TextField,
  Chip,
  Tooltip,
  Paper,
  Stack,
  Divider,
  InputAdornment,
} from '@mui/material';
import {
  ExpandLess,
  ExpandMore,
  Delete,
  ContentCopy,
  Search,
  Terminal,
  Error as ErrorIcon,
  Warning as WarningIcon,
  Info as InfoIcon,
  BugReport as DebugIcon,
  Code as RawIcon,
  FormatListBulleted as FormattedIcon,
} from '@mui/icons-material';
import { useLogStore, selectFilteredLogs, LogEntry } from '@/store/logStore';
import { useBackendContext } from '@/App';
import { logStreamClient } from '@/api/logApi';

interface LogPanelProps {
  /** Left offset to avoid overlapping left sidebar */
  leftOffset?: number;
  /** Right offset to avoid overlapping right toolbar */
  rightOffset?: number;
}

/**
 * Format timestamp for display
 */
const formatTimestamp = (date: Date): string => {
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
};

/**
 * Get icon for log level
 */
const getLevelIcon = (level: LogEntry['level']): React.ReactNode => {
  switch (level) {
    case 'error':
      return <ErrorIcon fontSize="small" sx={{ color: 'error.main' }} />;
    case 'warn':
      return <WarningIcon fontSize="small" sx={{ color: 'warning.main' }} />;
    case 'info':
      return <InfoIcon fontSize="small" sx={{ color: 'info.main' }} />;
    case 'debug':
      return <DebugIcon fontSize="small" sx={{ color: 'text.secondary' }} />;
    default:
      return null;
  }
};

/**
 * Get color for log level
 */
const getLevelColor = (level: LogEntry['level']): string => {
  switch (level) {
    case 'error':
      return 'error.main';
    case 'warn':
      return 'warning.main';
    case 'info':
      return 'info.main';
    case 'debug':
      return 'text.secondary';
    default:
      return 'text.primary';
  }
};

/**
 * Get color for source
 */
const getSourceColor = (source: LogEntry['source']): 'primary' | 'secondary' | 'default' => {
  switch (source) {
    case 'python':
      return 'primary';
    case 'electron':
      return 'secondary';
    case 'frontend':
      return 'default';
    default:
      return 'default';
  }
};

/**
 * Log entry row component (formatted view)
 */
const LogRow: React.FC<{ log: LogEntry }> = ({ log }) => {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 1,
        py: 0.5,
        px: 1,
        fontFamily: 'monospace',
        fontSize: '0.8rem',
        '&:hover': {
          backgroundColor: 'action.hover',
        },
      }}
    >
      <Typography
        variant="caption"
        sx={{
          fontFamily: 'monospace',
          color: 'text.secondary',
          minWidth: '70px',
          flexShrink: 0,
        }}
      >
        {formatTimestamp(log.timestamp)}
      </Typography>
      <Box sx={{ flexShrink: 0, width: 20 }}>{getLevelIcon(log.level)}</Box>
      <Chip
        label={log.source}
        size="small"
        color={getSourceColor(log.source)}
        variant="outlined"
        sx={{
          height: 18,
          fontSize: '0.65rem',
          '& .MuiChip-label': { px: 0.5 },
          flexShrink: 0,
        }}
      />
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'monospace',
          color: getLevelColor(log.level),
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          flex: 1,
        }}
      >
        {log.message}
      </Typography>
    </Box>
  );
};

/**
 * Format log entry as raw terminal output
 */
const formatRawLog = (log: LogEntry): string => {
  const timestamp = formatTimestamp(log.timestamp);
  const level = log.level.toUpperCase().padEnd(5);
  const source = `[${log.source}]`.padEnd(10);
  return `${timestamp} ${level} ${source} ${log.message}`;
};

/**
 * Raw log view component - shows logs exactly like terminal output
 */
const RawLogView: React.FC<{ logs: LogEntry[] }> = ({ logs }) => {
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 1,
        fontFamily: 'monospace',
        fontSize: '0.8rem',
        lineHeight: 1.4,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        color: 'text.primary',
        backgroundColor: 'transparent',
      }}
    >
      {logs.map((log) => (
        <Box
          key={log.id}
          component="span"
          sx={{
            display: 'block',
            '&:hover': {
              backgroundColor: 'action.hover',
            },
          }}
        >
          {formatRawLog(log)}
        </Box>
      ))}
    </Box>
  );
};

/**
 * LogPanel component - displays logs in a collapsible panel
 */
const LogPanel: React.FC<LogPanelProps> = ({ leftOffset = 0, rightOffset = 0 }) => {
  const {
    isOpen,
    togglePanel,
    clearLogs,
    filter,
    toggleLevelFilter,
    toggleSourceFilter,
    setSearchFilter,
  } = useLogStore();

  const logs = useLogStore(selectFilteredLogs);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [rawView, setRawView] = useState(false);
  const { isReady: backendReady } = useBackendContext();

  // Listen for logs from Electron main process
  useEffect(() => {
    if (typeof window !== 'undefined' && window.electronAPI) {
      // Set up the log listener first
      const unsubscribe = window.electronAPI.onLog((log) => {
        useLogStore.getState().addLog(log);
      });

      // Signal that we're ready to receive logs (triggers flush of buffered logs)
      window.electronAPI.signalLogReady();

      return unsubscribe;
    }
  }, []);

  // Connect to Python backend log stream via SSE when backend is ready
  useEffect(() => {
    if (backendReady) {
      // Connect immediately - history replay ensures we don't miss startup logs
      logStreamClient.connect();

      return () => {
        logStreamClient.disconnect();
      };
    }
  }, [backendReady]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  // Handle scroll to detect if user scrolled up
  const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
    const element = e.currentTarget;
    const isAtBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 50;
    setAutoScroll(isAtBottom);
  };

  // Copy all visible logs to clipboard
  const handleCopyLogs = (): void => {
    const logText = logs
      .map((log) => `[${formatTimestamp(log.timestamp)}] [${log.level.toUpperCase()}] [${log.source}] ${log.message}`)
      .join('\n');
    navigator.clipboard.writeText(logText);
  };

  const levelFilters: LogEntry['level'][] = ['info', 'warn', 'error', 'debug'];
  const sourceFilters: LogEntry['source'][] = ['python', 'electron', 'frontend'];

  return (
    <Paper
      elevation={4}
      sx={{
        position: 'fixed',
        bottom: 0,
        left: leftOffset,
        right: rightOffset,
        zIndex: 1200,
        borderRadius: '12px 12px 0 0',
        overflow: 'hidden',
        borderTop: '1px solid',
        borderColor: 'divider',
        transition: 'left 225ms ease-in-out, right 225ms ease-in-out',
      }}
    >
      {/* Header */}
      <Box
        onClick={togglePanel}
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1,
          backgroundColor: 'background.paper',
          borderBottom: isOpen ? 1 : 0,
          borderColor: 'divider',
          cursor: 'pointer',
          '&:hover': {
            backgroundColor: 'action.hover',
          },
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1}>
          <Terminal fontSize="small" />
          <Typography variant="subtitle2">Console</Typography>
          <Chip
            label={logs.length}
            size="small"
            sx={{ height: 20, fontSize: '0.7rem' }}
          />
        </Stack>
        <IconButton size="small" onClick={(e) => { e.stopPropagation(); togglePanel(); }}>
          {isOpen ? <ExpandMore /> : <ExpandLess />}
        </IconButton>
      </Box>

      {/* Content */}
      <Collapse in={isOpen}>
        <Box sx={{ height: 300, display: 'flex', flexDirection: 'column' }}>
          {/* Toolbar */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 2,
              py: 1,
              backgroundColor: 'background.default',
              borderBottom: 1,
              borderColor: 'divider',
              flexWrap: 'wrap',
            }}
          >
            {/* Search */}
            <TextField
              size="small"
              placeholder="Filter logs..."
              value={filter.search}
              onChange={(e) => setSearchFilter(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Search fontSize="small" />
                  </InputAdornment>
                ),
                sx: { fontSize: '0.8rem', height: 32 },
              }}
              sx={{ width: 200 }}
            />

            <Divider orientation="vertical" flexItem />

            {/* Level filters */}
            <Stack direction="row" spacing={0.5}>
              {levelFilters.map((level) => (
                <Chip
                  key={level}
                  label={level}
                  size="small"
                  variant={filter.levels.has(level) ? 'filled' : 'outlined'}
                  onClick={() => toggleLevelFilter(level)}
                  sx={{
                    height: 24,
                    fontSize: '0.7rem',
                    textTransform: 'capitalize',
                  }}
                />
              ))}
            </Stack>

            <Divider orientation="vertical" flexItem />

            {/* Source filters */}
            <Stack direction="row" spacing={0.5}>
              {sourceFilters.map((source) => (
                <Chip
                  key={source}
                  label={source}
                  size="small"
                  color={getSourceColor(source)}
                  variant={filter.sources.has(source) ? 'filled' : 'outlined'}
                  onClick={() => toggleSourceFilter(source)}
                  sx={{
                    height: 24,
                    fontSize: '0.7rem',
                    textTransform: 'capitalize',
                  }}
                />
              ))}
            </Stack>

            <Box sx={{ flex: 1 }} />

            {/* Actions */}
            <Tooltip title={rawView ? 'Switch to formatted view' : 'Switch to raw view'}>
              <IconButton size="small" onClick={() => setRawView(!rawView)}>
                {rawView ? <FormattedIcon fontSize="small" /> : <RawIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
            <Tooltip title="Copy all logs">
              <IconButton size="small" onClick={handleCopyLogs}>
                <ContentCopy fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Clear logs">
              <IconButton size="small" onClick={clearLogs}>
                <Delete fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>

          {/* Log entries */}
          <Box
            onScroll={handleScroll}
            sx={{
              flex: 1,
              overflow: 'auto',
              backgroundColor: 'background.default',
              '&::-webkit-scrollbar': {
                width: 8,
              },
              '&::-webkit-scrollbar-track': {
                backgroundColor: 'background.paper',
              },
              '&::-webkit-scrollbar-thumb': {
                backgroundColor: 'action.disabled',
                borderRadius: 4,
              },
            }}
          >
            {logs.length === 0 ? (
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '100%',
                  color: 'text.secondary',
                }}
              >
                <Typography variant="body2">No logs to display</Typography>
              </Box>
            ) : rawView ? (
              <>
                <RawLogView logs={logs} />
                <div ref={logsEndRef} />
              </>
            ) : (
              <>
                {logs.map((log) => (
                  <LogRow key={log.id} log={log} />
                ))}
                <div ref={logsEndRef} />
              </>
            )}
          </Box>
        </Box>
      </Collapse>
    </Paper>
  );
};

export default LogPanel;
