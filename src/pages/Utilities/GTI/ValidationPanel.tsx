import React, { useMemo, useState } from 'react';
import { Alert, Button, Card, CardContent, Grid, Stack, Typography } from '@mui/material';
import { ProvenancePanel, UtilityWarnings } from '@/components/utilities/UtilityResult';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { gtiApi, type GtiTimeReference, type GtiValidationData } from '@/api/gtiApi';
import {
  GtiRowsField,
  type InspectedGtiRows,
  IntervalResult,
  parseStrictGtis,
  RunButton,
  RunnerError,
  TimeReferenceControl,
} from './GtiCommon';

interface ValidationPanelProps {
  inspectedRows: InspectedGtiRows | null;
  onUseValidatedRows: (rows: string, reference: GtiTimeReference) => void;
}

const ValidationPanel: React.FC<ValidationPanelProps> = ({
  inspectedRows,
  onUseValidatedRows,
}) => {
  const [rows, setRows] = useState('');
  const [timeReference, setTimeReference] =
    useState<GtiTimeReference>('absolute_mission_time');
  const [validatedSignature, setValidatedSignature] = useState<string | null>(null);
  const parsed = useMemo(() => parseStrictGtis(rows), [rows]);
  const runner = useAnalysisRunner<GtiValidationData>('Validate GTIs');
  const signature = `${timeReference}\u0000${rows}`;
  const resultIsCurrent = validatedSignature === signature;

  const runValidation = (): void => {
    if (!parsed.rows) return;
    const requestSignature = signature;
    void runner.run(async () => {
      const response = await gtiApi.validate({
        gtis: parsed.rows as [number, number][],
        time_reference: timeReference,
      });
      if (response.success) setValidatedSignature(requestSignature);
      return response;
    });
  };

  const useInspectedRows = (): void => {
    if (!inspectedRows) return;
    setRows(inspectedRows.rows);
    setTimeReference('absolute_mission_time');
  };

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={5}>
        <Card variant="outlined">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h6">Manual GTI rows</Typography>
              <Typography variant="body2" color="text.secondary">
                Paste or edit ordered start/stop pairs. Validation never silently sorts, merges,
                or changes an interval.
              </Typography>
              <GtiRowsField
                label="Manual GTIs"
                value={rows}
                onChange={setRows}
                error={parsed.error}
                editableRows
                disabled={runner.running}
              />
              {inspectedRows ? (
                <Button size="small" onClick={useInspectedRows}>
                  Use inspected effective GTIs from {inspectedRows.sourceName}
                </Button>
              ) : null}
              <TimeReferenceControl
                value={timeReference}
                onChange={setTimeReference}
                disabled={runner.running}
              />
              <RunButton
                label="Validate rows"
                running={runner.running}
                disabled={!parsed.rows}
                onClick={runValidation}
              />
            </Stack>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={7}>
        <Stack spacing={2}>
          <RunnerError error={runner.error} warnings={runner.warnings} />
          {runner.result ? (
            <>
              {!resultIsCurrent ? (
                <Alert severity="warning">
                  These validation results belong to the previous row content or time reference.
                  Validate again before reusing the rows.
                </Alert>
              ) : (
                <Alert severity="success">
                  All rows are finite, ordered, positive in length, and non-overlapping.
                </Alert>
              )}
              <UtilityWarnings warnings={runner.result.warnings} />
              <IntervalResult
                title="Validated GTIs"
                payload={runner.result}
                timeReference={runner.result.time_reference}
              />
              <Button
                variant="outlined"
                disabled={!resultIsCurrent}
                onClick={() => onUseValidatedRows(rows, timeReference)}
              >
                Use validated rows in compatible tools
              </Button>
              {resultIsCurrent && timeReference === 'relative_seconds' ? (
                <Alert severity="info">
                  Relative rows are copied to set operations and segmentation, but not to the
                  absolute-mission-time EventList mask.
                </Alert>
              ) : null}
              <ProvenancePanel provenance={runner.result.provenance} />
            </>
          ) : (
            <Alert severity="info">Enter rows and run the explicit validation step.</Alert>
          )}
        </Stack>
      </Grid>
    </Grid>
  );
};

export default ValidationPanel;
