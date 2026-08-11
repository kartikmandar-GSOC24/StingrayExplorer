import React, { useMemo, useState } from 'react';
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
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { timingApi, BispectrumData } from '@/api/timingApi';
import { parsePositiveNumber } from '@/utils/numbers';

const SCALE_OPTIONS = ['biased', 'unbiased'];
const WINDOW_OPTIONS = ['uniform', 'parzen', 'hamming', 'hanning', 'triangular', 'welch', 'blackmann', 'flat-top'];
const MAXLAG_CAP = 500;

const BispectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.1');
  const [maxlag, setMaxlag] = useState('25');
  const [scale, setScale] = useState('unbiased');
  const [windowFn, setWindowFn] = useState('uniform');
  const [outputName, setOutputName] = useState('');
  const [tab, setTab] = useState(0);
  const [logZ, setLogZ] = useState(true);
  const { result, running, error, run } = useAnalysisRunner<BispectrumData>('Bispectrum');

  const dtNum = parsePositiveNumber(dt);
  const maxlagNum = parsePositiveNumber(maxlag);
  const maxlagInt = maxlagNum === null ? null : Math.round(maxlagNum);
  const maxlagValid = maxlagInt !== null && maxlagInt >= 1 && maxlagInt <= MAXLAG_CAP;
  const canRun = eventList !== '' && dtNum !== null && maxlagValid && !running;

  const handleRun = (): void => {
    if (!dtNum || !maxlagInt || !maxlagValid) return;
    void run(() =>
      timingApi.createBispectrum({
        event_list_name: eventList,
        dt: dtNum,
        maxlag: maxlagInt,
        scale,
        window: windowFn,
        output_name: outputName.trim() || undefined,
      })
    );
  };

  const heatmapData = useMemo<Data[]>(() => {
    if (!result) return [];
    if (tab === 0) {
      const z = logZ
        ? result.bispec_mag.map((row) => row.map((v) => (v > 0 ? Math.log10(v) : null)))
        : result.bispec_mag;
      return [
        {
          z,
          x: result.freq,
          y: result.freq,
          type: 'heatmap',
          colorscale: 'Viridis',
          colorbar: { title: { text: logZ ? 'log10 |B|' : '|B|' } },
        } as Data,
      ];
    }
    return [
      {
        z: result.bispec_phase,
        x: result.freq,
        y: result.freq,
        type: 'heatmap',
        colorscale: 'RdBu',
        zmid: 0,
        colorbar: { title: { text: 'Phase (rad)' } },
      } as Data,
    ];
  }, [result, tab, logZ]);

  return (
    <PageTemplate
      title="Bispectrum"
      description="Third-order spectrum revealing nonlinear interactions and phase coupling"
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
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Max lag (bins)"
                  size="small"
                  value={maxlag}
                  onChange={(e) => setMaxlag(e.target.value)}
                  error={maxlag !== '' && !maxlagValid}
                  helperText={
                    maxlag !== '' && !maxlagValid
                      ? 'Integer between 1 and 500'
                      : 'Bispectrum size is (2·maxlag+1)²; keep ≤ 100'
                  }
                />
                <FormControl size="small">
                  <InputLabel id="bs-scale-label">Scale</InputLabel>
                  <Select
                    labelId="bs-scale-label"
                    label="Scale"
                    value={scale}
                    onChange={(e) => setScale(e.target.value)}
                  >
                    {SCALE_OPTIONS.map((s) => (
                      <MenuItem key={s} value={s}>
                        {s}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small">
                  <InputLabel id="bs-window-label">Window</InputLabel>
                  <Select
                    labelId="bs-window-label"
                    label="Window"
                    value={windowFn}
                    onChange={(e) => setWindowFn(e.target.value)}
                  >
                    {WINDOW_OPTIONS.map((w) => (
                      <MenuItem key={w} value={w}>
                        {w}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Store as (optional)"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
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
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Tabs value={tab} onChange={(_e, v: number) => setTab(v)} sx={{ flexGrow: 1 }}>
                  <Tab label="Magnitude" />
                  <Tab label="Phase" />
                </Tabs>
                {result && <Chip size="small" label={`maxlag ${result.maxlag}`} variant="outlined" />}
                {result && <Chip size="small" label={result.window} variant="outlined" />}
                {tab === 0 && (
                  <FormControlLabel
                    control={<Switch size="small" checked={logZ} onChange={(e) => setLogZ(e.target.checked)} />}
                    label="log color"
                  />
                )}
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={heatmapData}
                  layout={{
                    xaxis: { title: { text: 'Frequency f1 (Hz)' } },
                    yaxis: { title: { text: 'Frequency f2 (Hz)' } },
                  }}
                  height={520}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Compute a bispectrum to see magnitude and phase maps.
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

export default BispectrumPage;
