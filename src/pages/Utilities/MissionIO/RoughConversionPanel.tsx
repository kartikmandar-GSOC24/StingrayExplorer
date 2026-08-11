import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  AlertTitle,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormLabel,
  Grid,
  Radio,
  RadioGroup,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import CalculateIcon from '@mui/icons-material/Calculate';
import type { Data } from 'plotly.js';
import EventListSelector from '@/components/analysis/EventListSelector';
import PlotlyChart from '@/components/plots/PlotlyChart';
import {
  NumericResultTable,
  ProvenancePanel,
} from '@/components/utilities/UtilityResult';
import {
  missionIoApi,
  type ApproximateConversionData,
  type ConversionDependency,
  type ConvertPiParams,
} from '@/api/missionIoApi';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { EVENT_LISTS_QUERY_KEY, useEventLists } from '@/hooks/useEventLists';
import { parseNumericArray, validateDerivedName } from '@/utils/utilityInputs';
import { parsePositiveNumber } from '@/utils/numbers';
import {
  MissionFieldCards,
  mergeWarnings,
  OptionalOverrides,
  ResultFeedback,
  ResultSection,
  hasOverrideErrors,
  optionalText,
  type OverrideValues,
} from './MissionCommon';

const EMPTY_OVERRIDES: OverrideValues = { mission: '', instrument: '', mode: '' };
const XTE_MIN_EXCLUSIVE_MJD = 50_081;
const XTE_MAX_INCLUSIVE_MJD = 55_931;

function parsePiValues(text: string): { value: number[] | null; error: string | null } {
  const parsed = parseNumericArray(text, 'PI values');
  if (!parsed.value) return parsed;
  const invalidIndex = parsed.value.findIndex(
    (value) => !Number.isSafeInteger(value) || value < 0
  );
  if (invalidIndex >= 0) {
    return {
      value: null,
      error: `PI value ${invalidIndex + 1} must be a non-negative integer channel`,
    };
  }
  return parsed;
}

function parseDetectorIds(text: string): { value: number[] | null; error: string | null } {
  if (text.trim() === '') return { value: null, error: null };
  const parsed = parseNumericArray(text, 'Detector IDs');
  if (!parsed.value) return parsed;
  const invalidIndex = parsed.value.findIndex(
    (value) => !Number.isSafeInteger(value) || value < 0 || value > 4
  );
  if (invalidIndex >= 0) {
    return {
      value: null,
      error: `Detector ID ${invalidIndex + 1} must be an integer in the RXTE PCU range 0-4`,
    };
  }
  return parsed;
}

function dependencyLabel(name: string, dependency: ConversionDependency): string {
  if (dependency.used === false) {
    if (dependency.requested_value != null) {
      return `${name}: requested ${dependency.requested_value}; not used`;
    }
    if (dependency.value != null) return `${name}: ${dependency.value}; not used`;
    return `${name}: not used`;
  }
  return `${name}: ${dependency.value ?? dependency.source ?? (dependency.used ? 'used' : 'not provided')}`;
}

