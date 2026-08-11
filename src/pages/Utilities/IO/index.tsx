import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import AssessmentOutlinedIcon from '@mui/icons-material/AssessmentOutlined';
import CalculateOutlinedIcon from '@mui/icons-material/CalculateOutlined';
import RefreshIcon from '@mui/icons-material/Refresh';
import SaveAltIcon from '@mui/icons-material/SaveAlt';
import SearchIcon from '@mui/icons-material/Search';
import { useQueryClient } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import PageTemplate from '@/components/common/PageTemplate';
import EventListSelector from '@/components/analysis/EventListSelector';
import GrantedFileField, {
  GrantedFileSelection,
} from '@/components/utilities/GrantedFileField';
import {
  NumericResultTable,
  ProvenancePanel,
  ResultCell,
  UtilityWarnings,
} from '@/components/utilities/UtilityResult';
import PlotlyChart from '@/components/plots/PlotlyChart';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { EVENT_LISTS_QUERY_KEY } from '@/hooks/useEventLists';
import { parseNumericArray, validateDerivedName } from '@/utils/utilityInputs';
import {
  EventListConversionResult,
  ExportableObject,
  ExportableObjectsResult,
  ExportResult,
  FileInspectionResult,
  ioApi,
  PiConversionResult,
  RmfInspectionResult,
  UtilityExportFormat,
} from '@/api/ioApi';

const EMPTY_EXPORTABLE_OBJECTS: ExportableObject[] = [];

interface SummaryDatum {
  label: string;
  value: React.ReactNode;
}

const SummaryGrid: React.FC<{ values: SummaryDatum[] }> = ({ values }) => (
  <Grid container spacing={1.5}>
    {values.map((item) => (
      <Grid item xs={12} sm={6} md={3} key={item.label}>
        <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
          <Typography variant="caption" color="text.secondary">
            {item.label}
          </Typography>
          <Typography component="div" variant="body2" sx={{ mt: 0.25, overflowWrap: 'anywhere' }}>
            {item.value}
          </Typography>
        </Paper>
      </Grid>
    ))}
  </Grid>
);

const LoadingButtonContent: React.FC<{ loading: boolean; idle: string; busy: string }> = ({
  loading,
  idle,
  busy,
}) => (
  <>
    {loading ? <CircularProgress size={16} color="inherit" sx={{ mr: 1 }} /> : null}
    {loading ? busy : idle}
  </>
);

function formatBytes(size: number | null | undefined): string {
  if (size == null || !Number.isFinite(size) || size < 0) return 'Unknown';
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(2)} KiB`;
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(2)} MiB`;
  return `${(size / 1024 ** 3).toFixed(2)} GiB`;
}

function formatMaybe(value: unknown): string {
  if (value == null || value === '') return 'Not provided';
  return String(value);
}

function getObjectName(object: ExportableObject): string {
  return object.name;
}

function getObjectFormats(object: ExportableObject | undefined): UtilityExportFormat[] {
  return object?.formats ?? [];
}

function getObjectKey(object: ExportableObject): string {
  return `${object.object_type}:${getObjectName(object)}`;
}

function fileHduRows(result: FileInspectionResult): Array<Record<string, ResultCell>> {
  return result.hdus.map((hdu) => ({
    index: hdu.index,
    name: hdu.name,
    type: hdu.type,
    shape: hdu.dimensions ? hdu.dimensions.join(' × ') : 'Not applicable',
    rows: hdu.row_count,
    columns: hdu.columns
      .map((column) => `${column.name} [${column.format}${column.unit ? `; ${column.unit}` : ''}]`)
      .join(', '),
  }));
}

function fileTimingRows(result: FileInspectionResult): Array<Record<string, ResultCell>> {
  return result.hdus.map((hdu) => ({
    hdu: hdu.index,
    name: hdu.name,
    status: hdu.timing.status,
    mjdref: hdu.timing.mjdref?.decimal ?? null,
    stingray_mjdref: hdu.timing.mjdref?.stingray_value ?? null,
    source: hdu.timing.mjdref
      ? Object.entries(hdu.timing.mjdref.source_keywords)
          .map(([keyword, value]) => `${keyword}=${value}`)
          .join(' + ')
      : null,
    timesys: hdu.timing.keywords.TIMESYS ?? null,
    timeref: hdu.timing.keywords.TIMEREF ?? null,
    timeunit: hdu.timing.keywords.TIMEUNIT ?? null,
    all_keywords:
      Object.entries(hdu.timing.keywords)
        .map(([keyword, value]) => `${keyword}=${formatMaybe(value)}`)
        .join('; ') || null,
    exact_split_values:
      Object.entries(hdu.timing.high_precision_keywords)
        .map(([keyword, value]) => {
          const sources = Object.entries(value.source_keywords)
            .map(([sourceKeyword, sourceValue]) => `${sourceKeyword}=${sourceValue}`)
            .join(' + ');
          return `${keyword}=${value.decimal} (Stingray ${value.stingray_value}; ${sources})`;
        })
        .join('; ') || null,
    note: hdu.timing.note,
  }));
}

