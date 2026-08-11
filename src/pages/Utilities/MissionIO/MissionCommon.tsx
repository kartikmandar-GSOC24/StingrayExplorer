import React from 'react';
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import type { MissionMapping, MissionSourceField } from '@/api/missionIoApi';
import { UtilityWarnings } from '@/components/utilities/UtilityResult';

const MAPPING_ROWS: Array<[keyof MissionMapping, string]> = [
  ['event_hdu', 'Event HDU'],
  ['gti_hdu', 'GTI HDU'],
  ['time_column', 'Time column'],
  ['energy_or_channel_column', 'Energy / channel column'],
  ['detector_column', 'Detector column'],
  ['instrument_keyword', 'Instrument keyword'],
  ['mode_keyword', 'Mode keyword'],
];

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not defined';
  if (Array.isArray(value)) return value.map(displayValue).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function optionalText(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

export function mergeWarnings(...groups: Array<string[] | undefined>): string[] {
  return [...new Set(groups.flatMap((group) => group ?? []))];
}

export const MappingTable: React.FC<{ mapping: MissionMapping; title?: string }> = ({
  mapping,
  title = 'Runtime FITS mapping',
}) => (
  <TableContainer component={Paper} variant="outlined">
    <Table size="small" aria-label={title}>
      <TableHead>
        <TableRow>
          <TableCell colSpan={2}>{title}</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {MAPPING_ROWS.map(([key, label]) => (
          <TableRow key={key}>
            <TableCell component="th" scope="row">
              {label}
            </TableCell>
            <TableCell sx={{ fontFamily: '"IBM Plex Mono", monospace' }}>
              {displayValue(mapping[key])}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </TableContainer>
);

const SOURCE_LABELS: Record<MissionSourceField['source_type'], string> = {
  event_list_attribute: 'EventList attribute',
  fits_header: 'FITS header',
  override: 'User override',
  missing: 'Missing',
};

const MissionFieldCard: React.FC<{
  label: string;
  field: MissionSourceField;
}> = ({ label, field }) => (
  <Card variant="outlined" sx={{ height: '100%' }}>
    <CardContent>
      <Stack spacing={1}>
        <Typography variant="overline" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h6">{field.value ?? 'Not identified'}</Typography>
        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
          <Chip
            size="small"
            color={field.source_type === 'missing' ? 'default' : field.override ? 'warning' : 'info'}
            label={SOURCE_LABELS[field.source_type]}
          />
          {field.inferred ? <Chip size="small" label="Inferred" /> : null}
          {field.override ? <Chip size="small" color="warning" label="Override" /> : null}
          {label === 'Mission' && field.database_supported !== undefined ? (
            <Chip
              size="small"
              color={field.database_supported ? 'success' : 'default'}
              label={field.database_supported ? 'Runtime mapping found' : 'Not in runtime database'}
            />
          ) : null}
        </Stack>
        <Typography variant="caption" color="text.secondary">
          Source: {field.source ?? 'none'}
        </Typography>
        {field.raw_value && field.raw_value !== field.value ? (
          <Typography variant="caption" color="text.secondary">
            Raw value: {field.raw_value}
          </Typography>
        ) : null}
      </Stack>
    </CardContent>
  </Card>
);

export const MissionFieldCards: React.FC<{
  mission: MissionSourceField;
  instrument: MissionSourceField;
  mode: MissionSourceField;
}> = ({ mission, instrument, mode }) => (
  <Grid container spacing={1.5}>
    {[
      ['Mission', mission],
      ['Instrument', instrument],
      ['Observing mode', mode],
    ].map(([label, field]) => (
      <Grid item xs={12} md={4} key={label as string}>
        <MissionFieldCard label={label as string} field={field as MissionSourceField} />
      </Grid>
    ))}
  </Grid>
);

export interface OverrideValues {
  mission: string;
  instrument: string;
  mode: string;
}

const OVERRIDE_LIMITS = {
  mission: 128,
  instrument: 128,
  mode: 256,
} as const;

export type OverrideErrors = Record<keyof OverrideValues, string | null>;

export function overrideErrors(values: OverrideValues): OverrideErrors {
  return {
    mission:
      values.mission.length > OVERRIDE_LIMITS.mission
        ? `Mission override must be at most ${OVERRIDE_LIMITS.mission} characters`
        : null,
    instrument:
      values.instrument.length > OVERRIDE_LIMITS.instrument
        ? `Instrument override must be at most ${OVERRIDE_LIMITS.instrument} characters`
        : null,
    mode:
      values.mode.length > OVERRIDE_LIMITS.mode
        ? `Mode override must be at most ${OVERRIDE_LIMITS.mode} characters`
        : null,
  };
}

export function hasOverrideErrors(values: OverrideValues): boolean {
  return Object.values(overrideErrors(values)).some((error) => error !== null);
}

export const OptionalOverrides: React.FC<{
  values: OverrideValues;
  onChange: (values: OverrideValues) => void;
  disabled?: boolean;
  missionRequired?: boolean;
}> = ({ values, onChange, disabled = false, missionRequired = false }) => {
  const errors = overrideErrors(values);
  return (
    <Stack spacing={1.5}>
    <Alert severity={missionRequired ? 'info' : 'warning'}>
      Overrides are accepted only when source metadata are absent. They never replace a mission,
      instrument, or mode already present in an EventList or FITS header.
    </Alert>
    <Grid container spacing={1.5}>
      <Grid item xs={12} md={4}>
        <TextField
          fullWidth
          size="small"
          label={missionRequired ? 'Mission override (required)' : 'Mission override (if missing)'}
          value={values.mission}
          onChange={(event) => onChange({ ...values, mission: event.target.value })}
          disabled={disabled}
          required={missionRequired}
          error={errors.mission !== null}
          helperText={errors.mission}
          inputProps={{ maxLength: OVERRIDE_LIMITS.mission }}
        />
      </Grid>
      <Grid item xs={12} md={4}>
        <TextField
          fullWidth
          size="small"
          label="Instrument override (if missing)"
          value={values.instrument}
          onChange={(event) => onChange({ ...values, instrument: event.target.value })}
          disabled={disabled}
          error={errors.instrument !== null}
          helperText={errors.instrument}
          inputProps={{ maxLength: OVERRIDE_LIMITS.instrument }}
        />
      </Grid>
      <Grid item xs={12} md={4}>
        <TextField
          fullWidth
          size="small"
          label="Mode override (if missing)"
          value={values.mode}
          onChange={(event) => onChange({ ...values, mode: event.target.value })}
          disabled={disabled}
          error={errors.mode !== null}
          helperText={errors.mode}
          inputProps={{ maxLength: OVERRIDE_LIMITS.mode }}
        />
      </Grid>
    </Grid>
    </Stack>
  );
};

export const ResultFeedback: React.FC<{
  error: string | null;
  warnings?: string[];
}> = ({ error, warnings }) => (
  <Stack spacing={1.5}>
    {error ? <Alert severity="error">{error}</Alert> : null}
    <UtilityWarnings warnings={warnings} />
  </Stack>
);

export const ResultSection: React.FC<{
  title: string;
  children: React.ReactNode;
}> = ({ title, children }) => (
  <Box component="section" aria-label={title}>
    <Stack spacing={1.5}>
      <Typography variant="h6">{title}</Typography>
      {children}
    </Stack>
  </Box>
);
