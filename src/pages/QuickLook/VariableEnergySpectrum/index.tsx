import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControlLabel,
  Grid,
  Stack,
  Switch,
  TextField,
  Typography,
  useTheme,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { varenergyApi, VariableEnergySpectrumData } from '@/api/varenergyApi';
import { parsePositiveNumber } from '@/utils/numbers';

/** Shared helper text for a required min/max numeric pair. */
const rangeHelperText = (raw: string, parsed: number | null, inverted: boolean): string => {
  if (raw !== '' && parsed === null) return 'Must be a positive number';
  if (inverted) return 'max must be > min';
  return ' ';
};

const VariableEnergySpectrumPage: React.FC = () => {
  const theme = useTheme();

  const [eventList, setEventList] = useState('');
  const [binTime, setBinTime] = useState('0.1');
  const [segmentSize, setSegmentSize] = useState('8');
  const [freqMin, setFreqMin] = useState('0.1');
  const [freqMax, setFreqMax] = useState('1');
  const [energyMin, setEnergyMin] = useState('0.5');
  const [energyMax, setEnergyMax] = useState('10');
  const [nBands, setNBands] = useState('5');
  const [logBands, setLogBands] = useState(false);
  const [refMin, setRefMin] = useState('');
  const [refMax, setRefMax] = useState('');
  const [logX, setLogX] = useState(false);

  const { result, running, error, run } = useAnalysisRunner<VariableEnergySpectrumData>(
    'Variable Energy Spectrum'
  );

  const binTimeNum = parsePositiveNumber(binTime);
  const segNum = parsePositiveNumber(segmentSize);

  const freqMinNum = parsePositiveNumber(freqMin);
  const freqMaxNum = parsePositiveNumber(freqMax);
  const freqRangeInverted =
    freqMinNum !== null && freqMaxNum !== null && freqMaxNum <= freqMinNum;

  const energyMinNum = parsePositiveNumber(energyMin);
  const energyMaxNum = parsePositiveNumber(energyMax);
  const energyRangeInverted =
    energyMinNum !== null && energyMaxNum !== null && energyMaxNum <= energyMinNum;

  const nBandsNum = ((): number | null => {
    const n = Number(nBands);
    return Number.isInteger(n) && n >= 2 ? n : null;
  })();
  const nBandsInvalid = nBands !== '' && nBandsNum === null;

  const refMinNum = parsePositiveNumber(refMin);
  const refMaxNum = parsePositiveNumber(refMax);
  const refPartial = (refMin !== '') !== (refMax !== '');
  const refInverted = refMinNum !== null && refMaxNum !== null && refMaxNum <= refMinNum;
  const refValid =
    !refPartial &&
    !(refMin !== '' && refMinNum === null) &&
    !(refMax !== '' && refMaxNum === null) &&
    !refInverted;

  const refHelperText = (raw: string, parsed: number | null): string => {
    if (raw !== '' && parsed === null) return 'Must be a positive number';
    if (refPartial) return 'Fill both or leave both blank';
    if (refInverted) return 'max must be > min';
    return ' ';
  };

  const canRun =
    eventList !== '' &&
    binTimeNum !== null &&
    segNum !== null &&
    freqMinNum !== null &&
    freqMaxNum !== null &&
    !freqRangeInverted &&
    energyMinNum !== null &&
    energyMaxNum !== null &&
    !energyRangeInverted &&
    nBandsNum !== null &&
    refValid &&
    !running;

  const handleRun = (): void => {
    if (
      !binTimeNum ||
      !segNum ||
      !freqMinNum ||
      !freqMaxNum ||
      !energyMinNum ||
      !energyMaxNum ||
      !nBandsNum
    ) {
      return;
    }
    void run(() =>
      varenergyApi.variableEnergySpectrum({
        event_list_name: eventList,
        bin_time: binTimeNum,
        segment_size: segNum,
        freq_min: freqMinNum,
        freq_max: freqMaxNum,
        energy_min: energyMinNum,
        energy_max: energyMaxNum,
        n_bands: nBandsNum,
        log_bands: logBands,
        ref_min: refMinNum ?? undefined,
        ref_max: refMaxNum ?? undefined,
      })
    );
  };

  const energyAxis: { title: { text: string }; type: 'log' | 'linear' } = {
    title: { text: 'Energy (keV)' },
    type: logX ? 'log' : 'linear',
  };

  const countsTraces: Data[] = result
    ? [
        {
          x: result.energy,
          y: result.counts.spectrum,
          type: 'scattergl',
          mode: 'lines+markers',
          error_y: { type: 'data', array: result.counts.error, visible: true },
        } as Data,
      ]
    : [];

  const rmsTraces: Data[] = result
    ? [
        {
          x: result.energy,
          y: result.rms.spectrum,
          type: 'scattergl',
          mode: 'lines+markers',
          error_y: { type: 'data', array: result.rms.error, visible: true },
        } as Data,
      ]
    : [];

  const lagTraces: Data[] = result
    ? [
        {
          x: result.energy,
          y: result.lag.spectrum,
          type: 'scattergl',
          mode: 'lines+markers',
          error_y: { type: 'data', array: result.lag.error, visible: true },
        } as Data,
      ]
    : [];

  return (
    <PageTemplate
      title="Variable Energy Spectrum"
      description="Counts, fractional rms, and time lag vs energy from shared frequency and segment parameters"
      category="Energy Dependent Analysis"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list" value={eventList} onChange={setEventList} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={binTime}
                  onChange={(e) => setBinTime(e.target.value)}
                  error={binTime !== '' && binTimeNum === null}
                  helperText={binTime !== '' && binTimeNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Segment size (s)"
                  size="small"
                  value={segmentSize}
                  onChange={(e) => setSegmentSize(e.target.value)}
                  error={segmentSize !== '' && segNum === null}
                  helperText={segmentSize !== '' && segNum === null ? 'Must be a positive number' : ' '}
                />
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="f min (Hz)"
                    size="small"
                    value={freqMin}
                    onChange={(e) => setFreqMin(e.target.value)}
                    error={(freqMin !== '' && freqMinNum === null) || freqRangeInverted}
                    helperText={rangeHelperText(freqMin, freqMinNum, freqRangeInverted)}
                  />
                  <TextField
                    label="f max (Hz)"
                    size="small"
                    value={freqMax}
                    onChange={(e) => setFreqMax(e.target.value)}
                    error={(freqMax !== '' && freqMaxNum === null) || freqRangeInverted}
                    helperText={rangeHelperText(freqMax, freqMaxNum, freqRangeInverted)}
                  />
                </Box>
                <Typography variant="subtitle2">Energy bands (keV)</Typography>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="E min"
                    size="small"
                    value={energyMin}
                    onChange={(e) => setEnergyMin(e.target.value)}
                    error={(energyMin !== '' && energyMinNum === null) || energyRangeInverted}
                    helperText={rangeHelperText(energyMin, energyMinNum, energyRangeInverted)}
                  />
                  <TextField
                    label="E max"
                    size="small"
                    value={energyMax}
                    onChange={(e) => setEnergyMax(e.target.value)}
                    error={(energyMax !== '' && energyMaxNum === null) || energyRangeInverted}
                    helperText={rangeHelperText(energyMax, energyMaxNum, energyRangeInverted)}
                  />
                </Box>
                <TextField
                  label="Number of bands"
                  size="small"
                  value={nBands}
                  onChange={(e) => setNBands(e.target.value)}
                  error={nBandsInvalid}
                  helperText={nBandsInvalid ? 'Must be an integer ≥ 2' : ' '}
                />
                <FormControlLabel
                  control={
                    <Switch size="small" checked={logBands} onChange={(e) => setLogBands(e.target.checked)} />
                  }
                  label="Log-spaced energy bands"
                />
                <Typography variant="subtitle2">Reference band (optional)</Typography>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="ref min (keV)"
                    size="small"
                    value={refMin}
                    onChange={(e) => setRefMin(e.target.value)}
                    error={!refValid}
                    helperText={refHelperText(refMin, refMinNum)}
                  />
                  <TextField
                    label="ref max (keV)"
                    size="small"
                    value={refMax}
                    onChange={(e) => setRefMax(e.target.value)}
                    error={!refValid}
                    helperText={refHelperText(refMax, refMaxNum)}
                  />
                </Box>
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                  Result
                </Typography>
                {result?.freq_range && (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${result.freq_range[0]}–${result.freq_range[1]} Hz`}
                  />
                )}
                {result && (
                  <Chip size="small" variant="outlined" label={`≈ ${result.n_segments_hint} segments`} />
                )}
                {result?.ref_band && (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`ref ${result.ref_band[0]}–${result.ref_band[1]} keV`}
                  />
                )}
                <FormControlLabel
                  control={<Switch size="small" checked={logX} onChange={(e) => setLogX(e.target.checked)} />}
                  label="log E"
                />
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result && result.warnings.length > 0 && (
                <Alert severity="warning" sx={{ mb: 1 }}>
                  <Stack spacing={0.5}>
                    {result.warnings.map((w, i) => (
                      <Typography key={i} variant="body2">
                        {w}
                      </Typography>
                    ))}
                  </Stack>
                </Alert>
              )}
              {result ? (
                <Stack spacing={3}>
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Counts vs energy
                    </Typography>
                    <PlotlyChart
                      data={countsTraces}
                      layout={{
                        xaxis: energyAxis,
                        yaxis: { title: { text: 'Counts' }, type: 'log' },
                      }}
                      height={280}
                    />
                  </Box>
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Fractional rms vs energy
                    </Typography>
                    <PlotlyChart
                      data={rmsTraces}
                      layout={{
                        xaxis: energyAxis,
                        yaxis: { title: { text: 'Fractional rms' } },
                      }}
                      height={280}
                    />
                  </Box>
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Lag vs energy
                    </Typography>
                    <PlotlyChart
                      data={lagTraces}
                      layout={{
                        xaxis: energyAxis,
                        yaxis: { title: { text: 'Lag (s)' } },
                        shapes: [
                          {
                            type: 'line',
                            xref: 'paper',
                            x0: 0,
                            x1: 1,
                            yref: 'y',
                            y0: 0,
                            y1: 0,
                            line: { color: theme.palette.divider, width: 1, dash: 'dash' },
                          },
                        ],
                      }}
                      height={280}
                    />
                    <Typography variant="caption" color="text.secondary">
                      The reference band affects only the lag panel.
                    </Typography>
                  </Box>
                </Stack>
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose an event list and compute the variable-energy spectrum.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default VariableEnergySpectrumPage;