function rmfRows(result: RmfInspectionResult): Array<Record<string, ResultCell>> {
  return result.preview_rows.map((bound) => ({
    channel: bound.channel,
    energy_min: bound.energy_min,
    energy_max: bound.energy_max,
    energy_midpoint: bound.energy_midpoint,
  }));
}

function conversionRows(result: PiConversionResult): Array<Record<string, ResultCell>> {
  return result.rows.map((row) => ({ index: row.index, pi: row.pi, energy: row.energy }));
}

function previewValues(result: PiConversionResult): {
  pi: number[];
  energy: Array<number | null>;
} {
  return { pi: result.plot.arrays[0], energy: result.plot.arrays[1] };
}

const ExportCapabilitySummary: React.FC<{ catalog: ExportableObjectsResult }> = ({ catalog }) => (
  <Stack spacing={1}>
    <Typography variant="subtitle2">Verified format compatibility</Typography>
    <NumericResultTable
      title="Object and format capabilities"
      columns={[
        { key: 'object_type', label: 'Object type' },
        ...catalog.format_allowlist.map((allowedFormat) => ({
          key: allowedFormat,
          label: allowedFormat.toUpperCase(),
        })),
      ]}
      rows={Object.entries(catalog.capability_matrix).map(([objectType, matrix]) => ({
        object_type: objectType.replace(/_/g, ' '),
        ...Object.fromEntries(
          catalog.format_allowlist.map((allowedFormat) => {
            const capability = matrix[allowedFormat];
            return [
              allowedFormat,
              capability.supported
                ? `Supported — ${capability.notes}`
                : capability.notes || 'Not supported',
            ];
          })
        ),
      }))}
      pageSize={10}
    />
    <Typography variant="caption" color="text.secondary">
      Maximum export size: {catalog.row_cap.toLocaleString()} rows.{' '}
      {Object.entries(catalog.excluded_formats)
        .map(([format, reason]) => `${format.toUpperCase()}: ${reason}`)
        .join(' ')}
    </Typography>
  </Stack>
);

interface FileInspectorPanelProps {
  selection: GrantedFileSelection | null;
  onSelectionChange: (selection: GrantedFileSelection | null) => void;
}

const FileInspectorPanel: React.FC<FileInspectorPanelProps> = ({ selection, onSelectionChange }) => {
  const inspection = useAnalysisRunner<FileInspectionResult>('File inspection');

  const changeSelection = (nextSelection: GrantedFileSelection | null): void => {
    inspection.reset();
    onSelectionChange(nextSelection);
  };

  const inspect = (): void => {
    if (!selection) return;
    void inspection.run(() =>
      ioApi.inspectFile({ file_path: selection.path, file_grant: selection.grant })
    );
  };

  const result = inspection.result?.path === selection?.path ? inspection.result : null;
  const hasTiming =
    result?.hdus.some(
      (hdu) =>
        hdu.timing.mjdref != null ||
        Object.keys(hdu.timing.keywords).length > 0 ||
        Object.keys(hdu.timing.high_precision_keywords).length > 0
    ) ?? false;

  return (
    <Stack spacing={2.5}>
      <Typography variant="body2" color="text.secondary">
        Inspect an explicitly selected local file. FITS headers and HDU structure are read without
        materializing full event tables.
      </Typography>
      <GrantedFileField
        label="Scientific file"
        value={selection}
        onChange={changeSelection}
        disabled={inspection.running}
      />
      <Box>
        <Button
          variant="contained"
          startIcon={!inspection.running ? <SearchIcon /> : undefined}
          disabled={!selection || inspection.running}
          onClick={inspect}
        >
          <LoadingButtonContent loading={inspection.running} idle="Inspect file" busy="Inspecting…" />
        </Button>
      </Box>
      {inspection.error ? <Alert severity="error">{inspection.error}</Alert> : null}
      <UtilityWarnings warnings={inspection.warnings} />
      {result ? (
        <Stack spacing={2} aria-label="File inspection result">
          <UtilityWarnings warnings={result.warnings} />
          <SummaryGrid
            values={[
              { label: 'Path', value: result.path },
              { label: 'Detected type', value: result.detected_type },
              { label: 'Extension', value: result.extension || 'None' },
              { label: 'File size', value: formatBytes(result.size_bytes) },
              {
                label: 'Supported format',
                value: (
                  <Chip
                    size="small"
                    color={result.supported ? 'success' : 'default'}
                    label={result.supported ? 'Supported' : 'Inspection only'}
                  />
                ),
              },
            ]}
          />
          <Box>
            <Typography variant="subtitle1" gutterBottom>
              Time reference
            </Typography>
            {!hasTiming ? (
              <Alert severity="info">
                No unambiguous time-reference metadata was found in the inspected headers.
              </Alert>
            ) : null}
            {result.hdus.length > 0 ? (
              <NumericResultTable
                title="Per-HDU timing metadata"
                columns={[
                  { key: 'hdu', label: 'HDU' },
                  { key: 'name', label: 'Name' },
                  { key: 'status', label: 'Status' },
                  { key: 'mjdref', label: 'MJD reference (exact)' },
                  { key: 'stingray_mjdref', label: 'Stingray numeric MJD reference' },
                  { key: 'source', label: 'MJD source values' },
                  { key: 'timesys', label: 'TIMESYS' },
                  { key: 'timeref', label: 'TIMEREF' },
                  { key: 'timeunit', label: 'TIMEUNIT' },
                  { key: 'all_keywords', label: 'All FITS timing keywords' },
                  { key: 'exact_split_values', label: 'Exact split timing values' },
                  { key: 'note', label: 'Interpretation' },
                ]}
                rows={fileTimingRows(result)}
              />
            ) : null}
          </Box>
          {result.hdus.length > 0 ? (
            <NumericResultTable
              title="FITS HDUs"
              columns={[
                { key: 'index', label: 'HDU' },
                { key: 'name', label: 'Name' },
                { key: 'type', label: 'Type' },
                { key: 'shape', label: 'Shape' },
                { key: 'rows', label: 'Rows' },
                { key: 'columns', label: 'Columns' },
              ]}
              rows={fileHduRows(result)}
            />
          ) : (
            <Alert severity="info">This file has no FITS HDU table to display.</Alert>
          )}
          <ProvenancePanel provenance={result.provenance} />
        </Stack>
      ) : (
        <Alert severity="info">Choose a file to inspect its format, structure, and timing metadata.</Alert>
      )}
    </Stack>
  );
};

