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
import type { EventListSummary } from '@/api/dataApi';

interface EventListSelectorProps {
  label: string;
  value: string;
  onChange: (name: string) => void;
  requiredCapability?: 'pi' | 'energy';
  disabled?: boolean;
}

function supportsRequiredCapability(
  eventList: EventListSummary,
  requiredCapability: EventListSelectorProps['requiredCapability']
): boolean {
  if (requiredCapability === 'pi') return eventList.has_pi === true;
  if (requiredCapability === 'energy') return eventList.has_energy === true;
  return true;
}

/** Dropdown of event lists currently loaded in the backend. */
const EventListSelector: React.FC<EventListSelectorProps> = ({
  label,
  value,
  onChange,
  requiredCapability,
  disabled = false,
}) => {
  const { data, isLoading, isError, error, refetch, isFetching } = useEventLists();
  const labelId = `event-list-selector-${React.useId()}`;
  const capabilityLabel = requiredCapability === 'pi' ? 'PI/channel' : 'energy';

  // Auto-clear a selection that no longer exists in the list (deleted
  // elsewhere or backend restart) so consumers never submit stale names.
  React.useEffect(() => {
    if (
      !isLoading &&
      !isFetching &&
      value !== '' &&
      data !== undefined &&
      !data.some(
        (ev) => ev.name === value && supportsRequiredCapability(ev, requiredCapability)
      )
    ) {
      onChange('');
    }
  }, [data, isLoading, isFetching, value, onChange, requiredCapability]);

  const refreshButton = (
    <Tooltip title="Refresh list">
      <span>
        <IconButton
          size="small"
          aria-label="Refresh event lists"
          onClick={() => refetch()}
          disabled={disabled || isFetching}
        >
          {isFetching ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
        </IconButton>
      </span>
    </Tooltip>
  );

  // Only take over the UI with an error when there is no usable (stale) data;
  // a failed background refetch keeps the populated dropdown rendered.
  if (isError && data === undefined) {
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

  if (
    !isLoading &&
    requiredCapability !== undefined &&
    data !== undefined &&
    !data.some((eventList) => supportsRequiredCapability(eventList, requiredCapability))
  ) {
    return (
      <Alert severity="info" action={refreshButton}>
        No EventLists with {capabilityLabel} data are loaded.{' '}
        <Link component={RouterLink} to="/data-ingestion">
          Load compatible data
        </Link>{' '}
        first.
      </Alert>
    );
  }

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <FormControl fullWidth size="small" disabled={disabled || isLoading}>
        <InputLabel id={labelId}>{label}</InputLabel>
        <Select
          labelId={labelId}
          value={value}
          label={label}
          onChange={(e) => onChange(e.target.value)}
        >
          {(data ?? []).map((ev) => (
            <MenuItem
              key={ev.name}
              value={ev.name}
              disabled={!supportsRequiredCapability(ev, requiredCapability)}
            >
              {ev.name} ({ev.n_events.toLocaleString()} events)
              {!supportsRequiredCapability(ev, requiredCapability)
                ? ` — no ${capabilityLabel} data`
                : ''}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      {refreshButton}
    </Box>
  );
};

export default EventListSelector;
