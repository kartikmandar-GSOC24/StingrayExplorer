import React, { useId } from 'react';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import SaveOutlinedIcon from '@mui/icons-material/SaveOutlined';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  FormHelperText,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import type { Data } from 'plotly.js';
import PlotlyChart from '@/components/plots/PlotlyChart';
import {
  NumericResultTable,
  UtilityWarnings,
} from '@/components/utilities/UtilityResult';
import type {
  GtiIntervalPayload,
  GtiSetOperation,
  GtiTimeReference,
} from '@/api/gtiApi';
import { parseGtiRows } from '@/utils/utilityInputs';
import {
  parseNumber as parseFiniteDecimal,
  parsePositiveNumber as parsePositiveFiniteDecimal,
} from '@/utils/numbers';

export interface ParsedGtis {
  rows: [number, number][] | null;
  error: string | null;
}

export interface InspectedGtiRows {
  rows: string;
  sourceName: string;
}

export const TIME_REFERENCE_LABELS: Record<GtiTimeReference, string> = {
  absolute_mission_time: 'Absolute mission time',
  relative_seconds: 'Relative seconds',
};

export const SET_OPERATION_LABELS: Record<GtiSetOperation, string> = {
  intersection: 'Intersection — shared good time',
  union: 'Union — coalesce overlap/touching',
  append: 'Append — separate sets only',
};

export function parseStrictGtis(text: string, label = 'GTIs'): ParsedGtis {
  const parsed = parseGtiRows(text);
  if (!parsed.value) {
    return { rows: null, error: `${label}: ${parsed.error ?? 'invalid rows'}` };
  }
  for (let index = 0; index < parsed.value.length; index += 1) {
    const [start, stop] = parsed.value[index];
    if (stop <= start) {
      return {
        rows: null,
        error: `${label} row ${index + 1}: stop must be greater than start`,
      };
    }
    if (index > 0) {
      const [previousStart, previousStop] = parsed.value[index - 1];
      if (start < previousStart) {
        return {
          rows: null,
          error: `${label} row ${index + 1}: starts before row ${index}; preserve time order`,
        };
      }
      if (start < previousStop) {
        return {
          rows: null,
          error: `${label} row ${index + 1}: overlaps row ${index}`,
        };
      }
    }
  }
  return { rows: parsed.value, error: null };
}

export function finiteNumber(text: string): number | null {
  return parseFiniteDecimal(text);
}

export function positiveNumber(text: string): number | null {
  return parsePositiveFiniteDecimal(text);
}

export function rowsToText(rows: Array<{ start: number; stop: number }>): string {
  return rows.map((row) => `${row.start}, ${row.stop}`).join('\n');
}

function appendGtiRow(text: string): string {
  if (text.trim() === '') return '0, 1';
  const parsed = parseGtiRows(text);
  if (!parsed.value) return `${text.trimEnd()}\n0, 1`;
  const previousStop = parsed.value[parsed.value.length - 1][1];
  const start = previousStop + 1;
  return `${text.trimEnd()}\n${start}, ${start + 1}`;
}

function removeLastGtiRow(text: string): string {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== '');
  lines.pop();
  return lines.join('\n');
}

export function formatMetric(value: number | null, suffix = ''): string {
  if (value === null) return 'Unavailable';
  const formatted = value.toLocaleString(undefined, {
    maximumSignificantDigits: 10,
    useGrouping: false,
  });
  return `${formatted}${suffix}`;
}

export const TabPanel: React.FC<{
  active: number;
  index: number;
  children: React.ReactNode;
}> = ({ active, index, children }) => (
  <Box
    role="tabpanel"
    id={`gti-tabpanel-${index}`}
    aria-labelledby={`gti-tab-${index}`}
    hidden={active !== index}
    sx={{ pt: 3 }}
  >
    {children}
  </Box>
);

export const RunButton: React.FC<{
  label: string;
  running: boolean;
  disabled: boolean;
  onClick: () => void;
  save?: boolean;
}> = ({ label, running, disabled, onClick, save = false }) => (
  <Button
    variant="contained"
    startIcon={
      running ? (
        <CircularProgress size={16} color="inherit" />
      ) : save ? (
        <SaveOutlinedIcon />
      ) : (
        <PlayArrowIcon />
      )
    }
    disabled={disabled || running}
    onClick={onClick}
  >
    {label}
  </Button>
);

export const GtiRowsField: React.FC<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
  editableRows?: boolean;
  disabled?: boolean;
}> = ({ label, value, onChange, error, editableRows = false, disabled = false }) => (
  <Stack spacing={1}>
    <TextField
      label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      multiline
      minRows={4}
      maxRows={12}
      fullWidth
      disabled={disabled}
      error={value.trim() !== '' && error !== null}
      helperText={
        value.trim() !== '' && error
          ? error
          : 'One start, stop pair per line. Rows remain in the order entered.'
      }
      inputProps={{ spellCheck: false }}
    />
    {editableRows ? (
      <Stack direction="row" spacing={1}>
        <Button
          size="small"
          startIcon={<AddIcon />}
          onClick={() => onChange(appendGtiRow(value))}
          disabled={disabled}
        >
          Add row
        </Button>
        <Button
          size="small"
          startIcon={<DeleteOutlineIcon />}
          onClick={() => onChange(removeLastGtiRow(value))}
          disabled={disabled || value.trim() === ''}
        >
          Remove last row
        </Button>
      </Stack>
    ) : null}
  </Stack>
);

