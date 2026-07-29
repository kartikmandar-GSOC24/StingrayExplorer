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
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { varenergyApi, LagSpectrumData } from '@/api/varenergyApi';
import { parsePositiveNumber } from '@/utils/numbers';

const LagEnergySpectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [binTime, setBinTime] = useState('0.01');
  const [segmentSize, setSegmentSize] = useState('8');
  const [freqMin, setFreqMin] = useState('0.1');
  const [freqMax, setFreqMax] = useState('1');
  const [energyMin, setEnergyMin] = useState('0.5');
  const [energyMax, setEnergyMax] = useState('10');
  const [nBands, setNBands] = useState('5');
  const [logBands, setLogBands] = useState(false);
  const [refMin, setRefMin] = useState('');
  const [refMax, setRefMax] = useState('');

  const { result, running, error, run } = useAnalysisRunner<LagSpectrumData>('Lag-Energy Spectrum');

  const binTimeNum = parsePositiveNumber(binTime);
  const segNum = parsePositiveNumber(segmentSize);
  const freqMinNum = parsePositiveNumber(freqMin);
  const freqMaxNum = parsePositiveNumber(freqMax);
  const energyMinNum = parsePositiveNumber(energyMin);
  const energyMaxNum = parsePositiveNumber(energyMax);
  const nBandsNum = parsePositiveNumber(nBands);
  const nBandsValid = nBandsNum !== null && Number.isInteger(nBandsNum) && nBandsNum >= 2;

  const freqRangeInverted =
    freqMinNum !== null && freqMaxNum !== null && freqMaxNum <= freqMinNum;
  const energyRangeInverted =
    energyMinNum !== null && energyMaxNum !== null && energyMaxNum <= energyMinNum;

  const refMinNum = parsePositiveNumber(refMin);
  const refMaxNum = parsePositiveNumber(refMax);
  const refMinFilled = refMin.trim() !== '';
  const refMaxFilled = refMax.trim() !== '';
  const refBandPartial = refMinFilled !== refMaxFilled;
  const refBandInverted =
    refMinNum !== null && refMaxNum !== null && refMaxNum <= refMinNum;
  const refBandValid =
    (!refMinFilled && !refMaxFilled) ||
    (refMinFilled &&
      refMaxFilled &&
      refMinNum !== null &&
      refMaxNum !== null &&
      !refBandInverted);

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
    nBandsValid &&
    refBandValid &&
    !running;

  const handleRun = (): void => {
    if (
      binTimeNum === null ||
      segNum === null ||
      freqMinNum === null ||
      freqMaxNum === null ||
      energyMinNum === null ||
      energyMaxNum === null ||
      nBandsNum === null
    ) {
      return;
    }
    const useRefBand =
      refMinFilled && refMaxFilled && refMinNum !== null && refMaxNum !== null;
    void run(() =>
      varenergyApi.lagSpectrum({
        event_list_name: eventList,
        bin_time: binTimeNum,
        segment_size: segNum,
        freq_min: freqMinNum,
        freq_max: freqMaxNum,
        energy_min: energyMinNum,
        energy_max: energyMaxNum,
        n_bands: nBandsNum,
        log_bands: logBands,
        ref_min: useRefBand ? refMinNum : null,
        ref_max: useRefBand ? refMaxNum : null,
      })
    );
  };

  const finiteSpectrum = result ? result.spectrum.filter((v): v is number => v !== null) : [];
  const allNull = result !== null && result.spectrum.length > 0 && finiteSpectrum.length === 0;

  const traces: Data[] = result
    ? [
        {
          x: result.energy,
          y: result.spectrum,
          type: 'scattergl',
          mode: 'markers',
          marker: { size: 7, color: '#00d4aa' },
          error_y: {
            type: 'data',
            array: result.spectrum_error,
            visible: true,
            color: 'rgba(0, 212, 170, 0.35)',
          },
        } as Data,
      ]
    : [];

  return (
    <PageTemplate
      title="Lag-Energy Spectrum"
      description="Frequency-averaged time lag as a function of energy, relative to a broad or user-chosen reference band"
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
                    helperText={
                      freqMin !== '' && freqMinNum === null
                        ? 'Must be a positive number'
                        : freqRangeInverted
                          ? 'f max must be > f min'
                          : ' '
                    }
                  />
                  <TextField
                    label="f max (Hz)"
                    size="small"
                    value={freqMax}
                    onChange={(e) => setFreqMax(e.target.value)}
                    error={(freqMax !== '' && freqMaxNum === null) || freqRangeInverted}
                    helperText={
                      freqMax !== '' && freqMaxNum === null
                        ? 'Must be a positive number'
                        : freqRangeInverted
                          ? 'f max must be > f min'
                          : ' '
                    }
                  />
                </Box>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="Energy min (keV)"
                    size="small"
                    value={energyMin}
                    onChange={(e) => setEnergyMin(e.target.value)}
                    error={(energyMin !== '' && energyMinNum === null) || energyRangeInverted}
                    helperText={
                      energyMin !== '' && energyMinNum === null
                        ? 'Must be a positive number'
                        : energyRangeInverted
                          ? 'max must be > min'
                          : ' '
                    }
                  />
                  <TextField
                    label="Energy max (keV)"
                    size="small"
                    value={energyMax}
                    onChange={(e) => setEnergyMax(e.target.value)}
                    error={(energyMax !== '' && energyMaxNum === null) || energyRangeInverted}
                    helperText={
                      energyMax !== '' && energyMaxNum === null
                        ? 'Must be a positive number'
                        : energyRangeInverted
                          ? 'max must be > min'
                          : ' '
                    }
                  />
                </Box>
                <TextField
                  label="Number of energy bands"
                  size="small"
                  value={nBands}
                  onChange={(e) => setNBands(e.target.value)}
                  error={nBands !== '' && !nBandsValid}
                  helperText={nBands !== '' && !nBandsValid ? 'Must be an integer >= 2' : ' '}
                />
                <FormControlLabel
                  control={
                    <Switch
                      size="small"
                      checked={logBands}
                      onChange={(e) => setLogBands(e.target.checked)}
                    />
                  }
                  label="Log-spaced energy bands"
                />
                <Typography variant="subtitle2">Reference band (optional)</Typography>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="Ref min (keV)"
                    size="small"
                    value={refMin}
                    onChange={(e) => setRefMin(e.target.value)}
                    error={(refMinFilled && refMinNum === null) || refBandPartial || refBandInverted}
                    helperText={
                      refMinFilled && refMinNum === null
                        ? 'Must be a positive number'
                        : refBandPartial
                          ? 'Fill both or leave both blank'
                          : refBandInverted
                            ? 'ref max must be > ref min'
                            : ' '
                    }
                  />
                  <TextField
                    label="Ref max (keV)"
                    size="small"
                    value={refMax}
                    onChange={(e) => setRefMax(e.target.value)}
                    error={(refMaxFilled && refMaxNum === null) || refBandPartial || refBandInverted}
                    helperText={
                      refMaxFilled && refMaxNum === null
                        ? 'Must be a positive number'
                        : refBandPartial
                          ? 'Fill both or leave both blank'
                          : refBandInverted
                            ? 'ref max must be > ref min'
                            : ' '
                    }
                  />
                </Box>
                <Typography variant="caption" color="text.secondary">
                  Leave both blank to use the full band as the reference; fill both to compare against a
                  specific band. stingray requires both edges or neither.
                </Typography>
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
                {result && (
                  <>
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`${result.freq_range[0]}–${result.freq_range[1]} Hz`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`≈ ${result.n_segments_hint} segments`}
                    />
                    {result.ref_band && (
                      <Chip
                        size="small"
                        variant="outlined"
                        label={`ref: ${result.ref_band[0]}–${result.ref_band[1]} keV`}
                      />
                    )}
                  </>
                )}
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
                allNull ? (
                  <Box sx={{ py: 10, textAlign: 'center' }}>
                    <Typography color="text.secondary">
                      No finite lag values in any energy band. See the warnings above for why (e.g. low
                      count rate or no variability above the Poisson floor) and try a coarser bin, fewer
                      bands, or a longer segment.
                    </Typography>
                  </Box>
                ) : (
                  <PlotlyChart
                    data={traces}
                    layout={{
                      xaxis: { title: { text: 'Energy (keV)' } },
                      yaxis: { title: { text: 'Time lag (s)' }, type: 'linear' },
                      shapes: [
                        {
                          type: 'line',
                          xref: 'paper',
                          x0: 0,
                          x1: 1,
                          yref: 'y',
                          y0: 0,
                          y1: 0,
                          line: { width: 1, dash: 'dash' },
                        },
                      ],
                    }}
                  />
                )
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose an event list and compute the lag-energy spectrum.
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

export default LagEnergySpectrumPage;
