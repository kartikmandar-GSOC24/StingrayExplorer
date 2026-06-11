import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Grid,
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
import { timingApi, PowerColorsData } from '@/api/timingApi';
import { parsePositiveNumber } from '@/utils/numbers';
import { computePowerColorRatios } from '@/utils/powerColors';

interface BandInput {
  label: string;
  fmin: string;
  fmax: string;
}

// Heil et al. (2015) bands; require dt <= 1/(2*16) s for the top band.
const DEFAULT_BANDS: BandInput[] = [
  { label: 'A', fmin: '0.0039', fmax: '0.031' },
  { label: 'B', fmin: '0.031', fmax: '0.25' },
  { label: 'C', fmin: '0.25', fmax: '2.0' },
  { label: 'D', fmin: '2.0', fmax: '16.0' },
];

const BAND_COLORS = ['#00d4aa', '#3b82f6', '#f59e0b', '#ef4444'];

const PowerColorsPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.03125');
  const [segmentSize, setSegmentSize] = useState('64');
  const [bands, setBands] = useState<BandInput[]>(DEFAULT_BANDS);
  const { result, running, error, run } = useAnalysisRunner<PowerColorsData>('Power Colors');

  const dtNum = parsePositiveNumber(dt);
  const segNum = parsePositiveNumber(segmentSize);

  const parsedBands = bands.map((b) => ({
    label: b.label,
    fmin: parsePositiveNumber(b.fmin),
    fmax: parsePositiveNumber(b.fmax),
  }));
  const bandsValid = parsedBands.every(
    (b) => b.fmin !== null && b.fmax !== null && b.fmax > b.fmin
  );
  const nyquist = dtNum !== null ? 1 / (2 * dtNum) : null;
  const bandExceedsNyquist =
    nyquist !== null && parsedBands.some((b) => b.fmax !== null && b.fmax > nyquist);
  const canRun = eventList !== '' && dtNum !== null && segNum !== null && bandsValid && !running;

  const updateBand = (index: number, field: 'fmin' | 'fmax', value: string): void => {
    setBands((prev) => prev.map((b, i) => (i === index ? { ...b, [field]: value } : b)));
  };

  const handleRun = (): void => {
    if (!dtNum || !segNum || !bandsValid) return;
    const freq_ranges: Record<string, [number, number]> = {};
    for (const b of parsedBands) {
      freq_ranges[b.label] = [b.fmin as number, b.fmax as number];
    }
    void run(() =>
      timingApi.calculatePowerColors({
        event_list_name: eventList,
        dt: dtNum,
        segment_size: segNum,
        freq_ranges,
      })
    );
  };

  const bandTraces: Data[] = result
    ? Object.entries(result.power_colors).map(([label, values], i) => ({
        x: result.time,
        y: values,
        type: 'scattergl' as const,
        mode: 'lines+markers' as const,
        marker: { size: 4, color: BAND_COLORS[i % BAND_COLORS.length] },
        line: { width: 1, color: BAND_COLORS[i % BAND_COLORS.length] },
        name: label,
      }))
    : [];

  const ratios = result
    ? computePowerColorRatios(
        result.power_colors,
        bands.map((b) => b.label)
      )
    : null;

  const scatterTrace: Data[] = ratios
    ? [
        {
          x: ratios.pc1,
          y: ratios.pc2,
          type: 'scattergl' as const,
          mode: 'markers' as const,
          marker: { size: 6, color: '#00d4aa' },
        },
      ]
    : [];

  return (
    <PageTemplate
      title="Power Colors"
      description="Band-mean Leahy power per segment in four frequency bands, and the PC1–PC2 power-color diagram"
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
                  helperText="Nyquist must cover the highest band"
                />
                <TextField
                  label="Segment size (s)"
                  size="small"
                  value={segmentSize}
                  onChange={(e) => setSegmentSize(e.target.value)}
                  error={segmentSize !== '' && segNum === null}
                  helperText="Must exceed 1/f_min of the lowest band"
                />
                <Typography variant="subtitle2">Frequency bands (Hz)</Typography>
                {bands.map((b, i) => (
                  <Box key={b.label} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Typography sx={{ width: 20, fontFamily: '"JetBrains Mono", monospace' }}>
                      {b.label}
                    </Typography>
                    <TextField
                      size="small"
                      label="f min"
                      value={b.fmin}
                      onChange={(e) => updateBand(i, 'fmin', e.target.value)}
                    />
                    <TextField
                      size="small"
                      label="f max"
                      value={b.fmax}
                      onChange={(e) => updateBand(i, 'fmax', e.target.value)}
                    />
                  </Box>
                ))}
                {!bandsValid && (
                  <Alert severity="warning">Each band needs 0 &lt; f min &lt; f max.</Alert>
                )}
                {bandExceedsNyquist && (
                  <Alert severity="warning">
                    A band&apos;s f max exceeds the Nyquist frequency 1/(2·dt); frequency bins above it are
                    dropped.
                  </Alert>
                )}
                <Button
                  variant="contained"
                  startIcon={
                    running ? (
                      <CircularProgress size={16} color="inherit" />
                    ) : (
                      <PlayArrowIcon />
                    )
                  }
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
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <Stack spacing={3}>
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Band power vs time
                    </Typography>
                    <PlotlyChart
                      data={bandTraces}
                      layout={{
                        showlegend: true,
                        xaxis: { title: { text: 'Time (s)' } },
                        yaxis: { title: { text: 'Mean power (leahy)' }, type: 'log' },
                      }}
                      height={320}
                    />
                  </Box>
                  {ratios && ratios.pc1.length > 0 && (
                    <Box>
                      <Typography variant="subtitle2" gutterBottom>
                        Power-color diagram (PC1 = C/A, PC2 = B/D)
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Ratios use band-mean (not band-integrated) power: PC tracks match literature power
                        colors up to constant per-band factors, so absolute values are not comparable to
                        published hue diagrams.
                      </Typography>
                      <PlotlyChart
                        data={scatterTrace}
                        layout={{
                          xaxis: { title: { text: 'PC1' }, type: 'log' },
                          yaxis: { title: { text: 'PC2' }, type: 'log' },
                        }}
                        height={380}
                      />
                    </Box>
                  )}
                </Stack>
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Compute band powers to populate the power-color diagram.
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

export default PowerColorsPage;
