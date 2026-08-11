import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from '@mui/material';
import PreviewIcon from '@mui/icons-material/Preview';
import GrantedFileField, {
  type GrantedFileSelection,
} from '@/components/utilities/GrantedFileField';
import {
  NumericResultTable,
  ProvenancePanel,
} from '@/components/utilities/UtilityResult';
import {
  missionIoApi,
  type InterpretMissionParams,
  type MissionInterpretationData,
} from '@/api/missionIoApi';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import {
  MissionFieldCards,
  mergeWarnings,
  hasOverrideErrors,
  OptionalOverrides,
  ResultFeedback,
  ResultSection,
  optionalText,
  type OverrideValues,
} from './MissionCommon';
import { CAPABILITIES_QUERY_KEY, loadCapabilities } from './MissionDatabasePanel';

const EMPTY_OVERRIDES: OverrideValues = { mission: '', instrument: '', mode: '' };

const InterpretationPanel: React.FC = () => {
  const capabilities = useQuery({
    queryKey: CAPABILITIES_QUERY_KEY,
    queryFn: loadCapabilities,
    staleTime: 60_000,
  });
  const [fitsFile, setFitsFile] = React.useState<GrantedFileSelection | null>(null);
  const [overrides, setOverrides] = React.useState<OverrideValues>(EMPTY_OVERRIDES);
  const {
    result: runnerResult,
    running,
    error,
    warnings,
    run,
  } = useAnalysisRunner<MissionInterpretationData>('Mission-specific FITS interpretation');
  const [resultSignature, setResultSignature] = React.useState<string | null>(null);
  const [requestSignature, setRequestSignature] = React.useState<string | null>(null);
  const inputSignature = JSON.stringify({ fitsFile, overrides });
  const result = resultSignature === inputSignature ? runnerResult : null;
  const feedbackIsCurrent = requestSignature === inputSignature;
  const overridesInvalid = hasOverrideErrors(overrides);

  const interpret = (): void => {
    if (!fitsFile || overridesInvalid) return;
    const params: InterpretMissionParams = {
      file_path: fitsFile.path,
      file_grant: fitsFile.grant,
    };
    const mission = optionalText(overrides.mission);
    const instrument = optionalText(overrides.instrument);
    const mode = optionalText(overrides.mode);
    if (mission) params.mission_override = mission;
    if (instrument) params.instrument_override = instrument;
    if (mode) params.mode_override = mode;
    const submittedSignature = inputSignature;
    setRequestSignature(submittedSignature);
    void run(async () => {
      const response = await missionIoApi.interpret(params);
      if (response.success && response.data) setResultSignature(submittedSignature);
      return response;
    });
  };

  const supported = capabilities.data?.missions.filter(
    (row) => row.specialized_interpretation.supported
  );

  return (
    <Stack spacing={2.5}>
      <Alert severity="info">
        Specialized interpretation is exposed only where the installed public Stingray API has an
        interpreter. It decodes mission-specific event channels; it does not calibrate energy.
      </Alert>

      {capabilities.isLoading ? (
        <Stack direction="row" spacing={1} alignItems="center">
          <CircularProgress size={18} />
          <Typography variant="body2">Checking runtime interpreter support…</Typography>
        </Stack>
      ) : capabilities.isError ? (
        <Alert severity="error">Could not load runtime interpreter capabilities.</Alert>
      ) : (
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          {(supported ?? []).length > 0 ? (
            supported?.map((row) => (
              <Chip
                key={row.mission}
                color="success"
                label={`${row.mission}: ${row.specialized_interpretation.scope ?? 'supported'}`}
              />
            ))
          ) : (
            <Chip label="No specialized interpreters reported by this runtime" />
          )}
        </Stack>
      )}

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6">Read-only FITS interpretation</Typography>
            <Typography variant="body2" color="text.secondary">
              The backend operates on a bounded in-memory copy. The selected FITS file is never
              changed.
            </Typography>
            <GrantedFileField
              label="FITS file to interpret"
              value={fitsFile}
              onChange={setFitsFile}
              disabled={running}
            />
            <OptionalOverrides values={overrides} onChange={setOverrides} disabled={running} />
            <Button
              variant="contained"
              startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PreviewIcon />}
              disabled={fitsFile === null || overridesInvalid || running}
              onClick={interpret}
            >
              {running ? 'Interpreting…' : 'Interpret selected FITS'}
            </Button>
          </Stack>
        </CardContent>
      </Card>

      <ResultFeedback
        error={feedbackIsCurrent ? error : null}
        warnings={feedbackIsCurrent ? mergeWarnings(warnings, result?.warnings) : []}
      />
      {result ? (
        <ResultSection title={result.label}>
          <Alert severity="success">
            Read-only result: the source file was not modified.
          </Alert>
          <MissionFieldCards
            mission={result.mission}
            instrument={result.instrument}
            mode={result.mode}
          />
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip label={`HDU: ${result.hdu}`} />
            <Chip label={`${result.event_count.toLocaleString()} events`} />
            <Chip label={`${result.changed_count.toLocaleString()} channels changed`} />
            <Chip color="info" label={result.supported_scope} />
          </Stack>
          <NumericResultTable
            title="Interpreted PHA preview"
            columns={[
              { key: 'index', label: 'Index' },
              { key: 'original_pha', label: 'Original PHA' },
              { key: 'interpreted_pha', label: 'Interpreted PHA' },
              { key: 'changed', label: 'Changed' },
            ]}
            rows={result.rows}
          />
          {result.preview_truncated ? (
            <Alert severity="info">
              Showing {result.preview_count.toLocaleString()} of{' '}
              {result.event_count.toLocaleString()} rows.
            </Alert>
          ) : null}
          <ProvenancePanel provenance={result.provenance} />
        </ResultSection>
      ) : runnerResult ? (
        <Alert severity="warning">
          Interpretation inputs changed. Run interpretation again to view results for this source.
        </Alert>
      ) : (
        <Alert severity="info">
          Choose a supported mission FITS file to preview read-only interpretation.
        </Alert>
      )}
    </Stack>
  );
};

export default InterpretationPanel;
