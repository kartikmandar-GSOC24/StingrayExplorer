import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
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
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import {
  missionIoApi,
  type MissionCapabilitiesData,
  type MissionInfoData,
  type RoughConversionCapability,
} from '@/api/missionIoApi';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { ProvenancePanel, UtilityWarnings } from '@/components/utilities/UtilityResult';
import {
  MappingTable,
  mergeWarnings,
  ResultFeedback,
  ResultSection,
  displayValue,
  optionalText,
} from './MissionCommon';

export const CAPABILITIES_QUERY_KEY = ['missionIoCapabilities'] as const;

function capabilityColor(
  status: RoughConversionCapability['status']
): 'success' | 'warning' | 'default' {
  if (status === 'supported') return 'success';
  if (status === 'conditional') return 'warning';
  return 'default';
}

export async function loadCapabilities(): Promise<MissionCapabilitiesData> {
  const response = await missionIoApi.getCapabilities();
  if (!response.success || response.data === null) {
    throw new Error(response.error || response.message || 'Could not load mission capabilities');
  }
  return response.data;
}

const MissionDatabasePanel: React.FC = () => {
  const capabilities = useQuery({
    queryKey: CAPABILITIES_QUERY_KEY,
    queryFn: loadCapabilities,
    staleTime: 60_000,
  });
  const [mission, setMission] = React.useState('');
  const [instrument, setInstrument] = React.useState('');
  const [mode, setMode] = React.useState('');
  const { result, running, error, warnings, run } = useAnalysisRunner<MissionInfoData>(
    'Mission mapping lookup'
  );
  const instrumentError =
    instrument.length > 128 ? 'Instrument must be at most 128 characters' : null;
  const modeError = mode.length > 256 ? 'Mode must be at most 256 characters' : null;

  const inspect = (): void => {
    if (mission === '' || instrumentError || modeError) return;
    const params: { mission: string; instrument?: string; mode?: string } = { mission };
    const selectedInstrument = optionalText(instrument);
    const selectedMode = optionalText(mode);
    if (selectedInstrument) params.instrument = selectedInstrument;
    if (selectedMode) params.mode = selectedMode;
    void run(() => missionIoApi.getMissionInfo(params));
  };

  if (capabilities.isLoading) {
    return (
      <Stack alignItems="center" spacing={1.5} sx={{ py: 5 }}>
        <CircularProgress aria-label="Loading mission capabilities" />
        <Typography color="text.secondary">Reading the runtime mission database…</Typography>
      </Stack>
    );
  }

  if (capabilities.isError || !capabilities.data) {
    return (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={() => void capabilities.refetch()}>
            Retry
          </Button>
        }
      >
        {capabilities.error instanceof Error
          ? capabilities.error.message
          : 'Could not load the runtime mission database'}
      </Alert>
    );
  }

  const data = capabilities.data;
  return (
    <Stack spacing={2.5}>
      <Alert severity="info">
        {data.support_note} Precise PI calibration uses {data.precise_calibration.method} in{' '}
        {data.precise_calibration.location}.
      </Alert>
      <UtilityWarnings warnings={data.warnings} />
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
        <Chip label={`${data.mission_count} unique mission mappings`} />
        <Chip label={`${data.raw_database_entry_count} raw database entries`} />
        <Typography variant="caption" color="text.secondary">
          Source: {data.database_source}
        </Typography>
      </Stack>
      <ProvenancePanel provenance={data.provenance} />

      <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 520 }}>
        <Table size="small" stickyHeader aria-label="Runtime mission capability table">
          <TableHead>
            <TableRow>
              <TableCell>Mission</TableCell>
              <TableCell>Core FITS mapping</TableCell>
              <TableCell>Instruments / modes</TableCell>
              <TableCell>Rough PI → energy</TableCell>
              <TableCell>Specialized interpreter</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.missions.map((row) => (
              <TableRow key={row.mission} hover>
                <TableCell component="th" scope="row">
                  {row.mission}
                </TableCell>
                <TableCell>
                  <Typography variant="caption" display="block">
                    Event HDU: {displayValue(row.mapping.event_hdu)}
                  </Typography>
                  <Typography variant="caption" display="block">
                    Time: {displayValue(row.mapping.time_column)}
                  </Typography>
                  <Typography variant="caption" display="block">
                    Energy/channel: {displayValue(row.mapping.energy_or_channel_column)}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption" display="block">
                    Instruments: {displayValue(row.instruments)}
                  </Typography>
                  <Typography variant="caption" display="block">
                    Modes: {displayValue(row.modes)}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Stack spacing={0.5} alignItems="flex-start">
                    <Chip
                      size="small"
                      color={capabilityColor(row.rough_pi_to_energy.status)}
                      label={row.rough_pi_to_energy.status}
                    />
                    <Typography variant="caption">
                      {row.rough_pi_to_energy.message ?? 'No additional details'}
                    </Typography>
                    {row.rough_pi_to_energy.dependencies.length > 0 ? (
                      <Typography variant="caption" color="text.secondary">
                        Dependencies: {row.rough_pi_to_energy.dependencies.join(', ')}
                      </Typography>
                    ) : null}
                  </Stack>
                </TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    color={row.specialized_interpretation.supported ? 'success' : 'default'}
                    label={row.specialized_interpretation.supported ? 'Supported' : 'Not available'}
                  />
                  {row.specialized_interpretation.scope ? (
                    <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                      {row.specialized_interpretation.scope}
                    </Typography>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6">Inspect one runtime mapping</Typography>
            <Grid container spacing={1.5}>
              <Grid item xs={12} md={4}>
                <FormControl fullWidth size="small">
                  <InputLabel id="mission-info-name-label">Mission</InputLabel>
                  <Select
                    labelId="mission-info-name-label"
                    label="Mission"
                    value={mission}
                    onChange={(event) => setMission(event.target.value)}
                    disabled={running}
                  >
                    <MenuItem value="">Choose a mission</MenuItem>
                    {data.missions.map((row) => (
                      <MenuItem key={row.mission} value={row.mission}>
                        {row.mission}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} md={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Instrument (optional)"
                  value={instrument}
                  onChange={(event) => setInstrument(event.target.value)}
                  disabled={running}
                  error={instrumentError !== null}
                  helperText={instrumentError}
                  inputProps={{ maxLength: 128 }}
                />
              </Grid>
              <Grid item xs={12} md={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Mode (optional)"
                  value={mode}
                  onChange={(event) => setMode(event.target.value)}
                  disabled={running}
                  error={modeError !== null}
                  helperText={modeError}
                  inputProps={{ maxLength: 256 }}
                />
              </Grid>
            </Grid>
            <Button
              variant="contained"
              startIcon={
                running ? <CircularProgress size={16} color="inherit" /> : <InfoOutlinedIcon />
              }
              disabled={mission === '' || instrumentError !== null || modeError !== null || running}
              onClick={inspect}
            >
              {running ? 'Inspecting…' : 'Inspect mission mapping'}
            </Button>
          </Stack>
        </CardContent>
      </Card>

      <ResultFeedback error={error} warnings={mergeWarnings(warnings, result?.warnings)} />
      {result ? (
        <ResultSection title={`Mapping for ${result.mission}`}>
          <MappingTable mapping={result.mapping} />
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip
              color={capabilityColor(result.capabilities.rough_pi_to_energy.status)}
              label={`Rough conversion: ${result.capabilities.rough_pi_to_energy.status}`}
            />
            <Chip
              color={
                result.capabilities.specialized_interpretation.supported ? 'success' : 'default'
              }
              label={
                result.capabilities.specialized_interpretation.supported
                  ? 'Specialized interpretation supported'
                  : 'No specialized interpreter'
              }
            />
          </Stack>
          <ProvenancePanel provenance={result.provenance} />
        </ResultSection>
      ) : null}
    </Stack>
  );
};

export default MissionDatabasePanel;
