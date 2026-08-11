import React, { useCallback, useState } from 'react';
import { Alert, Grid, Stack } from '@mui/material';
import EventListSelector from '@/components/analysis/EventListSelector';
import { ProvenancePanel, UtilityWarnings } from '@/components/utilities/UtilityResult';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { gtiApi, type GtiInspectionData } from '@/api/gtiApi';
import {
  formatMetric,
  type InspectedGtiRows,
  IntervalResult,
  MetricCard,
  rowsToText,
  RunButton,
  RunnerError,
} from './GtiCommon';

interface InspectionPanelProps {
  onInspectedRowsChange: (rows: InspectedGtiRows | null) => void;
}

const InspectionPanel: React.FC<InspectionPanelProps> = ({ onInspectedRowsChange }) => {
  const [eventListName, setEventListName] = useState('');
  const runner = useAnalysisRunner<GtiInspectionData>('Inspect GTIs');
  const onEventListChange = useCallback((name: string) => {
    runner.reset();
    onInspectedRowsChange(null);
    setEventListName(name);
  }, [onInspectedRowsChange, runner]);

  const runInspection = (): void => {
    if (eventListName === '') return;
    const sourceName = eventListName;
    void runner.run(async () => {
      const response = await gtiApi.inspect({ event_list_name: sourceName });
      if (response.success && response.data) {
        onInspectedRowsChange({
          rows: rowsToText(response.data.intervals),
          sourceName,
        });
      }
      return response;
    });
  };
  const result = runner.result?.event_list_name === eventListName ? runner.result : null;

  return (
    <Stack spacing={2.5}>
      <Alert severity="info">
        Inspection reports the EventList&apos;s effective <code>.gti</code> exactly as stored. It
        does not infer good time from the first and last event, and mission-clock seconds must be
        interpreted with MJDREF.
      </Alert>
      <Grid container spacing={2} alignItems="flex-start">
        <Grid item xs={12} md={8}>
          <EventListSelector
            label="Event list to inspect"
            value={eventListName}
            onChange={onEventListChange}
            disabled={runner.running}
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <RunButton
            label="Inspect effective GTIs"
            running={runner.running}
            disabled={eventListName === ''}
            onClick={runInspection}
          />
        </Grid>
      </Grid>
      <RunnerError error={runner.error} warnings={runner.warnings} />
      {result ? (
        <Stack spacing={2}>
          <UtilityWarnings warnings={result.warnings} />
          {result.gti_status !== 'available' ? (
            <Alert severity={result.gti_status === 'missing' ? 'warning' : 'info'}>
              Effective GTI status: {result.gti_status}. No synthetic interval was
              substituted.
            </Alert>
          ) : null}
          <Grid container spacing={1.5}>
            <Grid item xs={6} md={3}>
              <MetricCard label="Events" value={result.event_count.toLocaleString()} />
            </Grid>
            <Grid item xs={6} md={3}>
              <MetricCard label="MJDREF" value={formatMetric(result.mjdref)} />
            </Grid>
          </Grid>
          <IntervalResult
            title="Effective GTIs"
            payload={result}
            timeReference={result.time_reference}
          />
          <ProvenancePanel provenance={result.provenance} />
        </Stack>
      ) : (
        <Alert severity="info">Select a loaded EventList to inspect its effective GTIs.</Alert>
      )}
    </Stack>
  );
};

export default InspectionPanel;
