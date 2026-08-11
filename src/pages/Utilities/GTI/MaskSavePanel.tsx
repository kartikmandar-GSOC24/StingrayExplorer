import React, { useCallback, useMemo, useState } from 'react';
import { Alert, Button, Card, CardContent, Grid, Paper, Stack, TextField, Typography } from '@mui/material';
import type { Data } from 'plotly.js';
import { useQueryClient } from '@tanstack/react-query';
import EventListSelector from '@/components/analysis/EventListSelector';
import PlotlyChart from '@/components/plots/PlotlyChart';
import {
  NumericResultTable,
  ProvenancePanel,
  UtilityWarnings,
} from '@/components/utilities/UtilityResult';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { EVENT_LISTS_QUERY_KEY, useEventLists } from '@/hooks/useEventLists';
import { gtiApi, type GtiMaskPreviewData, type GtiMaskSaveData } from '@/api/gtiApi';
import { validateDerivedName } from '@/utils/utilityInputs';
import {
  formatMetric,
  GtiRowsField,
  type InspectedGtiRows,
  IntervalResult,
  MetricCard,
  parseStrictGtis,
  RunButton,
  RunnerError,
} from './GtiCommon';

interface MaskSavePanelProps {
  inspectedRows: InspectedGtiRows | null;
  rows: string;
  onRowsChange: (rows: string) => void;
}

