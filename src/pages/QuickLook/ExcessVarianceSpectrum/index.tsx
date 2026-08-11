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
import { varenergyApi, ExcessVarianceData } from '@/api/varenergyApi';
import { parsePositiveNumber } from '@/utils/numbers';

const NORMALIZATION_OPTIONS = ['fvar', 'none'] as const;

/**
 * Positive-integer parser for the band-count field. `src/utils/numbers.ts`
 * only exposes `parsePositiveNumber`/`parseNumber` (no integer variant), so
 * this small helper lives locally rather than widening a shared module.
 */
function parsePositiveInteger(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && Number.isInteger(n) && n > 0 ? n : null;
}

const ExcessVarianceSpectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  // The backend report flags small bin_time as the most common cause of an
  // all-NaN excess variance; 0.1 s is the recommended, pre-validated default.
  const [binTime, setBinTime] = useState('0.1');
  const [energyMin, setEnergyMin] = useState('0.5');
  const [energyMax, setEnergyMax] = useState('10');
  const [nBands, setNBands] = useState('5');
  const [logBands, setLogBands] = useState(false);
  const [normalization, setNormalization] = useState<'fvar' | 'none'>('fvar');

  const { result, running, error, run } = useAnalysisRunner<ExcessVarianceData>(
    'Excess Variance Spectrum'
  );

  const binTimeNum = parsePositiveNumber(binTime);
  const energyMinNum = parsePositiveNumber(energyMin);
  const energyMaxNum = parsePositiveNumber(energyMax);
  const nBandsNum = parsePositiveInteger(nBands);

  const energyMinInvalid = energyMin !== '' && energyMinNum === null;
  const energyMaxInvalid = energyMax !== '' && energyMaxNum === null;
  const energyRangeInverted =
    energyMinNum !== null && energyMaxNum !== null && energyMaxNum <= energyMinNum;
  const energyRangeValid =
    energyMinNum !== null && energyMaxNum !== null && !energyRangeInverted;

  const nBandsInvalid = nBands !== '' && (nBandsNum === null || nBandsNum < 2);

  const canRun =
    eventList !== '' &&
    binTimeNum !== null &&
    energyRangeValid &&
    nBandsNum !== null &&
    nBandsNum >= 2 &&
    !running;

  const energyHelperText = (invalid: boolean): string => {
    if (invalid) return 'Must be a positive number';
    if (energyRangeInverted) return 'E max must be > E min';
    return ' ';
  };

  const handleRun = (): void => {
    if (binTimeNum === null || !energyRangeValid || nBandsNum === null || nBandsNum < 2) return;
    void run(() =>
      varenergyApi.excessVariance({
        event_list_name: eventList,
        bin_time: binTimeNum,
        energy_min: energyMinNum as number,
        energy_max: energyMaxNum as number,
        n_bands: nBandsNum,
        log_bands: logBands,
        normalization,
      })
    );
  };

  // Filter nulls for the empty-result check only; the raw arrays (which may
  // contain nulls) are still passed straight through to Plotly below.
  const finiteSpectrum = result ? result.spectrum.filter((v): v is number => v !== null) : [];
  const allNull = result !== null && result.spectrum.length > 0 && finiteSpectrum.length === 0;

  const traces: Data[] = result
    ? [
        {
          x: result.energy,
          y: result.spectrum,
          type: 'scattergl',
          mode: 'markers',
          marker: { size: 7 },
          error_y: { type: 'data', array: result.spectrum_error, visible: true },
        } as Data,
      ]
    : [];

  const yAxisTitle = normalization === 'fvar' ? 'F_var' : 'Excess variance';

  return (
    <PageTemplate
      title="Excess Variance Spectrum"
      description="Compute excess variance as a function of energy"
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
                  helperText={
                    binTime !== '' && binTimeNum === null
                      ? 'Must be a positive number'
                      : 'Small values can yield an all-NaN result; 0.1 s is a safe default'
                  }
                />
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="Energy min (keV)"
                    size="small"
                    value={energyMin}
                    onChange={(e) => setEnergyMin(e.target.value)}
                    error={energyMinInvalid || energyRangeInverted}
                    helperText={energyHelperText(energyMinInvalid)}
                  />
                  <TextField
                    label="Energy max (keV)"
                    size="small"
                    value={energyMax}
                    onChange={(e) => setEnergyMax(e.target.value)}
                    error={energyMaxInvalid || energyRangeInverted}
                    helperText={energyHelperText(energyMaxInvalid)}
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
                    <Switch
                      size="small"
                      checked={logBands}
                      onChange={(e) => setLogBands(e.target.checked)}
                    />
                  }
                  label="Log-spaced energy bands"
                />
                <FormControl size="small" fullWidth>
                  <InputLabel id="evs-normalization-label">Normalization</InputLabel>
                  <Select
                    labelId="evs-normalization-label"
                    label="Normalization"
                    value={normalization}
                    onChange={(e) => setNormalization(e.target.value as 'fvar' | 'none')}
                  >
                    {NORMALIZATION_OPTIONS.map((n) => (
                      <MenuItem key={n} value={n}>
                        {n}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
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
                      label={`normalization: ${result.normalization}`}
                      variant="outlined"
                    />
                    <Chip size="small" label={`n bands: ${result.energy.length}`} variant="outlined" />
                  </>
                )}
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result && result.warnings.length > 0 && (
                <Alert severity="warning" variant={allNull ? 'filled' : 'standard'} sx={{ mb: 1 }}>
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
                <PlotlyChart
                  data={traces}
                  layout={{
                    xaxis: { title: { text: 'Energy (keV)' } },
                    yaxis: { title: { text: yAxisTitle } },
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose an event list and compute its excess variance spectrum.
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

export default ExcessVarianceSpectrumPage;
