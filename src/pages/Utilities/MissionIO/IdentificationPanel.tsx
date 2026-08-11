import React from 'react';
import {
  Alert,
  Button,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
  Stack,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import EventListSelector from '@/components/analysis/EventListSelector';
import GrantedFileField, {
  type GrantedFileSelection,
} from '@/components/utilities/GrantedFileField';
import {
  missionIoApi,
  type IdentifyMissionParams,
  type MissionIdentificationData,
} from '@/api/missionIoApi';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { ProvenancePanel } from '@/components/utilities/UtilityResult';
import {
  MappingTable,
  mergeWarnings,
  MissionFieldCards,
  OptionalOverrides,
  ResultFeedback,
  ResultSection,
  displayValue,
  hasOverrideErrors,
  optionalText,
  type OverrideValues,
} from './MissionCommon';

const EMPTY_OVERRIDES: OverrideValues = { mission: '', instrument: '', mode: '' };

const IdentificationPanel: React.FC = () => {
  const [sourceType, setSourceType] = React.useState<'event_list' | 'fits'>('event_list');
  const [eventListName, setEventListName] = React.useState('');
  const [fitsFile, setFitsFile] = React.useState<GrantedFileSelection | null>(null);
  const [overrides, setOverrides] = React.useState<OverrideValues>(EMPTY_OVERRIDES);
  const {
    result: runnerResult,
    running,
    error,
    warnings,
    run,
  } = useAnalysisRunner<MissionIdentificationData>('Mission identification');
  const [resultSignature, setResultSignature] = React.useState<string | null>(null);
  const [requestSignature, setRequestSignature] = React.useState<string | null>(null);

  const inputSignature = JSON.stringify({ sourceType, eventListName, fitsFile, overrides });
  const result = resultSignature === inputSignature ? runnerResult : null;
  const feedbackIsCurrent = requestSignature === inputSignature;

  const sourceReady = sourceType === 'event_list' ? eventListName !== '' : fitsFile !== null;
  const overridesInvalid = hasOverrideErrors(overrides);

  const identify = (): void => {
    if (!sourceReady || overridesInvalid) return;
    const overrideParams: {
      mission_override?: string;
      instrument_override?: string;
      mode_override?: string;
    } = {};
    const mission = optionalText(overrides.mission);
    const instrument = optionalText(overrides.instrument);
    const mode = optionalText(overrides.mode);
    if (mission) overrideParams.mission_override = mission;
    if (instrument) overrideParams.instrument_override = instrument;
    if (mode) overrideParams.mode_override = mode;
    let params: IdentifyMissionParams;
    if (sourceType === 'event_list') {
      params = { event_list_name: eventListName, ...overrideParams };
    } else {
      if (!fitsFile) return;
      params = {
        file_path: fitsFile.path,
        file_grant: fitsFile.grant,
        ...overrideParams,
      };
    }
    const submittedSignature = inputSignature;
    setRequestSignature(submittedSignature);
    void run(async () => {
      const response = await missionIoApi.identify(params);
      if (response.success && response.data) setResultSignature(submittedSignature);
      return response;
    });
  };

  return (
    <Stack spacing={2.5}>
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6">Identify mission metadata</Typography>
            <Typography variant="body2" color="text.secondary">
              Inspect one loaded EventList or one explicitly selected FITS file. Every value is
              labelled with its origin; inferred aliases and user overrides remain visible.
            </Typography>
            <FormControl disabled={running}>
              <FormLabel id="mission-identify-source-label">Source</FormLabel>
              <RadioGroup
                row
                aria-labelledby="mission-identify-source-label"
                value={sourceType}
                onChange={(event) => setSourceType(event.target.value as 'event_list' | 'fits')}
              >
                <FormControlLabel value="event_list" control={<Radio />} label="Loaded EventList" />
                <FormControlLabel value="fits" control={<Radio />} label="Selected FITS file" />
              </RadioGroup>
            </FormControl>
            {sourceType === 'event_list' ? (
              <EventListSelector
                label="EventList to identify"
                value={eventListName}
                onChange={setEventListName}
                disabled={running}
              />
            ) : (
              <GrantedFileField
                label="Mission FITS file"
                value={fitsFile}
                onChange={setFitsFile}
                disabled={running}
                filters={[{ name: 'FITS files', extensions: ['fits', 'fit', 'fts', 'evt'] }]}
              />
            )}
            <OptionalOverrides values={overrides} onChange={setOverrides} disabled={running} />
            <Button
              variant="contained"
              startIcon={running ? <CircularProgress size={16} color="inherit" /> : <SearchIcon />}
              disabled={!sourceReady || overridesInvalid || running}
              onClick={identify}
            >
              {running ? 'Identifying…' : 'Identify mission'}
            </Button>
          </Stack>
        </CardContent>
      </Card>

      <ResultFeedback
        error={feedbackIsCurrent ? error : null}
        warnings={feedbackIsCurrent ? mergeWarnings(warnings, result?.warnings) : []}
      />

      {result ? (
        <ResultSection title="Identification result">
          <MissionFieldCards
            mission={result.mission}
            instrument={result.instrument}
            mode={result.mode}
          />
          {result.mapping ? (
            <MappingTable mapping={result.mapping} />
          ) : (
            <Alert severity="info">
              No runtime FITS mapping is available until a supported mission is identified or
              supplied as an override.
            </Alert>
          )}
          {result.timing_metadata && Object.keys(result.timing_metadata).length > 0 ? (
            <Card variant="outlined">
              <CardContent>
                <Stack spacing={0.75}>
                  <Typography variant="subtitle2">Timing metadata</Typography>
                  {Object.entries(result.timing_metadata).map(([key, entry]) => {
                    const preciseValue =
                      'decimal' in entry && typeof entry.decimal === 'string'
                        ? entry.decimal
                        : displayValue(entry.value);
                    const components =
                      key === 'mjdref' ? result.timing_metadata?.mjdref?.components : null;
                    return (
                      <Stack key={key} spacing={0.25}>
                        <Typography variant="body2">
                          <strong>{key}:</strong> {preciseValue}{' '}
                          <Typography component="span" variant="caption" color="text.secondary">
                            from {entry.source ?? 'unknown source'}
                          </Typography>
                        </Typography>
                        {components ? (
                          <Typography variant="caption" color="text.secondary">
                            MJDREFI={components.integer.value} from{' '}
                            {components.integer.source ?? 'unknown source'}; MJDREFF=
                            {components.fraction.value} from{' '}
                            {components.fraction.source ?? 'unknown source'}
                          </Typography>
                        ) : null}
                      </Stack>
                    );
                  })}
                </Stack>
              </CardContent>
            </Card>
          ) : null}
          {result.hdus ? (
            <Alert severity="info">
              Inspected {result.hdus.length} FITS HDU{result.hdus.length === 1 ? '' : 's'} without
              loading the full event table.
            </Alert>
          ) : null}
          <ProvenancePanel provenance={result.provenance} />
        </ResultSection>
      ) : runnerResult ? (
        <Alert severity="warning">
          Identification inputs changed. Run identification again to view results for this source.
        </Alert>
      ) : (
        <Alert severity="info">Choose a source to inspect its mission metadata and mappings.</Alert>
      )}
    </Stack>
  );
};

export default IdentificationPanel;
