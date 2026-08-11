import React, { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  CardContent,
  FormControl,
  FormHelperText,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { ProvenancePanel, UtilityWarnings } from '@/components/utilities/UtilityResult';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import {
  gtiApi,
  type GtiBadTimeData,
  type GtiSetOperation,
  type GtiSetOperationData,
  type GtiTimeReference,
} from '@/api/gtiApi';
import {
  finiteNumber,
  formatMetric,
  GtiRowsField,
  type InspectedGtiRows,
  IntervalResult,
  MetricCard,
  parseStrictGtis,
  RunButton,
  RunnerError,
  SET_OPERATION_LABELS,
  TimeReferenceControl,
} from './GtiCommon';

interface SetOperationsPanelProps {
  inspectedRows: InspectedGtiRows | null;
  leftRows: string;
  onLeftRowsChange: (rows: string) => void;
  timeReference: GtiTimeReference;
  onTimeReferenceChange: (reference: GtiTimeReference) => void;
}

const SetOperationsPanel: React.FC<SetOperationsPanelProps> = ({
  inspectedRows,
  leftRows,
  onLeftRowsChange,
  timeReference,
  onTimeReferenceChange,
}) => {
  const [rightRows, setRightRows] = useState('');
  const [operation, setOperation] = useState<GtiSetOperation>('intersection');
  const leftParsed = useMemo(() => parseStrictGtis(leftRows, 'Left GTIs'), [leftRows]);
  const rightParsed = useMemo(() => parseStrictGtis(rightRows, 'Right GTIs'), [rightRows]);
  const setRunner = useAnalysisRunner<GtiSetOperationData>('GTI set operation');
  const [observationStart, setObservationStart] = useState('');
  const [observationStop, setObservationStop] = useState('');
  const startNumber = finiteNumber(observationStart);
  const stopNumber = finiteNumber(observationStop);
  const badRangeError =
    startNumber !== null && stopNumber !== null && stopNumber <= startNumber
      ? 'Observation stop must be greater than observation start'
      : null;
  const badTimeRunner = useAnalysisRunner<GtiBadTimeData>('Generate bad-time intervals');

  const runSetOperation = (): void => {
    if (!leftParsed.rows || !rightParsed.rows) return;
    void setRunner.run(() =>
      gtiApi.setOperation({
        left_gtis: leftParsed.rows as [number, number][],
        right_gtis: rightParsed.rows as [number, number][],
        operation,
        time_reference: timeReference,
      })
    );
  };

  const runBadTimes = (): void => {
    if (!leftParsed.rows || startNumber === null || stopNumber === null || badRangeError) return;
    void badTimeRunner.run(() =>
      gtiApi.badTimeIntervals({
        gtis: leftParsed.rows as [number, number][],
        start_time: startNumber,
        stop_time: stopNumber,
        time_reference: timeReference,
      })
    );
  };

  const useInspectedRows = (): void => {
    if (!inspectedRows) return;
    onLeftRowsChange(inspectedRows.rows);
    onTimeReferenceChange('absolute_mission_time');
  };

  return (
    <Stack spacing={3}>
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <GtiRowsField
            label="Left / good GTIs"
            value={leftRows}
            onChange={onLeftRowsChange}
            error={leftParsed.error}
            disabled={setRunner.running || badTimeRunner.running}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <GtiRowsField
            label="Right GTIs"
            value={rightRows}
            onChange={setRightRows}
            error={rightParsed.error}
            disabled={setRunner.running}
          />
        </Grid>
      </Grid>
      {inspectedRows ? (
        <Button size="small" onClick={useInspectedRows}>
          Use inspected GTIs from {inspectedRows.sourceName} as the left/good set
        </Button>
      ) : null}
      <Card variant="outlined">
        <CardContent>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={12} md={7}>
              <FormControl size="small" fullWidth>
                <InputLabel id="gti-set-operation-label">Set operation</InputLabel>
                <Select
                  labelId="gti-set-operation-label"
                  label="Set operation"
                  value={operation}
                  onChange={(event) => setOperation(event.target.value as GtiSetOperation)}
                  disabled={setRunner.running}
                >
                  {Object.entries(SET_OPERATION_LABELS).map(([value, label]) => (
                    <MenuItem key={value} value={value}>
                      {label}
                    </MenuItem>
                  ))}
                </Select>
                <FormHelperText>
                  {operation === 'intersection'
                    ? 'Returns only time accepted by both sets.'
                    : operation === 'union'
                      ? 'Coalesces overlapping and touching intervals explicitly.'
                      : 'Requires mutually exclusive inputs; use union for overlaps.'}
                </FormHelperText>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={5}>
              <RunButton
                label="Compute set result"
                running={setRunner.running}
                disabled={!leftParsed.rows || !rightParsed.rows}
                onClick={runSetOperation}
              />
            </Grid>
            <Grid item xs={12}>
              <TimeReferenceControl
                value={timeReference}
                onChange={onTimeReferenceChange}
                disabled={setRunner.running || badTimeRunner.running}
              />
            </Grid>
          </Grid>
        </CardContent>
      </Card>
      <RunnerError error={setRunner.error} warnings={setRunner.warnings} />
      {setRunner.result ? (
        <Stack spacing={2}>
          <Alert severity="info">Merge strategy: {setRunner.result.merge_strategy}</Alert>
          <UtilityWarnings warnings={setRunner.result.warnings} />
          <IntervalResult
            title={`${SET_OPERATION_LABELS[setRunner.result.operation]} result`}
            payload={setRunner.result}
            timeReference={setRunner.result.time_reference}
          />
          <ProvenancePanel provenance={setRunner.result.provenance} />
        </Stack>
      ) : null}

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6">Bad-time interval complement</Typography>
            <Typography variant="body2" color="text.secondary">
              Treat the left rows as good time and return every gap inside an explicit observation
              range.
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Observation start (s)"
                  value={observationStart}
                  onChange={(event) => setObservationStart(event.target.value)}
                  error={observationStart !== '' && startNumber === null}
                  helperText={observationStart !== '' && startNumber === null ? 'Must be finite' : ' '}
                />
              </Grid>
              <Grid item xs={12} sm={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Observation stop (s)"
                  value={observationStop}
                  onChange={(event) => setObservationStop(event.target.value)}
                  error={observationStop !== '' && (stopNumber === null || !!badRangeError)}
                  helperText={
                    observationStop !== '' && stopNumber === null
                      ? 'Must be finite'
                      : badRangeError ?? ' '
                  }
                />
              </Grid>
              <Grid item xs={12} sm={4}>
                <RunButton
                  label="Generate BTIs"
                  running={badTimeRunner.running}
                  disabled={
                    !leftParsed.rows ||
                    startNumber === null ||
                    stopNumber === null ||
                    !!badRangeError
                  }
                  onClick={runBadTimes}
                />
              </Grid>
            </Grid>
          </Stack>
        </CardContent>
      </Card>
      <RunnerError error={badTimeRunner.error} warnings={badTimeRunner.warnings} />
      {badTimeRunner.result ? (
        <Stack spacing={2}>
          <Grid container spacing={1.5}>
            <Grid item xs={6}>
              <MetricCard
                label="Good exposure"
                value={formatMetric(badTimeRunner.result.good_exposure_s, ' s')}
              />
            </Grid>
            <Grid item xs={6}>
              <MetricCard
                label="Bad exposure"
                value={formatMetric(badTimeRunner.result.bad_exposure_s, ' s')}
              />
            </Grid>
          </Grid>
          <UtilityWarnings warnings={badTimeRunner.result.warnings} />
          <IntervalResult
            title="Bad-time intervals"
            payload={badTimeRunner.result}
            timeReference={badTimeRunner.result.time_reference}
          />
          <ProvenancePanel provenance={badTimeRunner.result.provenance} />
        </Stack>
      ) : null}
    </Stack>
  );
};

export default SetOperationsPanel;
