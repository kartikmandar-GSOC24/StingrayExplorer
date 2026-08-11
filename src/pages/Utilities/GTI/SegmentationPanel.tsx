import React, { useMemo, useState } from 'react';
import { Alert, Button, Card, CardContent, Grid, Paper, Stack, TextField, Typography } from '@mui/material';
import PlotlyChart from '@/components/plots/PlotlyChart';
import {
  NumericResultTable,
  ProvenancePanel,
  UtilityWarnings,
} from '@/components/utilities/UtilityResult';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import {
  gtiApi,
  type GtiExposureSegmentsData,
  type GtiFixedSegmentsData,
  type GtiIntervalPayload,
  type GtiTimeReference,
} from '@/api/gtiApi';
import {
  formatMetric,
  GtiRowsField,
  type InspectedGtiRows,
  intervalTrace,
  IntervalResult,
  MetricCard,
  parseStrictGtis,
  positiveNumber,
  RunButton,
  RunnerError,
  TIME_REFERENCE_LABELS,
  TimeReferenceControl,
} from './GtiCommon';

interface SegmentationPanelProps {
  inspectedRows: InspectedGtiRows | null;
  rows: string;
  onRowsChange: (rows: string) => void;
  timeReference: GtiTimeReference;
  onTimeReferenceChange: (reference: GtiTimeReference) => void;
}

