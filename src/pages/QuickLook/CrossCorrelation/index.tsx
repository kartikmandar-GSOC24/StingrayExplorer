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

const MODE_OPTIONS = ['same', 'full'];
const NORM_OPTIONS = ['none', 'variance'];

const CrossCorrelationPage: React.FC = () => {
  const [eventList1, setEventList1] = useState('');
  const [eventList2, setEventList2] = useState('');
  const [dt, setDt] = useState('0.1');
  const [mode, setMode] = useState('same');
  const [norm, setNorm] = useState('none');
  const { result, running, error, run } = useAnalysisRunner<CorrelationData>('Cross Correlation');

  const dtNum = parsePositiveNumber(dt);
  const canRun = eventList1 !== '' && eventList2 !== '' && dtNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum) return;
    void run(() =>
      correlationApi.crossCorrelation({
        event_list_1_name: eventList1,
        event_list_2_name: eventList2,
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
          line: { color: '#00d4aa', width: 1 },
        } as Data,
      ]
    : [];

  const hasTimeShift = result != null && result.time_shift !== null;

  return (
    <PageTemplate
      title="Cross Correlation"
      description="Compute the cross-correlation function between two event lists and locate the time shift between them"
      category="Correlation Analysis"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list 1" value={eventList1} onChange={setEventList1} />
                <EventListSelector label="Event list 2" value={eventList2} onChange={setEventList2} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <FormControl size="small">
                  <InputLabel id="cc-mode-label">Mode</InputLabel>
                  <Select
                    labelId="cc-mode-label"
                    label="Mode"
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    {MODE_OPTIONS.map((m) => (
                      <MenuItem key={m} value={m}>
                        {m}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small">
                  <InputLabel id="cc-norm-label">Normalization</InputLabel>
                  <Select
                    labelId="cc-norm-label"
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
                {result && <Chip size="small" label={`n: ${result.n.toLocaleString()}`} variant="outlined" />}
                {result && <Chip size="small" label={`dt: ${result.dt} s`} variant="outlined" />}
                {result && <Chip size="small" label={`mode: ${result.mode}`} variant="outlined" />}
                {hasTimeShift && result && (
                  <Chip
                    size="small"
                    color="secondary"
                    label={`time shift: ${result.time_shift?.toFixed(4)} s`}
                  />
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
                <>
                  <PlotlyChart
                    data={traces}
                    layout={{
                      xaxis: { title: { text: 'Time lag (s)' } },
                      yaxis: { title: { text: 'Correlation' } },
                      shapes: hasTimeShift
                        ? [
                            {
                              type: 'line',
                              xref: 'x',
                              x0: result.time_shift as number,
                              x1: result.time_shift as number,
                              yref: 'paper',
                              y0: 0,
                              y1: 1,
                              line: { color: 'rgba(148, 163, 184, 0.7)', width: 1, dash: 'dash' },
                            },
                          ]
                        : [],
                    }}
                  />
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                    Positive shift means the first list lags the second.
                  </Typography>
                </>
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose two event lists and compute their cross-correlation.
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

export default CrossCorrelationPage;
