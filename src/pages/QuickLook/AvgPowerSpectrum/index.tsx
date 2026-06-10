import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
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
import { spectrumApi, PowerSpectrumData } from '@/api/spectrumApi';
import { parsePositiveNumber } from '@/utils/numbers';

const NORM_OPTIONS = ['leahy', 'frac', 'abs', 'none'];

const AvgPowerSpectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.0625');
  const [segmentSize, setSegmentSize] = useState('16');
  const [norm, setNorm] = useState('leahy');
  const [outputName, setOutputName] = useState('');
  const [logX, setLogX] = useState(true);
  const [logY, setLogY] = useState(true);
  const [rebinFactor, setRebinFactor] = useState('0.02');
  const [logRebin, setLogRebin] = useState(true);
  const [lastStoredName, setLastStoredName] = useState<string | null>(null);
  const lastActionRef = useRef<'create' | 'rebin'>('create');
  const { result, running, error, run } = useAnalysisRunner<PowerSpectrumData>('Averaged Power Spectrum');

  useEffect(() => {
    if (result?.name) {
      setLastStoredName(result.name);
    } else if (result && lastActionRef.current === 'create') {
      setLastStoredName(null);
    }
  }, [result]);

  const dtNum = parsePositiveNumber(dt);
  const segNum = parsePositiveNumber(segmentSize);
  const rebinNum = parsePositiveNumber(rebinFactor);
  const canRun = eventList !== '' && dtNum !== null && segNum !== null && !running;
  const rebinValid = logRebin ? rebinNum !== null : rebinNum !== null && rebinNum > 1;

  const handleRun = (): void => {
    lastActionRef.current = 'create';
    if (!dtNum || !segNum) return;
    void run(() =>
      spectrumApi.createAveragedPowerSpectrum({
        event_list_name: eventList,
        dt: dtNum,
        segment_size: segNum,
        norm,
        output_name: outputName.trim() || undefined,
      })
    );
  };

  const handleRebin = (): void => {
    lastActionRef.current = 'rebin';
    if (!lastStoredName || !rebinNum) return;
    void run(() =>
      spectrumApi.rebinSpectrum({ name: lastStoredName, rebin_factor: rebinNum, log: logRebin })
    );
  };

  const plotData: Data[] = result
    ? [
        {
          x: result.freq,
          y: result.power,
          type: 'scattergl',
          mode: 'lines',
          line: { color: '#00d4aa', width: 1 },
        },
      ]
    : [];

  return (
    <PageTemplate
      title="Averaged Power Spectrum"
      description="Welch-style averaged power spectrum over fixed-length segments"
      category="Frequency Domain"
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
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Segment size (s)"
                  size="small"
                  value={segmentSize}
                  onChange={(e) => setSegmentSize(e.target.value)}
                  error={segmentSize !== '' && segNum === null}
                  helperText={segmentSize !== '' && segNum === null ? 'Must be a positive number' : ' '}
                />
                <FormControl size="small">
                  <InputLabel id="ps-norm-label">Normalization</InputLabel>
                  <Select
                    labelId="ps-norm-label"
                    label="Normalization"
                    value={norm}
                    onChange={(e) => setNorm(e.target.value)}
                  >
                    {NORM_OPTIONS.map((n) => (
                      <MenuItem key={n} value={n}>
                        {n}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Store as (optional)"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                  placeholder={eventList ? `${eventList}_aps` : ''}
                  helperText="Required to enable rebinning"
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>

              {lastStoredName && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Stack spacing={2}>
                    <Typography variant="subtitle2">Rebin '{lastStoredName}'</Typography>
                    <TextField
                      label={logRebin ? 'Log rebin fraction f' : 'Linear rebin factor (× df)'}
                      size="small"
                      value={rebinFactor}
                      onChange={(e) => setRebinFactor(e.target.value)}
                      error={rebinFactor !== '' && !rebinValid}
                      helperText={logRebin ? 'Each bin grows by (1 + f)' : 'Must be > 1'}
                    />
                    <FormControlLabel
                      control={
                        <Switch
                          checked={logRebin}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setLogRebin(checked);
                            if (!checked && rebinNum !== null && rebinNum <= 1) {
                              setRebinFactor('2');
                            }
                          }}
                        />
                      }
                      label="Logarithmic"
                    />
                    <Button variant="outlined" disabled={!rebinValid || running} onClick={handleRebin}>
                      Rebin
                    </Button>
                  </Stack>
                </>
              )}
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
                {result?.norm && <Chip size="small" label={`norm: ${result.norm}`} />}
                {result && <Chip size="small" label={`${result.n_freq.toLocaleString()} freqs`} variant="outlined" />}
                {result?.n_segments != null && (
                  <Chip size="small" label={`${result.n_segments} segments`} variant="outlined" />
                )}
                {result?.df !== undefined && (
                  <Chip size="small" label={`df = ${result.df.toPrecision(3)} Hz`} variant="outlined" />
                )}
                <FormControlLabel
                  control={<Switch size="small" checked={logX} onChange={(e) => setLogX(e.target.checked)} />}
                  label="log f"
                />
                <FormControlLabel
                  control={<Switch size="small" checked={logY} onChange={(e) => setLogY(e.target.checked)} />}
                  label="log P"
                />
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={plotData}
                  layout={{
                    xaxis: { title: { text: 'Frequency (Hz)' }, type: logX ? 'log' : 'linear' },
                    yaxis: { title: { text: 'Power' }, type: logY ? 'log' : 'linear' },
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose an event list and compute a power spectrum.
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

export default AvgPowerSpectrumPage;
