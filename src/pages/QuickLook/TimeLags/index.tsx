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
import { timingApi, TimeLagsData } from '@/api/timingApi';
import { parsePositiveNumber, parseNumber } from '@/utils/numbers';

const TimeLagsPage: React.FC = () => {
  const [eventList1, setEventList1] = useState('');
  const [eventList2, setEventList2] = useState('');
  const [dt, setDt] = useState('0.0625');
  const [segmentSize, setSegmentSize] = useState('16');
  const [freqMin, setFreqMin] = useState('');
  const [freqMax, setFreqMax] = useState('');
  const [logX, setLogX] = useState(true);
  const { result, running, error, run } = useAnalysisRunner<TimeLagsData>('Time Lags');

  const dtNum = parsePositiveNumber(dt);
  const segNum = parsePositiveNumber(segmentSize);
  const fMin = parseNumber(freqMin);
  const fMax = parseNumber(freqMax);
  const canRun = eventList1 !== '' && eventList2 !== '' && dtNum !== null && segNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum || !segNum) return;
    const freq_range: [number, number] | undefined =
      fMin !== null && fMax !== null && fMax > fMin ? [fMin, fMax] : undefined;
    void run(() =>
      timingApi.calculateTimeLags({
        event_list_1_name: eventList1,
        event_list_2_name: eventList2,
        dt: dtNum,
        segment_size: segNum,
        freq_range,
      })
    );
  };

  const traces: Data[] = result
    ? [
        {
          x: result.freq,
          y: result.time_lags,
          type: 'scattergl',
          mode: 'lines+markers',
          marker: { size: 4, color: '#00d4aa' },
          line: { color: '#00d4aa', width: 1 },
          error_y: result.time_lags_err
            ? { type: 'data', array: result.time_lags_err, visible: true, color: 'rgba(0, 212, 170, 0.35)' }
            : undefined,
        } as Data,
      ]
    : [];

  return (
    <PageTemplate
      title="Time Lags"
      description="Frequency-dependent time lags between two energy bands (positive = band 1 lags band 2)"
      category="Frequency Domain"
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
                  />
                  <TextField
                    label="f max (Hz)"
                    size="small"
                    value={freqMax}
                    onChange={(e) => setFreqMax(e.target.value)}
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
                    label={`${result.freq_range[0]}–${result.freq_range[1]} Hz`}
                    variant="outlined"
                  />
                )}
                <FormControlLabel
                  control={<Switch size="small" checked={logX} onChange={(e) => setLogX(e.target.checked)} />}
                  label="log f"
                />
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={traces}
                  layout={{
                    xaxis: { title: { text: 'Frequency (Hz)' }, type: logX ? 'log' : 'linear' },
                    yaxis: { title: { text: 'Time lag (s)' } },
                    shapes: [
                      {
                        type: 'line',
                        xref: 'paper',
                        x0: 0,
                        x1: 1,
                        yref: 'y',
                        y0: 0,
                        y1: 0,
                        line: { color: 'rgba(148, 163, 184, 0.5)', width: 1, dash: 'dash' },
                      },
                    ],
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose two event lists and compute their time lags.
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

export default TimeLagsPage;