interface RmfPanelProps {
  rmfSelection: GrantedFileSelection | null;
  onRmfSelectionChange: (selection: GrantedFileSelection | null) => void;
  eventLists: ExportableObject[];
  onEventListSaved: () => void;
}

const RmfPanel: React.FC<RmfPanelProps> = ({
  rmfSelection,
  onRmfSelectionChange,
  eventLists,
  onEventListSaved,
}) => {
  const queryClient = useQueryClient();
  const rmfInspection = useAnalysisRunner<RmfInspectionResult>('RMF inspection');
  const piConversion = useAnalysisRunner<PiConversionResult>('PI-to-energy conversion');
  const eventConversion = useAnalysisRunner<EventListConversionResult>('Derived EventList conversion');
  const [piText, setPiText] = useState('');
  const [sourceEventList, setSourceEventList] = useState('');
  const [saveAs, setSaveAs] = useState('');
  const [piResultSignature, setPiResultSignature] = useState<string | null>(null);
  const [piRequestSignature, setPiRequestSignature] = useState<string | null>(null);
  const [eventResultSignature, setEventResultSignature] = useState<string | null>(null);
  const [eventRequestSignature, setEventRequestSignature] = useState<string | null>(null);

  const piInputSignature = JSON.stringify({ rmfSelection, piText });
  const eventInputSignature = JSON.stringify({ rmfSelection, sourceEventList, saveAs });
  const panelRunning =
    rmfInspection.running || piConversion.running || eventConversion.running;

  const parsedPi = useMemo(() => {
    const parsed = parseNumericArray(piText, 'PI values');
    if (!parsed.value) return parsed;
    const invalidIndex = parsed.value.findIndex(
      (value) => !Number.isSafeInteger(value) || value < 0
    );
    if (invalidIndex >= 0) {
      return {
        value: null,
        error: `PI value ${invalidIndex + 1} must be a non-negative integer`,
      };
    }
    return parsed;
  }, [piText]);

  const derivedNameError = saveAs === '' ? 'A new destination name is required' : validateDerivedName(saveAs);
  const isSameName = saveAs !== '' && saveAs === sourceEventList;
  const isDuplicateName =
    saveAs !== '' &&
    (eventLists.some((object) => getObjectName(object) === saveAs) ||
      (eventConversion.result?.saved === true &&
        eventConversion.result.saved_name === saveAs));
  const eventNameError = derivedNameError ?? (isSameName
    ? 'Destination name must differ from the source EventList'
    : isDuplicateName
      ? `An EventList named "${saveAs}" already exists`
      : null);
  const selectedRmfInspection =
    rmfInspection.result?.path === rmfSelection?.path ? rmfInspection.result : null;
  const conversionUnavailable = selectedRmfInspection?.conversion_supported === false;

  const changeRmfSelection = (selection: GrantedFileSelection | null): void => {
    rmfInspection.reset();
    piConversion.reset();
    eventConversion.reset();
    onRmfSelectionChange(selection);
  };

  const inspectRmf = (): void => {
    if (!rmfSelection) return;
    void rmfInspection.run(() =>
      ioApi.inspectRmf({ rmf_path: rmfSelection.path, rmf_grant: rmfSelection.grant })
    );
  };

  const convertPi = (): void => {
    if (!rmfSelection || !parsedPi.value) return;
    const submittedSignature = piInputSignature;
    setPiRequestSignature(submittedSignature);
    void piConversion.run(async () => {
      const response = await ioApi.convertPi({
        pi_values: parsedPi.value as number[],
        rmf_path: rmfSelection.path,
        rmf_grant: rmfSelection.grant,
      });
      if (response.success && response.data) setPiResultSignature(submittedSignature);
      return response;
    });
  };

  const convertEventList = (save: boolean): void => {
    if (
      !rmfSelection ||
      !sourceEventList ||
      conversionUnavailable ||
      (save && eventNameError)
    ) return;
    const submittedSignature = eventInputSignature;
    setEventRequestSignature(submittedSignature);
    void eventConversion.run(async () => {
      const response = await ioApi.convertEventList({
        event_list_name: sourceEventList,
        rmf_path: rmfSelection.path,
        rmf_grant: rmfSelection.grant,
        save_as: save ? saveAs : null,
      });
      if (save && response.success && response.data?.saved) {
        onEventListSaved();
        void queryClient.invalidateQueries({ queryKey: EVENT_LISTS_QUERY_KEY });
      }
      if (response.success && response.data) setEventResultSignature(submittedSignature);
      return response;
    });
  };

  const piResult =
    piResultSignature === piInputSignature ? piConversion.result : null;
  const eventResult =
    eventResultSignature === eventInputSignature ? eventConversion.result : null;
  const piFeedbackCurrent = piRequestSignature === piInputSignature;
  const eventFeedbackCurrent = eventRequestSignature === eventInputSignature;
  const plot = piResult ? previewValues(piResult) : null;
  const energyUnit = piResult?.energy_unit ?? 'keV';

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h6" gutterBottom>
          Response matrix
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          RMF calibration maps exact integer PI channels to calibrated energy bounds. Unmatched
          channels are reported instead of silently receiving an energy.
        </Typography>
        <Stack spacing={2}>
          <GrantedFileField
            label="RMF file"
            value={rmfSelection}
            onChange={changeRmfSelection}
            disabled={panelRunning}
          />
          <Box>
            <Button
              variant="outlined"
              startIcon={!rmfInspection.running ? <AssessmentOutlinedIcon /> : undefined}
              disabled={!rmfSelection || panelRunning}
              onClick={inspectRmf}
            >
              <LoadingButtonContent loading={rmfInspection.running} idle="Inspect RMF" busy="Inspecting…" />
            </Button>
          </Box>
          {rmfInspection.error ? <Alert severity="error">{rmfInspection.error}</Alert> : null}
          <UtilityWarnings warnings={rmfInspection.warnings} />
          {selectedRmfInspection ? (
            <Stack spacing={2} aria-label="RMF inspection result">
              <UtilityWarnings warnings={selectedRmfInspection.warnings} />
              <SummaryGrid
                values={[
                  { label: 'Channels', value: selectedRmfInspection.channel_count },
                  {
                    label: 'Channel range',
                    value: `${formatMaybe(selectedRmfInspection.channel_min)} – ${formatMaybe(selectedRmfInspection.channel_max)}`,
                  },
                  {
                    label: selectedRmfInspection.energy_unit
                      ? `Energy range (${selectedRmfInspection.energy_unit})`
                      : 'Energy range (unit not declared)',
                    value: `${formatMaybe(selectedRmfInspection.energy_min)} – ${formatMaybe(selectedRmfInspection.energy_max)}`,
                  },
                  { label: 'File size', value: formatBytes(selectedRmfInspection.size_bytes) },
                  {
                    label: 'Calibration',
                    value: selectedRmfInspection.conversion_supported
                      ? 'Available'
                      : 'Unavailable (missing/ambiguous units)',
                  },
                  {
                    label: 'Channel sequence',
                    value: selectedRmfInspection.contiguous_channels
                      ? 'Contiguous'
                      : 'Non-contiguous (exact matches only)',
                  },
                ]}
              />
              {rmfRows(selectedRmfInspection).length > 0 ? (
                <NumericResultTable
                  title="Channel bounds preview"
                  columns={[
                    { key: 'channel', label: 'PI channel' },
                    { key: 'energy_min', label: 'Energy low', unit: selectedRmfInspection.energy_unit ?? undefined },
                    { key: 'energy_max', label: 'Energy high', unit: selectedRmfInspection.energy_unit ?? undefined },
                    {
                      key: 'energy_midpoint',
                      label: 'Energy midpoint',
                      unit: selectedRmfInspection.energy_unit ?? undefined,
                    },
                  ]}
                  rows={rmfRows(selectedRmfInspection)}
                />
              ) : null}
              <ProvenancePanel provenance={selectedRmfInspection.provenance} />
            </Stack>
          ) : null}
        </Stack>
      </Box>

      <Divider />

      <Box>
        <Typography variant="h6" gutterBottom>
          Convert pasted PI values
        </Typography>
        <Stack spacing={2}>
          <TextField
            label="PI values"
            value={piText}
            onChange={(event) => setPiText(event.target.value)}
            disabled={panelRunning}
            placeholder="0, 1, 2, 10"
            multiline
            minRows={3}
            error={piText !== '' && parsedPi.error != null}
            helperText={piText !== '' ? parsedPi.error ?? 'Comma, space, or newline separated integer channels' : 'Comma, space, or newline separated integer channels'}
          />
          <Box>
            <Button
              variant="contained"
              startIcon={!piConversion.running ? <CalculateOutlinedIcon /> : undefined}
              disabled={
                !rmfSelection || !parsedPi.value || conversionUnavailable || panelRunning
              }
              onClick={convertPi}
            >
              <LoadingButtonContent loading={piConversion.running} idle="Convert PI values" busy="Converting…" />
            </Button>
          </Box>
          {piFeedbackCurrent && piConversion.error ? (
            <Alert severity="error">{piConversion.error}</Alert>
          ) : null}
          <UtilityWarnings warnings={piFeedbackCurrent ? piConversion.warnings : []} />
          {piResult ? (
            <Stack spacing={2} aria-label="PI conversion result">
              <UtilityWarnings warnings={piResult.warnings} />
              {plot && plot.pi.length > 0 ? (
                <Paper variant="outlined" sx={{ p: 1 }}>
                  <PlotlyChart
                    height={330}
                    data={[
                      {
                        x: plot.pi,
                        y: plot.energy,
                        type: 'scattergl',
                        mode: 'lines+markers',
                        name: 'RMF calibration',
                      },
                    ]}
                    layout={{
                      xaxis: { title: { text: 'PI channel' } },
                      yaxis: { title: { text: `Energy (${energyUnit})` } },
                    }}
                  />
                </Paper>
              ) : null}
              <NumericResultTable
                title="PI-to-energy values"
                columns={[
                  { key: 'index', label: 'Index' },
                  { key: 'pi', label: 'PI channel' },
                  { key: 'energy', label: 'Energy', unit: energyUnit },
                ]}
                rows={conversionRows(piResult)}
              />
              <ProvenancePanel provenance={piResult.provenance} />
            </Stack>
          ) : piConversion.result ? (
            <Alert severity="warning">
              PI or RMF inputs changed. Convert again to view results for the current inputs.
            </Alert>
          ) : null}
        </Stack>
      </Box>

      <Divider />

      <Box>
        <Typography variant="h6" gutterBottom>
          Convert a loaded EventList
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          The source stays unchanged. Conversion is saved atomically under a new, unique EventList
          name while preserving the original PI channels and RMF provenance.
        </Typography>
        {eventLists.length === 0 ? (
          <Alert severity="info">Load an EventList with PI channels before using this conversion.</Alert>
        ) : (
          <Stack spacing={2}>
            <EventListSelector
              label="Source EventList"
              value={sourceEventList}
              onChange={(name) => {
                setSourceEventList(name);
                setSaveAs('');
              }}
              requiredCapability="pi"
              disabled={panelRunning}
            />
            <TextField
              size="small"
              label="Save as (new EventList name)"
              value={saveAs}
              onChange={(event) => setSaveAs(event.target.value)}
              disabled={panelRunning}
              error={saveAs !== '' && eventNameError != null}
              helperText={saveAs !== '' ? eventNameError ?? 'A new object; the source is never mutated' : 'Required; must be unique'}
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button
                variant="outlined"
                disabled={
                  !rmfSelection ||
                  conversionUnavailable ||
                  !sourceEventList ||
                  panelRunning
                }
                onClick={() => convertEventList(false)}
              >
                Preview conversion
              </Button>
              <Button
                variant="contained"
                disabled={
                  !rmfSelection ||
                  conversionUnavailable ||
                  !sourceEventList ||
                  eventNameError != null ||
                  panelRunning
                }
                onClick={() => convertEventList(true)}
              >
                <LoadingButtonContent
                  loading={eventConversion.running}
                  idle="Convert and save derived EventList"
                  busy="Converting…"
                />
              </Button>
            </Stack>
            {eventFeedbackCurrent && eventConversion.error ? (
              <Alert severity="error">{eventConversion.error}</Alert>
            ) : null}
            <UtilityWarnings warnings={eventFeedbackCurrent ? eventConversion.warnings : []} />
            {eventResult ? (
              <Stack spacing={2} aria-label="Derived EventList result">
                <Alert severity={eventResult.saved ? 'success' : 'info'}>
                  {eventResult.saved
                    ? `Saved ${eventResult.saved_name ?? saveAs} with ${eventResult.event_count.toLocaleString()} events`
                    : `Previewed ${eventResult.event_count.toLocaleString()} calibrated events; no object was saved and the source was not modified.`}
                </Alert>
                <UtilityWarnings warnings={eventResult.warnings} />
                <SummaryGrid
                  values={[
                    {
                      label: 'Source EventList',
                      value: eventResult.source_name,
                    },
                    {
                      label: 'Original PI channels',
                      value: eventResult.pi_preserved ? 'Preserved' : 'Not preserved',
                    },
                    {
                      label: 'Preview',
                      value: eventResult.preview_truncated
                        ? `First ${eventResult.preview_rows.length.toLocaleString()} rows`
                        : 'All rows',
                    },
                  ]}
                />
                {eventResult.plot.arrays[0].length > 0 ? (
                  <Paper variant="outlined" sx={{ p: 1 }}>
                    <PlotlyChart
                      height={330}
                      data={[
                        {
                          x: eventResult.plot.arrays[0],
                          y: eventResult.plot.arrays[1],
                          type: 'scattergl',
                          mode: 'markers',
                          name: 'RMF calibration',
                        },
                      ]}
                      layout={{
                        xaxis: { title: { text: 'PI channel' } },
                        yaxis: {
                          title: { text: `Energy (${eventResult.energy_unit})` },
                        },
                      }}
                    />
                  </Paper>
                ) : null}
                {eventResult.preview_rows.length > 0 ? (
                  <NumericResultTable
                    title="Converted event preview"
                    columns={[
                      { key: 'index', label: 'Index' },
                      { key: 'pi', label: 'PI channel' },
                      { key: 'energy', label: 'Energy', unit: eventResult.energy_unit },
                    ]}
                    rows={eventResult.preview_rows.map((row) => ({
                      index: row.index,
                      pi: row.pi,
                      energy: row.energy,
                    }))}
                  />
                ) : null}
                <ProvenancePanel provenance={eventResult.provenance} />
              </Stack>
            ) : eventConversion.result ? (
              <Alert severity="warning">
                EventList, RMF, or destination inputs changed. Convert again for the current source.
              </Alert>
            ) : null}
          </Stack>
        )}
      </Box>
    </Stack>
  );
};