export const MetricCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
    <Typography variant="caption" color="text.secondary">
      {label}
    </Typography>
    <Typography variant="h6" sx={{ fontFamily: '"IBM Plex Mono", monospace' }}>
      {value}
    </Typography>
  </Paper>
);

export function intervalTrace(payload: GtiIntervalPayload, name: string): Data[] {
  // Use the backend-sanitized duration values instead of subtracting extreme
  // finite endpoints again in JavaScript, where the difference can overflow.
  const lengths = payload.plot.interval_indices.map(
    (intervalIndex) => payload.lengths_s[intervalIndex - 1] ?? null
  );
  return [
    {
      type: 'bar',
      orientation: 'h',
      x: lengths,
      base: payload.plot.starts,
      y: payload.plot.interval_indices,
      name,
      marker: { color: '#00a98f' },
      hovertemplate: 'start=%{base:.12g}s<br>length=%{x:.12g}s<extra></extra>',
    } as Data,
  ];
}

export const IntervalResult: React.FC<{
  title: string;
  payload: GtiIntervalPayload;
  timeReference?: GtiTimeReference;
}> = ({ title, payload, timeReference }) => (
  <Stack spacing={2}>
    {timeReference ? (
      <Alert severity="info">
        Time reference: {TIME_REFERENCE_LABELS[timeReference]}. Values are reported in seconds and
        are not shifted or reinterpreted by the renderer.
      </Alert>
    ) : null}
    <Grid container spacing={1.5}>
      <Grid item xs={6} md={3}>
        <MetricCard label="Intervals" value={payload.interval_count.toLocaleString()} />
      </Grid>
      <Grid item xs={6} md={3}>
        <MetricCard label="Total exposure" value={formatMetric(payload.total_exposure_s, ' s')} />
      </Grid>
      <Grid item xs={6} md={3}>
        <MetricCard label="Overall span" value={formatMetric(payload.overall_time_span_s, ' s')} />
      </Grid>
      <Grid item xs={6} md={3}>
        <MetricCard
          label="Duty cycle"
          value={
            payload.duty_cycle === null
              ? 'Unavailable'
              : formatMetric(payload.duty_cycle * 100, '%')
          }
        />
      </Grid>
    </Grid>
    {payload.intervals.length === 0 ? (
      <Alert severity="info">No positive-duration intervals are present in this result.</Alert>
    ) : (
      <>
        <NumericResultTable
          title={`${title} — exact intervals`}
          columns={[
            { key: 'index', label: 'Interval' },
            { key: 'start', label: 'Start', unit: 's' },
            { key: 'stop', label: 'Stop', unit: 's' },
            { key: 'length_s', label: 'Length', unit: 's' },
          ]}
          rows={payload.intervals.map((interval) => ({ ...interval }))}
        />
        <Paper variant="outlined" sx={{ p: 1 }}>
          <Typography variant="subtitle2" sx={{ px: 1, pt: 0.5 }}>
            {title} — bounded plot preview
          </Typography>
          {payload.plot.stride > 1 ? (
            <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>
              Showing every {payload.plot.stride.toLocaleString()}th interval from{' '}
              {payload.plot.source_points.toLocaleString()} source intervals. The table above remains exact.
            </Typography>
          ) : null}
          <PlotlyChart
            data={intervalTrace(payload, title)}
            height={320}
            layout={{
              xaxis: { title: { text: 'Mission/relative time (s)' } },
              yaxis: { title: { text: 'Interval index' }, autorange: 'reversed' },
              showlegend: false,
              bargap: 0.35,
            }}
          />
        </Paper>
      </>
    )}
  </Stack>
);

export const RunnerError: React.FC<{
  error: string | null;
  warnings?: string[];
}> = ({ error, warnings = [] }) =>
  error || warnings.length ? (
    <Stack spacing={1}>
      {error ? <Alert severity="error">{error}</Alert> : null}
      <UtilityWarnings warnings={warnings} />
    </Stack>
  ) : null;

export const TimeReferenceControl: React.FC<{
  value: GtiTimeReference;
  onChange: (value: GtiTimeReference) => void;
  disabled?: boolean;
}> = ({ value, onChange, disabled = false }) => {
  const labelId = `gti-time-reference-${useId()}`;
  return (
    <FormControl size="small" fullWidth disabled={disabled}>
      <InputLabel id={labelId}>Time reference</InputLabel>
      <Select
        labelId={labelId}
        label="Time reference"
        value={value}
        onChange={(event) => onChange(event.target.value as GtiTimeReference)}
      >
        {Object.entries(TIME_REFERENCE_LABELS).map(([key, label]) => (
          <MenuItem key={key} value={key}>
            {label}
          </MenuItem>
        ))}
      </Select>
      <FormHelperText>
        {value === 'absolute_mission_time'
          ? 'Seconds on the mission clock; interpret with MJDREF, not as UTC seconds.'
          : 'Seconds from a user-chosen origin; values are labelled, not shifted.'}
      </FormHelperText>
    </FormControl>
  );
};