const MaskSavePanel: React.FC<MaskSavePanelProps> = ({ inspectedRows, rows, onRowsChange }) => {
  const queryClient = useQueryClient();
  const { data: eventLists } = useEventLists();
  const [eventListName, setEventListName] = useState('');
  const [destinationName, setDestinationName] = useState('');
  const [previewedSignature, setPreviewedSignature] = useState<string | null>(null);
  const parsed = useMemo(() => parseStrictGtis(rows, 'Mask GTIs'), [rows]);
  const signature = `${eventListName}\u0000${rows}`;
  const previewRunner = useAnalysisRunner<GtiMaskPreviewData>('Preview GTI mask');
  const saveRunner = useAnalysisRunner<GtiMaskSaveData>('Save filtered EventList');
  const onEventListChange = useCallback((name: string) => setEventListName(name), []);
  const destinationValidationError =
    destinationName === '' ? null : validateDerivedName(destinationName);
  const duplicateName =
    destinationName !== '' &&
    (eventLists ?? []).some((eventList) => eventList.name === destinationName);
  const previewIsCurrent = previewedSignature === signature;
  const inspectedRowsMatchSource =
    inspectedRows !== null && inspectedRows.sourceName === eventListName;

  const runPreview = (): void => {
    if (eventListName === '' || !parsed.rows) return;
    const requestSignature = signature;
    void previewRunner.run(async () => {
      const response = await gtiApi.previewMask({
        event_list_name: eventListName,
        gtis: parsed.rows as [number, number][],
      });
      if (response.success) setPreviewedSignature(requestSignature);
      return response;
    });
  };

  const runSave = (): void => {
    if (
      eventListName === '' ||
      !parsed.rows ||
      destinationName === '' ||
      destinationValidationError ||
      duplicateName ||
      !previewIsCurrent
    ) {
      return;
    }
    void saveRunner.run(async () => {
      const response = await gtiApi.saveMask({
        event_list_name: eventListName,
        gtis: parsed.rows as [number, number][],
        destination_name: destinationName,
      });
      if (response.success) {
        await queryClient.invalidateQueries({ queryKey: EVENT_LISTS_QUERY_KEY });
      }
      return response;
    });
  };

  const maskRowsForTable = useMemo(
    () =>
      previewRunner.result
        ? previewRunner.result.mask_preview.time.map((time, index) => ({
            index: index + 1,
            time,
            retained: previewRunner.result?.mask_preview.retained[index] ?? false,
          }))
        : [],
    [previewRunner.result]
  );

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={5}>
        <Card variant="outlined">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h6">Non-destructive GTI filter</Typography>
              <Alert severity="info">
                Requested rows are intersected with the source EventList&apos;s effective GTIs.
                Mask rows are always absolute mission-clock seconds. Preview is read-only; Save as
                creates a new EventList and never alters the source.
              </Alert>
              <EventListSelector
                label="Source event list"
                value={eventListName}
                onChange={onEventListChange}
              />
              <GtiRowsField
                label="Requested mask GTIs"
                value={rows}
                onChange={onRowsChange}
                error={parsed.error}
                disabled={previewRunner.running || saveRunner.running}
              />
              {inspectedRows ? (
                <Button
                  size="small"
                  disabled={!inspectedRowsMatchSource}
                  onClick={() => onRowsChange(inspectedRows.rows)}
                >
                  Use inspected effective GTIs from {inspectedRows.sourceName}
                </Button>
              ) : null}
              {inspectedRows && eventListName !== '' && !inspectedRowsMatchSource ? (
                <Alert severity="warning">
                  Those inspected GTIs belong to {inspectedRows.sourceName}, not {eventListName}.
                  Inspect {eventListName} before applying its effective GTIs.
                </Alert>
              ) : null}
              <RunButton
                label="Preview mask"
                running={previewRunner.running}
                disabled={eventListName === '' || !parsed.rows || saveRunner.running}
                onClick={runPreview}
              />
              <TextField
                fullWidth
                size="small"
                label="Save as EventList name"
                value={destinationName}
                onChange={(event) => setDestinationName(event.target.value)}
                disabled={saveRunner.running}
                error={!!destinationValidationError || duplicateName}
                helperText={
                  duplicateName
                    ? 'An EventList with this name already exists'
                    : destinationValidationError ??
                      'A unique name is required; the source is never overwritten.'
                }
              />
              {!previewIsCurrent && previewRunner.result ? (
                <Alert severity="warning">
                  Source or GTI rows changed after preview. Preview again before saving.
                </Alert>
              ) : null}
              <RunButton
                label="Save as new EventList"
                running={saveRunner.running}
                disabled={
                  !previewRunner.result ||
                  !previewIsCurrent ||
                  destinationName === '' ||
                  !!destinationValidationError ||
                  duplicateName ||
                  previewRunner.running
                }
                onClick={runSave}
                save
              />
              <RunnerError error={saveRunner.error} warnings={saveRunner.warnings} />
              {saveRunner.result ? (
                <Stack spacing={1}>
                  <Alert severity="success">
                    Saved {saveRunner.result.retained_event_count.toLocaleString()} events as{' '}
                    <strong>{saveRunner.result.destination_name}</strong>.
                  </Alert>
                  <Typography variant="caption" color="text.secondary">
                    Time basis: {saveRunner.result.time_reference.replace(/_/g, ' ')} ({saveRunner.result.time_unit}).
                  </Typography>
                  <UtilityWarnings warnings={saveRunner.result.warnings} />
                  <ProvenancePanel provenance={saveRunner.result.provenance} />
                </Stack>
              ) : null}
            </Stack>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={7}>
        <Stack spacing={2}>
          <RunnerError error={previewRunner.error} warnings={previewRunner.warnings} />
          {previewRunner.result ? (
            <>
              <UtilityWarnings warnings={previewRunner.result.warnings} />
              <Grid container spacing={1.5}>
                <Grid item xs={6} md={3}>
                  <MetricCard
                    label="Source events"
                    value={previewRunner.result.source_event_count.toLocaleString()}
                  />
                </Grid>
                <Grid item xs={6} md={3}>
                  <MetricCard
                    label="Retained"
                    value={previewRunner.result.retained_event_count.toLocaleString()}
                  />
                </Grid>
                <Grid item xs={6} md={3}>
                  <MetricCard
                    label="Rejected"
                    value={previewRunner.result.rejected_event_count.toLocaleString()}
                  />
                </Grid>
                <Grid item xs={6} md={3}>
                  <MetricCard
                    label="Retained exposure"
                    value={formatMetric(previewRunner.result.retained_exposure_s, ' s')}
                  />
                </Grid>
              </Grid>
              {previewRunner.result.mask_preview.truncated ? (
                <Alert severity="warning">
                  Exact mask table is capped at{' '}
                  {previewRunner.result.mask_preview.shown.toLocaleString()} of{' '}
                  {previewRunner.result.mask_preview.total.toLocaleString()} events.
                </Alert>
              ) : null}
              <NumericResultTable
                title="Exact mask preview"
                columns={[
                  { key: 'index', label: 'Event' },
                  { key: 'time', label: 'Time', unit: 's' },
                  { key: 'retained', label: 'Retained' },
                ]}
                rows={maskRowsForTable}
              />
              <Paper variant="outlined" sx={{ p: 1 }}>
                <Typography variant="subtitle2" sx={{ px: 1, pt: 0.5 }}>
                  Bounded event-mask plot preview
                </Typography>
                <PlotlyChart
                  height={300}
                  data={[
                    {
                      type: 'scattergl',
                      mode: 'markers',
                      x: previewRunner.result.plot.time,
                      y: previewRunner.result.plot.retained.map((value) => (value ? 1 : 0)),
                      marker: {
                        size: 6,
                        color: previewRunner.result.plot.retained.map((value) =>
                          value ? '#00a98f' : '#d05a6e'
                        ),
                      },
                      hovertemplate: 'time=%{x:.12g}s<br>retained=%{y}<extra></extra>',
                    } as Data,
                  ]}
                  layout={{
                    xaxis: { title: { text: 'Mission time (s)' } },
                    yaxis: {
                      title: { text: 'Mask' },
                      tickmode: 'array',
                      tickvals: [0, 1],
                      ticktext: ['Rejected', 'Retained'],
                      range: [-0.25, 1.25],
                    },
                  }}
                />
              </Paper>
              <IntervalResult
                title="Applied effective GTIs"
                payload={previewRunner.result.applied_gtis}
                timeReference="absolute_mission_time"
              />
              <ProvenancePanel provenance={previewRunner.result.provenance} />
            </>
          ) : (
            <Alert severity="info">Choose a source and valid rows, then preview the mask.</Alert>
          )}
        </Stack>
      </Grid>
    </Grid>
  );
};

export default MaskSavePanel;