interface ExportPanelProps {
  catalog: ExportableObjectsResult | null;
  loadingObjects: boolean;
  objectsError: string | null;
  onRefresh: () => void;
}

const ExportPanel: React.FC<ExportPanelProps> = ({
  catalog,
  loadingObjects,
  objectsError,
  onRefresh,
}) => {
  const objects = catalog?.objects ?? EMPTY_EXPORTABLE_OBJECTS;
  const exportRunner = useAnalysisRunner<ExportResult>('Scientific data export');
  const [objectKey, setObjectKey] = useState('');
  const [format, setFormat] = useState<UtilityExportFormat | ''>('');
  const [destination, setDestination] = useState<GrantedFileSelection | null>(null);
  const [destinationError, setDestinationError] = useState<string | null>(null);

  useEffect(() => {
    const current = objects.find((object) => getObjectKey(object) === objectKey);
    if (current?.exportable) {
      const formats = getObjectFormats(current);
      if (format && formats.includes(format)) return;
      setFormat(formats[0] ?? '');
      setDestination(null);
      setDestinationError(null);
      return;
    }
    const first = objects.find((object) => object.exportable);
    setObjectKey(first ? getObjectKey(first) : '');
    setFormat(first ? getObjectFormats(first)[0] ?? '' : '');
    setDestination(null);
    setDestinationError(null);
  }, [objects, objectKey, format]);

  const selectedObject = useMemo(
    () => objects.find((object) => getObjectKey(object) === objectKey),
    [objects, objectKey]
  );
  const formats = getObjectFormats(selectedObject);
  const selectedCapability =
    selectedObject && format && catalog
      ? catalog.capability_matrix[selectedObject.object_type][format]
      : null;

  const selectObject = (nextKey: string): void => {
    const nextObject = objects.find((object) => getObjectKey(object) === nextKey);
    setObjectKey(nextKey);
    setFormat(getObjectFormats(nextObject)[0] ?? '');
    setDestination(null);
    setDestinationError(null);
  };

  const selectFormat = (nextFormat: UtilityExportFormat): void => {
    setFormat(nextFormat);
    setDestination(null);
    setDestinationError(null);
  };

  const chooseDestination = async (): Promise<void> => {
    if (!selectedObject || !format) return;
    setDestinationError(null);
    if (!window.electronAPI?.saveGrantedFile) {
      setDestinationError('The native save dialog is unavailable.');
      return;
    }
    try {
      const selected = await window.electronAPI.saveGrantedFile({
        title: `Export ${getObjectName(selectedObject)}`,
        defaultPath: `${getObjectName(selectedObject)}.${format.toLowerCase()}`,
        filters: [{ name: format.toUpperCase(), extensions: [format.toLowerCase()] }],
      });
      // Cancelling the native dialog intentionally preserves the previous destination.
      if (selected) setDestination(selected);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setDestinationError(`Could not open the native save dialog: ${detail}`);
    }
  };

  const exportData = (): void => {
    if (!selectedObject || !format || !destination) return;
    void exportRunner.run(() =>
      ioApi.exportObject({
        object_type: selectedObject.object_type,
        object_name: getObjectName(selectedObject),
        format,
        destination_path: destination.path,
        destination_grant: destination.grant,
      })
    );
  };

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
        <Typography variant="body2" color="text.secondary">
          Export a compatible loaded object through an explicit native destination. Existing files
          are never overwritten, and the backend verifies the written artifact when supported.
        </Typography>
        <Button startIcon={<RefreshIcon />} onClick={onRefresh} disabled={loadingObjects}>
          Refresh
        </Button>
      </Stack>
      {objectsError ? <Alert severity="error">{objectsError}</Alert> : null}
      {catalog ? <ExportCapabilitySummary catalog={catalog} /> : null}
      {loadingObjects ? (
        <Alert severity="info" icon={<CircularProgress size={18} />}>
          Loading compatible objects…
        </Alert>
      ) : objects.length === 0 ? (
        <Alert severity="info">No compatible loaded objects are available to export.</Alert>
      ) : (
        <Stack spacing={2}>
          <Grid container spacing={2}>
            <Grid item xs={12} md={7}>
              <FormControl fullWidth size="small">
                <InputLabel id="export-object-label">Loaded object</InputLabel>
                <Select
                  labelId="export-object-label"
                  label="Loaded object"
                  value={objectKey}
                  onChange={(event) => selectObject(event.target.value)}
                >
                  {objects.map((object) => (
                    <MenuItem
                      key={getObjectKey(object)}
                      value={getObjectKey(object)}
                      disabled={!object.exportable}
                    >
                      {getObjectName(object)} ({object.object_type.replace(/_/g, ' ')})
                      {!object.exportable && object.reason ? ` — ${object.reason}` : ''}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={5}>
              <FormControl fullWidth size="small" disabled={formats.length === 0}>
                <InputLabel id="export-format-label">Format</InputLabel>
                <Select
                  labelId="export-format-label"
                  label="Format"
                  value={format}
                  onChange={(event) => selectFormat(event.target.value as UtilityExportFormat)}
                >
                  {formats.map((supportedFormat) => (
                    <MenuItem key={supportedFormat} value={supportedFormat}>
                      {supportedFormat.toUpperCase()}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          </Grid>
          {formats.length === 0 ? (
            <Alert severity="warning">The selected object has no verified export format.</Alert>
          ) : null}
          {selectedCapability ? (
            <Alert severity={format === 'csv' ? 'warning' : 'info'}>
              <strong>{format.toUpperCase()} scientific-data behavior:</strong>{' '}
              {selectedCapability.notes}
            </Alert>
          ) : null}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <TextField
              fullWidth
              size="small"
              label="Destination"
              value={destination?.path ?? ''}
              placeholder="Choose a new destination with the native dialog"
              InputProps={{ readOnly: true }}
            />
            <Button
              variant="outlined"
              startIcon={<SaveAltIcon />}
              onClick={() => void chooseDestination()}
              disabled={!selectedObject || !format || exportRunner.running}
            >
              Choose destination
            </Button>
          </Stack>
          {destinationError ? <Alert severity="error">{destinationError}</Alert> : null}
          <Box>
            <Button
              variant="contained"
              disabled={!selectedObject || !format || !destination || exportRunner.running}
              onClick={exportData}
            >
              <LoadingButtonContent loading={exportRunner.running} idle="Export" busy="Exporting…" />
            </Button>
          </Box>
          {exportRunner.error ? <Alert severity="error">{exportRunner.error}</Alert> : null}
          <UtilityWarnings warnings={exportRunner.warnings} />
          {exportRunner.result ? (
            <Stack spacing={2} aria-label="Export result">
              <Alert severity="success">
                Exported to {exportRunner.result.path}
              </Alert>
              <SummaryGrid
                values={[
                  { label: 'Format', value: exportRunner.result.format.toUpperCase() },
                  { label: 'File size', value: formatBytes(exportRunner.result.bytes) },
                  {
                    label: 'Rows / events',
                    value: formatMaybe(
                      exportRunner.result.row_count
                    ),
                  },
                  { label: 'Reopened / verified', value: exportRunner.result.verified ? 'Yes' : 'No' },
                ]}
              />
              <UtilityWarnings warnings={exportRunner.result.warnings} />
              <ProvenancePanel provenance={exportRunner.result.provenance} />
            </Stack>
          ) : null}
        </Stack>
      )}
    </Stack>
  );
};

const IOPage: React.FC = () => {
  const [tab, setTab] = useState(0);
  const [fileSelection, setFileSelection] = useState<GrantedFileSelection | null>(null);
  const [rmfSelection, setRmfSelection] = useState<GrantedFileSelection | null>(null);
  const [catalog, setCatalog] = useState<ExportableObjectsResult | null>(null);
  const [loadingObjects, setLoadingObjects] = useState(true);
  const [objectsError, setObjectsError] = useState<string | null>(null);
  const [refreshSequence, setRefreshSequence] = useState(0);

  useEffect(() => {
    let active = true;
    setLoadingObjects(true);
    setObjectsError(null);
    void ioApi
      .listExportableObjects()
      .then((response) => {
        if (!active) return;
        if (response.success && response.data) {
          setCatalog(response.data);
          setObjectsError(null);
        } else {
          setObjectsError(
            response.error ?? response.message ?? 'Could not list exportable objects'
          );
        }
        setLoadingObjects(false);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setObjectsError(error instanceof Error ? error.message : 'Could not list exportable objects');
        setLoadingObjects(false);
      });
    return () => {
      active = false;
    };
  }, [refreshSequence]);

  const eventLists = useMemo(
    () => (catalog?.objects ?? EMPTY_EXPORTABLE_OBJECTS).filter(
      (object) => object.object_type === 'event_list'
    ),
    [catalog]
  );

  return (
    <PageTemplate
      title="General I/O Functionality"
      description="Inspect local scientific files, apply precise RMF calibration, and safely export loaded data."
      category="Utilities"
      status="ready"
    >
      <Alert severity="info" sx={{ mb: 2 }}>
        This workbench inspects and converts data already available to the app. To load a new
        EventList or Lightcurve, go to{' '}
        <Link component={RouterLink} to="/data-ingestion">
          Data Ingestion
        </Link>
        .
      </Alert>
      <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
        <Tabs
          value={tab}
          onChange={(_event, value: number) => setTab(value)}
          aria-label="General I/O operations"
          variant="scrollable"
          scrollButtons="auto"
          sx={{ borderBottom: 1, borderColor: 'divider', px: 1 }}
        >
          <Tab id="io-tab-0" aria-controls="io-panel-0" label="File inspector" />
          <Tab id="io-tab-1" aria-controls="io-panel-1" label="RMF utilities" />
          <Tab id="io-tab-2" aria-controls="io-panel-2" label="Export / conversion" />
        </Tabs>
        <Box sx={{ p: { xs: 2, md: 3 } }}>
          <Box
            id="io-panel-0"
            role="tabpanel"
            aria-labelledby="io-tab-0"
            hidden={tab !== 0}
          >
            <FileInspectorPanel
              selection={fileSelection}
              onSelectionChange={setFileSelection}
            />
          </Box>
          <Box
            id="io-panel-1"
            role="tabpanel"
            aria-labelledby="io-tab-1"
            hidden={tab !== 1}
          >
            <RmfPanel
              rmfSelection={rmfSelection}
              onRmfSelectionChange={setRmfSelection}
              eventLists={eventLists}
              onEventListSaved={() => setRefreshSequence((value) => value + 1)}
            />
          </Box>
          <Box
            id="io-panel-2"
            role="tabpanel"
            aria-labelledby="io-tab-2"
            hidden={tab !== 2}
          >
            <ExportPanel
              catalog={catalog}
              loadingObjects={loadingObjects}
              objectsError={objectsError}
              onRefresh={() => setRefreshSequence((value) => value + 1)}
            />
          </Box>
        </Box>
      </Paper>
    </PageTemplate>
  );
};

export default IOPage;