const SegmentationPanel: React.FC<SegmentationPanelProps> = ({
  inspectedRows,
  rows,
  onRowsChange,
  timeReference,
  onTimeReferenceChange,
}) => {
  const parsed = useMemo(() => parseStrictGtis(rows, 'Segment GTIs'), [rows]);
  const [fixedSize, setFixedSize] = useState('');
  const fixedSizeNumber = positiveNumber(fixedSize);
  const fixedMeaningError = useMemo(() => {
    if (fixedSizeNumber === null || !parsed.rows) return null;
    const hasUsableInterval = parsed.rows.some(
      ([start, stop]) => stop - start >= fixedSizeNumber
    );
    return hasUsableInterval ? null : 'Segment size exceeds every GTI length';
  }, [fixedSizeNumber, parsed.rows]);
  const fixedRunner = useAnalysisRunner<GtiFixedSegmentsData>('Generate fixed segments');
  const [exposurePerChunk, setExposurePerChunk] = useState('');
  const [separationThreshold, setSeparationThreshold] = useState('');
  const exposureNumber = positiveNumber(exposurePerChunk);
  const separationNumber =
    separationThreshold.trim() === '' ? undefined : positiveNumber(separationThreshold);
  const exposureRunner = useAnalysisRunner<GtiExposureSegmentsData>('Split GTIs by exposure');

  const runFixedSegments = (): void => {
    if (!parsed.rows || fixedSizeNumber === null || fixedMeaningError) return;
    void fixedRunner.run(() =>
      gtiApi.fixedSegments({
        gtis: parsed.rows as [number, number][],
        segment_size: fixedSizeNumber,
        time_reference: timeReference,
      })
    );
  };

  const runExposureSegments = (): void => {
    if (
      !parsed.rows ||
      exposureNumber === null ||
      (separationThreshold.trim() !== '' && separationNumber === null)
    ) {
      return;
    }
    void exposureRunner.run(() =>
      gtiApi.exposureSegments({
        gtis: parsed.rows as [number, number][],
        exposure_per_chunk: exposureNumber,
        time_reference: timeReference,
        ...(typeof separationNumber === 'number'
          ? { new_interval_if_gti_sep: separationNumber }
          : {}),
      })
    );
  };

  const exposureRows = useMemo(
    () =>
      exposureRunner.result
        ? exposureRunner.result.chunks.flatMap((chunk) =>
            chunk.intervals.map((interval) => ({
              chunk: chunk.chunk_index,
              interval: interval.index,
              start: interval.start,
              stop: interval.stop,
              length_s: interval.length_s,
            }))
          )
        : [],
    [exposureRunner.result]
  );
  const exposurePlotPayload: GtiIntervalPayload | null = exposureRunner.result
    ? {
        intervals: [],
        interval_count: exposureRunner.result.interval_count,
        lengths_s: [],
        separations_s: [],
        total_exposure_s: exposureRunner.result.output_exposure_s,
        overall_time_span_s: 0,
        duty_cycle: null,
        plot: {
          starts: exposureRunner.result.plot.starts,
          stops: exposureRunner.result.plot.stops,
          interval_indices: exposureRunner.result.plot.chunk_indices,
          stride: exposureRunner.result.plot.stride,
          source_points: exposureRunner.result.plot.source_points,
        },
      }
    : null;

  const useInspectedRows = (): void => {
    if (!inspectedRows) return;
    onRowsChange(inspectedRows.rows);
    onTimeReferenceChange('absolute_mission_time');
  };

  return (
    <Stack spacing={3}>
      <GtiRowsField
        label="GTIs to segment"
        value={rows}
        onChange={onRowsChange}
        error={parsed.error}
        disabled={fixedRunner.running || exposureRunner.running}
      />
      {inspectedRows ? (
        <Button size="small" onClick={useInspectedRows}>
          Use inspected effective GTIs from {inspectedRows.sourceName}
        </Button>
      ) : null}
      <TimeReferenceControl
        value={timeReference}
        onChange={onTimeReferenceChange}
        disabled={fixedRunner.running || exposureRunner.running}
      />
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">Fixed-duration intervals</Typography>
                <Typography variant="body2" color="text.secondary">
                  Generates only complete, non-overlapping segments fully contained in good time.
                  Short remainders are reported and omitted.
                </Typography>
                <TextField
                  fullWidth
                  size="small"
                  label="Segment size (s)"
                  value={fixedSize}
                  onChange={(event) => setFixedSize(event.target.value)}
                  error={fixedSize !== '' && (fixedSizeNumber === null || !!fixedMeaningError)}
                  helperText={
                    fixedSize !== '' && fixedSizeNumber === null
                      ? 'Must be a positive finite number'
                      : fixedMeaningError ?? ' '
                  }
                />
                <RunButton
                  label="Generate fixed segments"
                  running={fixedRunner.running}
                  disabled={!parsed.rows || fixedSizeNumber === null || !!fixedMeaningError}
                  onClick={runFixedSegments}
                />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">Approximate-exposure chunks</Typography>
                <Typography variant="body2" color="text.secondary">
                  Splits GTIs into chunk groups near the requested exposure while preserving GTI
                  boundaries. Chunk exposure is approximate, not guaranteed exact.
                </Typography>
                <TextField
                  fullWidth
                  size="small"
                  label="Exposure per chunk (s)"
                  value={exposurePerChunk}
                  onChange={(event) => setExposurePerChunk(event.target.value)}
                  error={exposurePerChunk !== '' && exposureNumber === null}
                  helperText={
                    exposurePerChunk !== '' && exposureNumber === null
                      ? 'Must be a positive finite number'
                      : ' '
                  }
                />
                <TextField
                  fullWidth
                  size="small"
                  label="Start new chunk when GTI gap exceeds (s)"
                  value={separationThreshold}
                  onChange={(event) => setSeparationThreshold(event.target.value)}
                  error={separationThreshold !== '' && separationNumber === null}
                  helperText={
                    separationThreshold !== '' && separationNumber === null
                      ? 'Must be a positive finite number or blank'
                      : 'Optional; blank leaves Stingray grouping unchanged.'
                  }
                />
                <RunButton
                  label="Split by exposure"
                  running={exposureRunner.running}
                  disabled={
                    !parsed.rows ||
                    exposureNumber === null ||
                    (separationThreshold.trim() !== '' && separationNumber === null)
                  }
                  onClick={runExposureSegments}
                />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <RunnerError error={fixedRunner.error} warnings={fixedRunner.warnings} />
      {fixedRunner.result ? (
        <Stack spacing={2}>
          <UtilityWarnings warnings={fixedRunner.result.warnings} />
          <Grid container spacing={1.5}>
            <Grid item xs={6} md={3}>
              <MetricCard
                label="Segment size"
                value={formatMetric(fixedRunner.result.segment_size_s, ' s')}
              />
            </Grid>
            <Grid item xs={6} md={3}>
              <MetricCard
                label="Unused remainder"
                value={formatMetric(fixedRunner.result.unused_exposure_s, ' s')}
              />
            </Grid>
          </Grid>
          <IntervalResult
            title="Fixed segments"
            payload={fixedRunner.result}
            timeReference={fixedRunner.result.time_reference}
          />
          <ProvenancePanel provenance={fixedRunner.result.provenance} />
        </Stack>
      ) : null}
      <RunnerError error={exposureRunner.error} warnings={exposureRunner.warnings} />
      {exposureRunner.result && exposurePlotPayload ? (
        <Stack spacing={2}>
          <Alert severity="info">
            Time reference: {TIME_REFERENCE_LABELS[exposureRunner.result.time_reference]}. Values
            are reported in seconds without renderer-side shifting.
          </Alert>
          <UtilityWarnings warnings={exposureRunner.result.warnings} />
          <Grid container spacing={1.5}>
            <Grid item xs={6} md={3}>
              <MetricCard
                label="Chunks"
                value={exposureRunner.result.chunk_count.toLocaleString()}
              />
            </Grid>
            <Grid item xs={6} md={3}>
              <MetricCard
                label="Output exposure"
                value={formatMetric(exposureRunner.result.output_exposure_s, ' s')}
              />
            </Grid>
          </Grid>
          <NumericResultTable
            title="Exposure chunks — exact intervals"
            columns={[
              { key: 'chunk', label: 'Chunk' },
              { key: 'interval', label: 'Interval in chunk' },
              { key: 'start', label: 'Start', unit: 's' },
              { key: 'stop', label: 'Stop', unit: 's' },
              { key: 'length_s', label: 'Length', unit: 's' },
            ]}
            rows={exposureRows}
          />
          <Paper variant="outlined" sx={{ p: 1 }}>
            <Typography variant="subtitle2" sx={{ px: 1, pt: 0.5 }}>
              Exposure chunks — bounded plot preview
            </Typography>
            <PlotlyChart
              data={intervalTrace(exposurePlotPayload, 'Exposure chunks')}
              height={320}
              layout={{
                xaxis: { title: { text: 'Mission/relative time (s)' } },
                yaxis: { title: { text: 'Chunk index' }, autorange: 'reversed' },
                bargap: 0.35,
              }}
            />
          </Paper>
          <ProvenancePanel provenance={exposureRunner.result.provenance} />
        </Stack>
      ) : null}
      {!fixedRunner.result && !exposureRunner.result ? (
        <Alert severity="info">Enter valid rows and choose a segmentation method.</Alert>
      ) : null}
    </Stack>
  );
};

export default SegmentationPanel;
