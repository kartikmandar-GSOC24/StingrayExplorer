import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
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
import { varenergyApi, CovarianceSpectrumData } from '@/api/varenergyApi';
import { parsePositiveNumber } from '@/utils/numbers';

type CovarianceNorm = 'abs' | 'frac';

const CovarianceSpectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [binTime, setBinTime] = useState('0.1');
  const [freqMin, setFreqMin] = useState('0.1');
  const [freqMax, setFreqMax] = useState('1');
  const [energyMin, setEnergyMin] = useState('0.5');
  const [energyMax, setEnergyMax] = useState('10');
  const [nBands, setNBands] = useState('5');
  const [logBands, setLogBands] = useState(false);
  const [refMin, setRefMin] = useState('');
  const [refMax, setRefMax] = useState('');
  const [norm, setNorm] = useState<CovarianceNorm>('abs');
  const [logEnergy, setLogEnergy] = useState(false);

  const { result, running, error, run } = useAnalysisRunner<CovarianceSpectrumData>(
    'Covariance Spectrum'
  );

  const binTimeNum = parsePositiveNumber(binTime);

  const freqMinNum = parsePositiveNumber(freqMin);
  const freqMaxNum = parsePositiveNumber(freqMax);
  const freqMinInvalid = freqMin !== '' && freqMinNum === null;
  const freqMaxInvalid = freqMax !== '' && freqMaxNum === null;
  const freqInverted = freqMinNum !== null && freqMaxNum !== null && freqMaxNum <= freqMinNum;
  const freqValid =
    !freqMinInvalid && !freqMaxInvalid && freqMinNum !== null && freqMaxNum !== null && !freqInverted;

  const energyMinNum = parsePositiveNumber(energyMin);
  const energyMaxNum = parsePositiveNumber(energyMax);
  const energyMinInvalid = energyMin !== '' && energyMinNum === null;
  const energyMaxInvalid = energyMax !== '' && energyMaxNum === null;
  const energyInverted =
    energyMinNum !== null && energyMaxNum !== null && energyMaxNum <= energyMinNum;
  const energyValid =
    !energyMinInvalid &&
    !energyMaxInvalid &&
    energyMinNum !== null &&
    energyMaxNum !== null &&
    !energyInverted;

  const nBandsNum = parsePositiveNumber(nBands);
  const nBandsValid = nBandsNum !== null && Number.isInteger(nBandsNum) && nBandsNum >= 2;

  const refMinNum = refMin !== '' ? parsePositiveNumber(refMin) : null;
  const refMaxNum = refMax !== '' ? parsePositiveNumber(refMax) : null;
  const refMinInvalid = refMin !== '' && refMinNum === null;
  const refMaxInvalid = refMax !== '' && refMaxNum === null;
  const refPartial = (refMin !== '') !== (refMax !== '');
  const refInverted = refMinNum !== null && refMaxNum !== null && refMaxNum <= refMinNum;
  const refValid = !refMinInvalid && !refMaxInvalid && !refPartial && !refInverted;

  const canRun =
    eventList !== '' &&
    binTimeNum !== null &&
    freqValid &&
    energyValid &&
    nBandsValid &&
    refValid &&
    !running;

  const freqHelperText = (raw: string, parsed: number | null): string => {
    if (raw !== '' && parsed === null) return 'Must be a positive number';
    if (freqInverted) return 'f max must be > f min';
    return ' ';
  };

  const energyHelperText = (raw: string, parsed: number | null): string => {
    if (raw !== '' && parsed === null) return 'Must be a positive number';
    if (energyInverted) return 'energy max must be > energy min';
    return ' ';
  };

  const refHelperText = (raw: string, parsed: number | null): string => {
    if (raw !== '' && parsed === null) return 'Must be a positive number';
    if (refPartial) return 'Fill both or leave both blank';
    if (refInverted) return 'ref max must be > ref min';
    return ' ';
  };

  const handleRun = (): void => {
    if (
      binTimeNum === null ||
      freqMinNum === null ||
      freqMaxNum === null ||
      energyMinNum === null ||
      energyMaxNum === null ||
      nBandsNum === null
    ) {
      return;
    }
    void run(() =>
      varenergyApi.covarianceSpectrum({
        event_list_name: eventList,
        bin_time: binTimeNum,
        freq_min: freqMinNum,
        freq_max: freqMaxNum,
        energy_min: energyMinNum,
        energy_max: energyMaxNum,
        n_bands: nBandsNum,
        log_bands: logBands,
        ref_min: refMinNum,
        ref_max: refMaxNum,
        norm,
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
          error_y: { type: 'data', array: result.spectrum_error, visible: true },
          type: 'scattergl',
          mode: 'markers',
        } as Data,
      ]
    : [];

  const yAxisLabel = result?.norm === 'frac' ? 'Covariance (fractional)' : 'Covariance (absolute)';

  return (
    <PageTemplate
      title="Covariance Spectrum"
      description="Compute covariance spectrum to study energy-dependent variability"
      category="Advanced Analysis"
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
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="f min (Hz)"
                    size="small"
                    value={freqMin}
                    onChange={(e) => setFreqMin(e.target.value)}
                    error={freqMinInvalid || freqInverted}
                    helperText={freqHelperText(freqMin, freqMinNum)}
                  />
                  <TextField
                    label="f max (Hz)"
                    size="small"
                    value={freqMax}
                    onChange={(e) => setFreqMax(e.target.value)}
                    error={freqMaxInvalid || freqInverted}
                    helperText={freqHelperText(freqMax, freqMaxNum)}
                  />
                </Box>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="Energy min (keV)"
                    size="small"
                    value={energyMin}
                    onChange={(e) => setEnergyMin(e.target.value)}
                    error={energyMinInvalid || energyInverted}
                    helperText={energyHelperText(energyMin, energyMinNum)}
                  />
                  <TextField
                    label="Energy max (keV)"
                    size="small"
                    value={energyMax}
                    onChange={(e) => setEnergyMax(e.target.value)}
                    error={energyMaxInvalid || energyInverted}
                    helperText={energyHelperText(energyMax, energyMaxNum)}
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
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="Ref band min (keV)"
                    size="small"
                    value={refMin}
                    onChange={(e) => setRefMin(e.target.value)}
                    error={refMinInvalid || refPartial || refInverted}
                    helperText={refHelperText(refMin, refMinNum)}
                  />
                  <TextField
                    label="Ref band max (keV)"
                    size="small"
                    value={refMax}
                    onChange={(e) => setRefMax(e.target.value)}
                    error={refMaxInvalid || refPartial || refInverted}
                    helperText={refHelperText(refMax, refMaxNum)}
                  />
                </Box>
                <Typography variant="caption" color="text.secondary">
                  Leave the reference band blank to use the full energy range. Covariance measures
                  variability correlated with this band.
                </Typography>
                <FormControl size="small" fullWidth>
                  <InputLabel id="covariance-norm-label">Normalization</InputLabel>
                  <Select
                    labelId="covariance-norm-label"
                    label="Normalization"
                    value={norm}
                    onChange={(e) => setNorm(e.target.value as CovarianceNorm)}
                  >
                    <MenuItem value="abs">abs</MenuItem>
                    <MenuItem value="frac">frac</MenuItem>
                  </Select>
                </FormControl>
                <Typography variant="caption" color="text.secondary">
                  {norm === 'frac'
                    ? 'Fractional normalization is unitless (divided by the mean count rate).'
                    : 'Absolute normalization retains the source count-rate scale.'}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  No segment-size control: the spectrum is computed over one segment spanning the
                  longest good-time interval. Use Avg Covariance Spectrum to average over multiple
                  segments.
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
                      label={`${result.n_segments_hint} segment${
                        result.n_segments_hint === 1 ? '' : 's'
                      } · ${result.segment_size} s (full GTI)`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`${result.freq_range[0]}–${result.freq_range[1]} Hz`}
                    />
                    <Chip size="small" variant="outlined" label={`norm: ${result.norm}`} />
                    {result.ref_band && (
                      <Chip
                        size="small"
                        variant="outlined"
                        label={`ref band: ${result.ref_band[0]}–${result.ref_band[1]} keV`}
                      />
                    )}
                  </>
                )}
                <FormControlLabel
                  control={
                    <Switch
                      size="small"
                      checked={logEnergy}
                      onChange={(e) => setLogEnergy(e.target.checked)}
                    />
                  }
                  label="log energy"
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
                allNull ? (
                  <Box sx={{ py: 10, textAlign: 'center' }}>
                    <Typography color="text.secondary">
                      No finite covariance values in any energy band. This is expected for
                      Poisson-dominated or weakly variable sources — it is not an error. See the
                      warnings above and try a coarser bin, fewer bands, or a source with stronger
                      correlated variability.
                    </Typography>
                  </Box>
                ) : (
                  <PlotlyChart
                    data={traces}
                    layout={{
                      xaxis: { title: { text: 'Energy (keV)' }, type: logEnergy ? 'log' : 'linear' },
                      yaxis: { title: { text: yAxisLabel }, type: 'linear', zeroline: true },
                    }}
                  />
                )
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose an event list and compute its covariance spectrum.
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

export default CovarianceSpectrumPage;
