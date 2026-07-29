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
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { correlationApi, CorrelationData } from '@/api/correlationApi';
import { parsePositiveNumber } from '@/utils/numbers';

const AutoCorrelationPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.1');
  const [mode, setMode] = useState<'same' | 'full'>('same');
  const [norm, setNorm] = useState<'none' | 'variance'>('none');

  const { result, running, error, run } = useAnalysisRunner<CorrelationData>('Auto Correlation');

  const dtNum = parsePositiveNumber(dt);
  const canRun = eventList !== '' && dtNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum) return;
    void run(() =>
      correlationApi.autoCorrelation({
        event_list_name: eventList,
        dt: dtNum,
        mode,
        norm,
      })
    );
  };

  const traces: Data[] = result
    ? [
        {
          x: result.time_lags,
          y: result.corr,
          type: 'scattergl',
          mode: 'lines',
          line: { width: 1 },
        } as Data,
      ]
    : [];

  return (
    <PageTemplate
      title="Auto Correlation"
      description="Compute the auto-correlation function of a single event list"
      category="Correlation Analysis"
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
                <FormControl size="small" fullWidth>
                  <InputLabel id="auto-corr-mode-label">Mode</InputLabel>
                  <Select
                    labelId="auto-corr-mode-label"
                    label="Mode"
                    value={mode}
                    onChange={(e) => setMode(e.target.value as 'same' | 'full')}
                  >
                    <MenuItem value="same">same</MenuItem>
                    <MenuItem value="full">full</MenuItem>
                  </Select>
                </FormControl>
                <FormControl size="small" fullWidth>
                  <InputLabel id="auto-corr-norm-label">Normalization</InputLabel>
                  <Select
                    labelId="auto-corr-norm-label"
                    label="Normalization"
                    value={norm}
                    onChange={(e) => setNorm(e.target.value as 'none' | 'variance')}
                  >
                    <MenuItem value="none">none</MenuItem>
                    <MenuItem value="variance">variance</MenuItem>
                  </Select>
                </FormControl>
                <Typography variant="caption" color="text.secondary">
                  {norm === 'variance'
                    ? "Variance normalization scales the correlation to roughly [-1, 1]."
                    : "Counts² scale (unnormalized correlation)."}
                  {' '}The time shift is always 0 for an auto-correlation by construction &mdash; it
                  is not shown as a measurement here.
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
                    <Chip size="small" label={`n = ${result.n}`} variant="outlined" />
                    <Chip size="small" label={`dt = ${result.dt} s`} variant="outlined" />
                    <Chip size="small" label={`mode: ${result.mode}`} variant="outlined" />
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
                <PlotlyChart
                  data={traces}
                  layout={{
                    xaxis: { title: { text: 'Time lag (s)' } },
                    yaxis: {
                      title: { text: norm === 'variance' ? 'Correlation (normalized)' : 'Correlation (counts²)' },
                    },
                    shapes: [
                      {
                        type: 'line',
                        xref: 'x',
                        x0: 0,
                        x1: 0,
                        yref: 'paper',
                        y0: 0,
                        y1: 1,
                        line: { width: 1, dash: 'dash' },
                      },
                    ],
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose an event list and compute its auto-correlation.
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

export default AutoCorrelationPage;
