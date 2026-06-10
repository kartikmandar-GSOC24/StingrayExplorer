import React from 'react';
import {
  Alert,
  Box,
  CircularProgress,
  FormControl,
  IconButton,
  InputLabel,
  Link,
  MenuItem,
  Select,
  Tooltip,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { Link as RouterLink } from 'react-router-dom';
import { useEventLists } from '@/hooks/useEventLists';

interface EventListSelectorProps {
  label: string;
  value: string;
  onChange: (name: string) => void;
}

/** Dropdown of event lists currently loaded in the backend. */
const EventListSelector: React.FC<EventListSelectorProps> = ({ label, value, onChange }) => {
  const { data, isLoading, isError, error, refetch, isFetching } = useEventLists();

  const refreshButton = (
    <Tooltip title="Refresh list">
      <span>
        <IconButton size="small" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
        </IconButton>
      </span>
    </Tooltip>
  );

  if (isError) {
    return (
      <Alert severity="error" action={refreshButton}>
        Failed to load event lists: {error instanceof Error ? error.message : 'unknown error'}
      </Alert>
    );
  }

  if (!isLoading && (data?.length ?? 0) === 0) {
    return (
      <Alert severity="info" action={refreshButton}>
        No event lists loaded.{' '}
        <Link component={RouterLink} to="/data-ingestion">
          Load data
        </Link>{' '}
        first.
      </Alert>
    );
  }

  const labelId = `event-list-selector-${label.replace(/\s+/g, '-').toLowerCase()}`;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <FormControl fullWidth size="small" disabled={isLoading}>
        <InputLabel id={labelId}>{label}</InputLabel>
        <Select
          labelId={labelId}
          value={value}
          label={label}
          onChange={(e) => onChange(e.target.value)}
        >
          {(data ?? []).map((ev) => (
            <MenuItem key={ev.name} value={ev.name}>
              {ev.name} ({ev.n_events.toLocaleString()} events)
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      {refreshButton}
    </Box>
  );
};

export default EventListSelector;