const RoughConversionPanel: React.FC = () => {
  const queryClient = useQueryClient();
  const eventLists = useEventLists();
  const [sourceType, setSourceType] = React.useState<'pasted' | 'event_list'>('pasted');
  const [piText, setPiText] = React.useState('');
  const [eventListName, setEventListName] = React.useState('');
  const [overrides, setOverrides] = React.useState<OverrideValues>(EMPTY_OVERRIDES);
  const [epochMjd, setEpochMjd] = React.useState('');
  const [detectorText, setDetectorText] = React.useState('');
  const [saveDerived, setSaveDerived] = React.useState(false);
  const [saveAs, setSaveAs] = React.useState('');
  const {
    result: runnerResult,
    running,
    error,
    warnings,
    run,
  } = useAnalysisRunner<ApproximateConversionData>('Approximate PI-to-energy conversion');
  const [resultSignature, setResultSignature] = React.useState<string | null>(null);
  const [requestSignature, setRequestSignature] = React.useState<string | null>(null);

  const inputSignature = JSON.stringify({
    sourceType,
    piText,
    eventListName,
    overrides,
    epochMjd,
    detectorText,
    saveDerived,
    saveAs,
  });
  const result = resultSignature === inputSignature ? runnerResult : null;
  const feedbackIsCurrent = requestSignature === inputSignature;

  const parsedPi = sourceType === 'pasted' ? parsePiValues(piText) : { value: null, error: null };
  const parsedDetectors = parseDetectorIds(detectorText);
  const missionKey = overrides.mission.trim().toLowerCase();
  const isXte = missionKey === 'xte' || missionKey === 'rxte';
  const isAxaf = missionKey === 'axaf' || missionKey === 'chandra';
  const pastedPiCount = sourceType === 'pasted' ? parsedPi.value?.length : undefined;
  const selectedEventCount = eventLists.data?.find(
    (eventList) => eventList.name === eventListName
  )?.n_events;
  const expectedDetectorCount = pastedPiCount ?? selectedEventCount;
  const xtePiRangeError =
    isXte && parsedPi.value
      ? (() => {
          const index = parsedPi.value.findIndex((value) => value > 255);
          return index >= 0
            ? `PI value ${index + 1} must be in the RXTE PCA channel range 0-255`
            : null;
        })()
      : null;
  const axafPiRangeError =
    isAxaf && parsedPi.value
      ? (() => {
          const index = parsedPi.value.findIndex((value) => value < 1);
          return index >= 0
            ? `PI value ${index + 1} must be at least 1 for AXAF/Chandra conversion`
            : null;
        })()
      : null;
  const missionPiError = parsedPi.error ?? xtePiRangeError ?? axafPiRangeError;
  const instrument = overrides.instrument.trim();
  const xteInstrumentError = !isXte
    ? null
    : instrument !== '' && instrument.toLowerCase() !== 'pca'
      ? 'RXTE rough conversion supports only the PCA instrument'
      : sourceType === 'pasted' && instrument === ''
        ? 'RXTE pasted-PI conversion requires instrument override PCA'
        : null;
  const epochNumber = epochMjd.trim() === '' ? undefined : parsePositiveNumber(epochMjd);
  const numericEpochError =
    epochNumber === null
      ? 'Epoch MJD must be a positive finite number'
      : null;
  const xteEpochRangeError =
    isXte && typeof epochNumber === 'number' &&
    !(epochNumber > XTE_MIN_EXCLUSIVE_MJD && epochNumber <= XTE_MAX_INCLUSIVE_MJD)
      ? `RXTE PCA calibration requires ${XTE_MIN_EXCLUSIVE_MJD} < epoch MJD ≤ ${XTE_MAX_INCLUSIVE_MJD}`
      : null;
  const epochError =
    numericEpochError ??
    xteEpochRangeError ??
    (isXte && sourceType === 'pasted' && epochNumber === undefined
      ? 'RXTE pasted-PI conversion requires an observation epoch in MJD'
      : null);
  const detectorCardinalityError =
    isXte &&
    parsedDetectors.value &&
    expectedDetectorCount !== undefined &&
    parsedDetectors.value.length !== 1 &&
    parsedDetectors.value.length !== expectedDetectorCount
      ? `Provide one detector ID to broadcast or ${expectedDetectorCount} IDs, one per PI channel`
      : null;
  const detectorError =
    parsedDetectors.error ??
    (isXte && sourceType === 'pasted' && parsedDetectors.value === null
      ? 'RXTE pasted-PI conversion requires detector IDs (PCU 0-4)'
      : detectorCardinalityError);
  const nameValidationError =
    saveDerived && saveAs !== '' ? validateDerivedName(saveAs) : null;
  const duplicateName =
    saveDerived &&
    saveAs !== '' &&
    eventLists.data?.some((eventList) => eventList.name === saveAs);
  const nameError = nameValidationError ?? (saveAs === eventListName && saveAs !== ''
    ? 'Destination name must differ from the source EventList'
    : duplicateName
      ? `An EventList named "${saveAs}" already exists`
      : null);
  const sourceReady =
    sourceType === 'pasted' ? parsedPi.value !== null : eventListName !== '';
  const pastedMissionMissing = sourceType === 'pasted' && overrides.mission.trim() === '';
  const overridesInvalid = hasOverrideErrors(overrides);
  const saveReady =
    sourceType !== 'event_list' || !saveDerived || (saveAs !== '' && nameError === null);
  const canRun =
    sourceReady &&
    !pastedMissionMissing &&
    missionPiError === null &&
    xteInstrumentError === null &&
    detectorError === null &&
    epochError === null &&
    !overridesInvalid &&
    saveReady &&
    !running;

  const convert = (): void => {
    if (!canRun) return;
    const mission = optionalText(overrides.mission);
    const instrument = optionalText(overrides.instrument);
    const mode = optionalText(overrides.mode);
    const commonParams = {
      ...(mission ? { mission_override: mission } : {}),
      ...(instrument ? { instrument_override: instrument } : {}),
      ...(mode ? { mode_override: mode } : {}),
      ...(typeof epochNumber === 'number' ? { epoch_mjd: epochNumber } : {}),
      ...(parsedDetectors.value ? { detector_ids: parsedDetectors.value } : {}),
    };
    let params: ConvertPiParams;
    if (sourceType === 'pasted') {
      if (!parsedPi.value) return;
      params = { ...commonParams, pi_values: parsedPi.value };
    } else {
      params = {
        ...commonParams,
        event_list_name: eventListName,
        ...(saveDerived ? { save_as: saveAs } : {}),
      };
    }

    const submittedSignature = inputSignature;
    setRequestSignature(submittedSignature);
    void run(async () => {
      const response = await missionIoApi.convertPi(params);
      if (response.success && response.data) setResultSignature(submittedSignature);
      if (response.success && response.data?.saved_event_list) {
        void queryClient.invalidateQueries({ queryKey: EVENT_LISTS_QUERY_KEY });
      }
      return response;
    });
  };

  const plotData: Data[] = result
    ? [
        {
          x: result.rows.map((row) => row.pi),
          y: result.rows.map((row) => row.energy_kev),
          type: 'scattergl',
          mode: 'lines+markers',
          name: 'Approximate energy',
        } as Data,
      ]
    : [];

  return (
    <Stack spacing={2.5}>
      <Alert severity="warning">
        <AlertTitle>APPROXIMATE rough conversion only</AlertTitle>
        Mission relations are not a substitute for RMF calibration. Use RMF-based PI-to-energy
        conversion in General I/O for precise calibrated energies.
      </Alert>

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6">Preview rough PI-to-energy conversion</Typography>
            <FormControl disabled={running}>
              <FormLabel id="pi-source-label">PI source</FormLabel>
              <RadioGroup
                row
                aria-labelledby="pi-source-label"
                value={sourceType}
                onChange={(event) =>
                  setSourceType(event.target.value as 'pasted' | 'event_list')
                }
              >
                <FormControlLabel value="pasted" control={<Radio />} label="Pasted PI channels" />
                <FormControlLabel value="event_list" control={<Radio />} label="Loaded EventList" />
              </RadioGroup>
            </FormControl>

            {sourceType === 'pasted' ? (
              <TextField
                fullWidth
                multiline
                minRows={3}
                label="PI values"
                value={piText}
                onChange={(event) => setPiText(event.target.value)}
                disabled={running}
                error={piText.trim() !== '' && missionPiError !== null}
                helperText={
                  piText.trim() !== '' && missionPiError
                    ? missionPiError
                    : 'Comma, space, or newline-separated non-negative integer channels'
                }
              />
            ) : (
              <EventListSelector
                label="EventList with PI channels"
                value={eventListName}
                onChange={setEventListName}
                requiredCapability="pi"
                disabled={running}
              />
            )}

            <OptionalOverrides
              values={overrides}
              onChange={setOverrides}
              disabled={running}
              missionRequired={sourceType === 'pasted'}
            />

            <Grid container spacing={1.5}>
              <Grid item xs={12} md={6}>
                <TextField
                  fullWidth
                  size="small"
                  label="Observation epoch (MJD, if required)"
                  value={epochMjd}
                  onChange={(event) => setEpochMjd(event.target.value)}
                  disabled={running}
                  error={epochError !== null}
                  helperText={epochError ?? 'Required by RXTE PCA; may be derived from EventList timing metadata'}
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  fullWidth
                  size="small"
                  label="Detector IDs (if required)"
                  value={detectorText}
                  onChange={(event) => setDetectorText(event.target.value)}
                  disabled={running}
                  error={detectorError !== null}
                  helperText={
                    detectorError ??
                    'RXTE PCA PCU IDs 0-4: one value to broadcast or one per PI channel'
                  }
                />
              </Grid>
            </Grid>

            {sourceType === 'event_list' ? (
              <Stack spacing={1}>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={saveDerived}
                      onChange={(event) => setSaveDerived(event.target.checked)}
                      disabled={running}
                    />
                  }
                  label="Save converted data as a new EventList"
                />
                {saveDerived ? (
                  <TextField
                    fullWidth
                    size="small"
                    label="Save as EventList name"
                    value={saveAs}
                    onChange={(event) => setSaveAs(event.target.value)}
                    disabled={running}
                    error={saveAs !== '' && nameError !== null}
                    helperText={
                      (saveAs !== '' && nameError) ||
                      'The source remains unchanged; the backend rejects duplicate names atomically'
                    }
                  />
                ) : null}
              </Stack>
            ) : null}

            {pastedMissionMissing ? (
              <Alert severity="info">A mission override is required for pasted PI channels.</Alert>
            ) : null}
            {isXte &&
            [xteInstrumentError, epochError, detectorError, xtePiRangeError].some(Boolean) ? (
              <Alert severity="error">
                <AlertTitle>RXTE PCA input requirements</AlertTitle>
                <Stack spacing={0.25}>
                  {[xteInstrumentError, epochError, detectorError, xtePiRangeError]
                    .filter((message): message is string => message !== null)
                    .map((message) => (
                      <Typography key={message} variant="body2">
                        {message}
                      </Typography>
                    ))}
                </Stack>
              </Alert>
            ) : null}
            <Button
              variant="contained"
              color="warning"
              startIcon={
                running ? <CircularProgress size={16} color="inherit" /> : <CalculateIcon />
              }
              disabled={!canRun}
              onClick={convert}
            >
              {running ? 'Converting…' : 'Run approximate conversion'}
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
          <Alert severity="warning">
            These values are approximate. For publication-quality calibrated energies, use{' '}
            {result.precise_calibration.method} in {result.precise_calibration.location}.
          </Alert>
          <MissionFieldCards
            mission={result.mission}
            instrument={result.instrument}
            mode={result.mode}
          />
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip color="warning" label={`${result.count.toLocaleString()} channels converted`} />
            <Chip label={`Energy unit: ${result.energy_unit}`} />
            {Object.entries(result.dependencies).map(([name, dependency]) => (
              <Chip
                key={name}
                size="small"
                color={dependency.required ? 'warning' : 'default'}
                label={dependencyLabel(name, dependency)}
              />
            ))}
            {result.saved_event_list ? (
              <Chip color="success" label={`Saved as ${result.saved_event_list}`} />
            ) : null}
          </Stack>
          <PlotlyChart
            data={plotData}
            layout={{
              title: { text: 'Approximate PI channel to energy relation' },
              xaxis: { title: { text: 'PI channel' } },
              yaxis: { title: { text: 'Approximate energy (keV)' } },
            }}
          />
          <NumericResultTable
            title="Approximate converted values"
            columns={[
              { key: 'index', label: 'Index' },
              { key: 'pi', label: 'PI channel' },
              { key: 'energy_kev', label: 'Approximate energy', unit: 'keV' },
              ...(result.rows.some((row) => row.detector_id !== undefined)
                ? [{ key: 'detector_id', label: 'Detector ID' }]
                : []),
            ]}
            rows={result.rows}
          />
          {result.preview_truncated ? (
            <Alert severity="info">
              Showing {result.preview_count.toLocaleString()} of {result.count.toLocaleString()} rows.
            </Alert>
          ) : null}
          <ProvenancePanel provenance={result.provenance} />
        </ResultSection>
      ) : runnerResult ? (
        <Alert severity="warning">
          Conversion inputs changed. Run conversion again to view results for this source.
        </Alert>
      ) : (
        <Alert severity="info">Supply PI channels or choose an EventList to preview conversion.</Alert>
      )}
    </Stack>
  );
};

export default RoughConversionPanel;
