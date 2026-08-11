import React from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { useQuery } from '@tanstack/react-query';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import EventListSelector from '@/components/analysis/EventListSelector';
import PlotlyChart from '@/components/plots/PlotlyChart';
import {
  NumericResultTable,
  ProvenancePanel,
  UtilityWarnings,
  type ResultColumn,
  type ResultCell,
} from '@/components/utilities/UtilityResult';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import {
  miscApi,
  type BaselineData,
  type EnergyRangesData,
  type MiscCapabilities,
  type NamedPlotPreview,
  type NearestPowerOfTwoData,
  type NullableNumber,
  type OptimalBinTimeData,
  type PoissonErrorData,
  type RebinData,
  type SegmentSizeData,
  type StandardErrorData,
  type UtilityData,
  type WindowData,
} from '@/api/miscApi';
import {
  parseNumericArray,
  parseNumericMatrix,
  parsePositiveInteger,
} from '@/utils/utilityInputs';
import { parseNumber, parsePositiveNumber } from '@/utils/numbers';

type MainTab = 'rebin' | 'baseline' | 'window' | 'sampling' | 'errors' | 'energy';
type RebinMode = 'linear' | 'logarithmic';
type SamplingMode = 'optimal' | 'power' | 'segment';
type ErrorMode = 'poisson' | 'standard';

const MAIN_TABS: Array<{ value: MainTab; label: string }> = [
  { value: 'rebin', label: 'Rebinning' },
  { value: 'baseline', label: 'Baseline' },
  { value: 'window', label: 'Windows' },
  { value: 'sampling', label: 'Sampling' },
  { value: 'errors', label: 'Errors' },
  { value: 'energy', label: 'Energy ranges' },
];

const SERIES_COLUMNS: ResultColumn[] = [
  { key: 'index', label: 'Index' },
  { key: 'x', label: 'x', unit: 'input x unit' },
  { key: 'y', label: 'y', unit: 'input y unit' },
  { key: 'yError', label: '1σ uncertainty', unit: 'input y unit' },
  { key: 'samples', label: 'Samples/bin' },
];

interface OptionalNumberResult {
  value: number | null;
  error: string | null;
}

function parseOptionalNumber(text: string, label: string): OptionalNumberResult {
  if (text.trim() === '') return { value: null, error: null };
  const value = parseNumber(text);
  return value === null
    ? { value: null, error: `${label} must be a finite number` }
    : { value, error: null };
}

function numberUlp(value: number): number {
  const magnitude = Math.abs(value);
  if (magnitude === 0) return Number.MIN_VALUE;
  const exponent = Math.floor(Math.log2(magnitude));
  return Math.max(Number.MIN_VALUE, 2 ** (exponent - 52));
}

function matchesUniformSpacing(values: number[], spacing: number): boolean {
  const ordinaryTolerance =
    1e-10 * Math.abs(spacing) + 16 * Number.EPSILON * Math.max(1, Math.abs(spacing));
  return values.slice(1).every((value, index) => {
    const observed = value - values[index];
    const endpointRoundoff = 0.5 * (numberUlp(value) + numberUlp(values[index]));
    const subtractionRoundoff = 0.5 * numberUlp(observed);
    return (
      Math.abs(observed - spacing) <=
      Math.max(ordinaryTolerance, endpointRoundoff + subtractionRoundoff)
    );
  });
}

function nullableAt(values: NullableNumber[] | undefined, index: number): NullableNumber {
  return values?.[index] ?? null;
}

function samplesAt(
  samples: RebinData['rebinned']['samples_per_bin'],
  index: number
): NullableNumber {
  return Array.isArray(samples) ? (samples[index] ?? null) : samples;
}

function previewValues(preview: NamedPlotPreview, key: string): NullableNumber[] {
  return preview.values[key] ?? [];
}

function buildSeriesRows(series: RebinData['original'] | RebinData['rebinned']): Array<Record<string, ResultCell>> {
  return series.x.map((x, index) => ({
    index,
    x,
    y: nullableAt(series.y, index),
    yError: nullableAt(series.y_error ?? undefined, index),
    samples: 'samples_per_bin' in series ? samplesAt(series.samples_per_bin, index) : null,
  }));
}

function WorkbenchPanel({
  active,
  value,
  children,
}: {
  active: boolean;
  value: MainTab;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <Box
      role="tabpanel"
      id={`misc-panel-${value}`}
      aria-labelledby={`misc-tab-${value}`}
      hidden={!active}
      sx={{ pt: 3 }}
    >
      {children}
    </Box>
  );
}

function ParameterCard({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>{children}</Stack>
      </CardContent>
    </Card>
  );
}

function RunButton({
  running,
  disabled,
  children,
  onClick,
}: {
  running: boolean;
  disabled: boolean;
  children: React.ReactNode;
  onClick: () => void;
}): React.ReactElement {
  return (
    <Button
      variant="contained"
      startIcon={
        running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />
      }
      disabled={disabled || running}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}

function ResultCard<T extends UtilityData>({
  result,
  running,
  error,
  warnings,
  emptyText,
  children,
}: {
  result: T | null;
  running: boolean;
  error: string | null;
  warnings?: string[];
  emptyText: string;
  children: (value: T) => React.ReactNode;
}): React.ReactElement {
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Box>
            <Typography variant="subtitle2">Result</Typography>
            {running && result ? (
              <Typography variant="caption" color="text.secondary">
                Updating; the last successful result remains visible.
              </Typography>
            ) : null}
          </Box>
          {error ? <Alert severity="error">{error}</Alert> : null}
          <UtilityWarnings warnings={warnings} />
          {result ? (
            <>
              <UtilityWarnings warnings={result.warnings} />
              {children(result)}
              <ProvenancePanel
                provenance={result.provenance as unknown as Record<string, unknown>}
              />
            </>
          ) : (
            <Box sx={{ py: { xs: 5, md: 9 }, textAlign: 'center' }}>
              {running ? <CircularProgress size={28} sx={{ mb: 2 }} /> : null}
              <Typography color="text.secondary">{emptyText}</Typography>
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

function RebinWorkbench({ capabilities }: { capabilities?: MiscCapabilities }): React.ReactElement {
  const [mode, setMode] = React.useState<RebinMode>('linear');
  const [xText, setXText] = React.useState('');
  const [yText, setYText] = React.useState('');
  const [errorText, setErrorText] = React.useState('');
  const [resolution, setResolution] = React.useState('2');
  const [factor, setFactor] = React.useState('0.1');
  const [oldResolution, setOldResolution] = React.useState('');
  const [method, setMethod] = React.useState<'sum' | 'mean'>('sum');
  const linearRunner = useAnalysisRunner<RebinData>('Linear rebinning');
  const logarithmicRunner = useAnalysisRunner<RebinData>('Logarithmic rebinning');
  const activeRunner = mode === 'linear' ? linearRunner : logarithmicRunner;
  const maxValues = capabilities?.limits.max_array_values;
  const x = React.useMemo(
    () => parseNumericArray(xText, 'x values', maxValues),
    [xText, maxValues]
  );
  const y = React.useMemo(
    () => parseNumericArray(yText, 'y values', maxValues),
    [yText, maxValues]
  );
  const yError = React.useMemo(
    () =>
      errorText.trim() === ''
        ? { value: null, error: null }
        : parseNumericArray(errorText, 'Uncertainties', maxValues),
    [errorText, maxValues]
  );
  const dx = parseOptionalNumber(oldResolution, 'Original dx');
  const targetResolution = parsePositiveNumber(resolution);
  const growth = parsePositiveNumber(factor);

  let validationError = !capabilities ? 'Runtime capabilities are loading' : x.error ?? y.error;
  if (!validationError && x.value && x.value.length < 2) validationError = 'x needs at least two values';
  if (!validationError && y.value && y.value.length < 2) validationError = 'y needs at least two values';
  if (!validationError && x.value && y.value && x.value.length !== y.value.length) {
    validationError = 'x, y and optional uncertainties must have equal lengths';
  }
  if (!validationError && x.value) {
    const bad = x.value.findIndex((value, index) => index > 0 && value <= x.value![index - 1]);
    if (bad >= 0) validationError = `x must be strictly increasing (problem at value ${bad + 1})`;
    if (mode === 'logarithmic' && x.value.some((value) => value <= 0)) {
      validationError = 'Logarithmic rebinning requires positive x values';
    }
  }
  if (!validationError && yError.error) validationError = yError.error;
  if (!validationError && yError.value && x.value && yError.value.length !== x.value.length) {
    validationError = 'x, y and optional uncertainties must have equal lengths';
  }
  if (!validationError && yError.value?.some((value) => value < 0)) {
    validationError = 'Uncertainties must be non-negative';
  }
  if (!validationError && dx.error) validationError = dx.error;
  if (!validationError && dx.value !== null && dx.value <= 0) {
    validationError = 'Original dx must be positive';
  }
  if (!validationError && mode === 'linear' && targetResolution === null) {
    validationError = 'New dx must be a positive number';
  }
  if (!validationError && mode === 'linear' && targetResolution !== null && x.value) {
    const observedSpacing = x.value.slice(1).map((value, index) => value - x.value![index]);
    let requiredSpacing =
      dx.value ?? [...observedSpacing].sort((left, right) => left - right)[Math.floor(observedSpacing.length / 2)];
    let largestSpacing = dx.value ?? 0;
    if (dx.value === null) {
      for (const spacing of observedSpacing) largestSpacing = Math.max(largestSpacing, spacing);
    }
    if (targetResolution < largestSpacing) {
      validationError = 'New dx must be at least as large as every input resolution';
    } else {
      const tailResolution = dx.value ?? observedSpacing[observedSpacing.length - 1];
      const coveredSpan =
        tailResolution === undefined
          ? Number.NaN
          : x.value[x.value.length - 1] - x.value[0] + tailResolution;
      const spanTolerance =
        8 * Number.EPSILON * Math.max(1, Math.abs(coveredSpan), Math.abs(targetResolution));
      if (!Number.isFinite(coveredSpan) || coveredSpan <= 0) {
        validationError = 'The covered input span must be a positive finite number';
      } else if (targetResolution > coveredSpan + spanTolerance) {
        validationError = `New dx is wider than the covered input span (${coveredSpan.toPrecision(8)}), so no complete output bin fits`;
      }
    }
    if (!validationError && yError.value && requiredSpacing !== undefined) {
      if (!matchesUniformSpacing(x.value, requiredSpacing)) {
        validationError = 'Linear uncertainty propagation requires uniform x spacing; an explicit dx must match that spacing';
      } else {
        const nearestFactor = Math.round(targetResolution / requiredSpacing);
        if (nearestFactor >= 1) {
          const candidateSpacing = targetResolution / nearestFactor;
          if (matchesUniformSpacing(x.value, candidateSpacing)) requiredSpacing = candidateSpacing;
        }
        const ratio = targetResolution / requiredSpacing;
        if (Math.abs(ratio - Math.round(ratio)) > 1e-10 * Math.max(1, Math.abs(ratio))) {
          validationError = 'Linear uncertainty propagation requires an integer new dx / original dx ratio; fractional-overlap errors are unsupported in Stingray 2.2.10';
        }
      }
    }
  }
  if (!validationError && mode === 'logarithmic' && growth === null) {
    validationError = 'Growth factor must be a positive number';
  }

  const handleRun = (): void => {
    if (validationError || !x.value || !y.value) return;
    if (mode === 'linear' && targetResolution !== null) {
      void linearRunner.run(() =>
        miscApi.linearRebin({
          x: x.value!,
          y: y.value!,
          dx_new: targetResolution,
          y_error: yError.value,
          method,
          dx: dx.value,
        })
      );
    } else if (mode === 'logarithmic' && growth !== null) {
      void logarithmicRunner.run(() =>
        miscApi.logarithmicRebin({
          x: x.value!,
          y: y.value!,
          factor: growth,
          y_error: yError.value,
          dx: dx.value,
        })
      );
    }
  };

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={4} lg={3}>
        <ParameterCard>
          <Typography variant="subtitle2">Rebin parameters</Typography>
          <FormControl size="small" fullWidth>
            <InputLabel id="rebin-mode-label">Rebin mode</InputLabel>
            <Select
              labelId="rebin-mode-label"
              label="Rebin mode"
              value={mode}
              onChange={(event) => setMode(event.target.value as RebinMode)}
            >
              <MenuItem value="linear">Linear</MenuItem>
              <MenuItem value="logarithmic">Logarithmic</MenuItem>
            </Select>
          </FormControl>
          <TextField
            label="x values"
            value={xText}
            onChange={(event) => setXText(event.target.value)}
            multiline
            minRows={3}
            size="small"
            placeholder="0.5, 1.5, 2.5, 3.5"
            helperText="Comma, whitespace or newline separated; strictly increasing."
          />
          <TextField
            label="y values"
            value={yText}
            onChange={(event) => setYText(event.target.value)}
            multiline
            minRows={3}
            size="small"
            placeholder="2, 4, 6, 8"
            helperText="Same length as x."
          />
          <TextField
            label="1σ uncertainties (optional)"
            value={errorText}
            onChange={(event) => setErrorText(event.target.value)}
            multiline
            minRows={2}
            size="small"
            helperText="Independent, non-negative standard uncertainties in y units."
          />
          {mode === 'linear' ? (
            <>
              <TextField
                label="New dx"
                value={resolution}
                onChange={(event) => setResolution(event.target.value)}
                size="small"
                helperText="Same units as x; must not be finer than the input resolution."
              />
              <FormControl size="small" fullWidth>
                <InputLabel id="linear-method-label">Aggregation</InputLabel>
                <Select
                  labelId="linear-method-label"
                  label="Aggregation"
                  value={capabilities ? method : ''}
                  disabled={!capabilities}
                  onChange={(event) => setMethod(event.target.value as 'sum' | 'mean')}
                >
                  {(capabilities?.rebin.linear_methods ?? []).map((value) => (
                    <MenuItem key={value} value={value}>{value}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </>
          ) : (
            <TextField
              label="Fractional growth factor"
              value={factor}
              onChange={(event) => setFactor(event.target.value)}
              size="small"
              helperText="Positive f; output widths grow by 1 + f. Log rebinning always averages."
            />
          )}
          <TextField
            label="Original dx (optional)"
            value={oldResolution}
            onChange={(event) => setOldResolution(event.target.value)}
            size="small"
            helperText="Leave blank to infer spacing from x."
          />
          {validationError && (xText !== '' || yText !== '') ? (
            <Alert severity="error">{validationError}</Alert>
          ) : null}
          <RunButton running={activeRunner.running} disabled={Boolean(validationError)} onClick={handleRun}>
            Rebin data
          </RunButton>
        </ParameterCard>
        {capabilities?.rebin.linear_uncertainty_workaround_required ? (
          <Alert severity="warning" sx={{ mt: 2 }}>
            <strong>Stingray 2.2.10 linear-error workaround:</strong> standard uncertainties are
            squared before the installed linear helper and reported as quadrature 1σ errors. The
            response records this compatibility path and upstream reference{' '}
            {capabilities.rebin.linear_uncertainty_workaround_reference}. Supported domain:{' '}
            {capabilities.rebin.linear_uncertainty_support}.
          </Alert>
        ) : null}
      </Grid>
      <Grid item xs={12} md={8} lg={9}>
        <ResultCard
          {...activeRunner}
          emptyText="Paste aligned x/y arrays, choose a rebinning rule and compute."
        >
          {(result) => {
            const original = result.plot_preview.original;
            const rebinned = result.plot_preview.rebinned;
            const traces: Data[] = [
              {
                x: previewValues(original, 'x'),
                y: previewValues(original, 'y'),
                type: 'scattergl',
                mode: 'lines+markers',
                name: 'Original',
              } as Data,
              {
                x: previewValues(rebinned, 'x'),
                y: previewValues(rebinned, 'y'),
                type: 'scattergl',
                mode: 'lines+markers',
                name: 'Rebinned',
              } as Data,
            ];
            return (
              <>
                <Alert severity="info">
                  x and every dx use the same input unit. Mean preserves y units; sum reports the
                  summed y quantity. {result.error_semantics ?? 'No uncertainties were supplied.'}
                </Alert>
                <PlotlyChart
                  data={traces}
                  layout={{
                    showlegend: true,
                    xaxis: { title: { text: 'x (input units)' } },
                    yaxis: { title: { text: 'y (input units)' } },
                  }}
                />
                <Grid container spacing={2}>
                  <Grid item xs={12} lg={6}>
                    <NumericResultTable
                      title="Original exact values"
                      columns={SERIES_COLUMNS.slice(0, 4)}
                      rows={buildSeriesRows(result.original)}
                    />
                  </Grid>
                  <Grid item xs={12} lg={6}>
                    <NumericResultTable
                      title="Rebinned exact values"
                      columns={SERIES_COLUMNS}
                      rows={buildSeriesRows(result.rebinned)}
                    />
                  </Grid>
                </Grid>
              </>
            );
          }}
        </ResultCard>
      </Grid>
    </Grid>
  );
}

function BaselineWorkbench({ capabilities }: { capabilities?: MiscCapabilities }): React.ReactElement {
  const [xText, setXText] = React.useState('');
  const [yText, setYText] = React.useState('');
  const [lambda, setLambda] = React.useState('100000000000');
  const [asymmetry, setAsymmetry] = React.useState('0.001');
  const [iterations, setIterations] = React.useState('10');
  const [offsetCorrection, setOffsetCorrection] = React.useState(false);
  const runner = useAnalysisRunner<BaselineData>('Baseline estimation');
  const maxValues = capabilities?.limits.max_array_values;
  const x = React.useMemo(
    () => parseNumericArray(xText, 'x values', maxValues),
    [xText, maxValues]
  );
  const y = React.useMemo(
    () => parseNumericArray(yText, 'y values', maxValues),
    [yText, maxValues]
  );
  const smoothing = parsePositiveNumber(lambda);
  const probability = parseNumber(asymmetry);
  const iterationCount = parsePositiveInteger(iterations);
  let validationError = !capabilities ? 'Runtime capabilities are loading' : x.error ?? y.error;
  if (!validationError && x.value && x.value.length < 3) validationError = 'At least three x/y points are required';
  if (!validationError && x.value && y.value && x.value.length !== y.value.length) validationError = 'x and y must have equal lengths';
  if (!validationError && x.value?.some((value, index) => index > 0 && value <= x.value![index - 1])) validationError = 'x must be strictly increasing';
  if (!validationError && smoothing === null) validationError = 'Lambda must be positive';
  if (!validationError && (probability === null || probability <= 0 || probability >= 1)) validationError = 'Asymmetry must be strictly between 0 and 1';
  if (!validationError && (iterationCount === null || iterationCount > capabilities!.limits.max_baseline_iterations)) validationError = `Iterations must be an integer from 1 to ${capabilities!.limits.max_baseline_iterations}`;

  const handleRun = (): void => {
    if (validationError || !x.value || !y.value || smoothing === null || probability === null || iterationCount === null) return;
    void runner.run(() => miscApi.estimateBaseline({
      x: x.value!,
      y: y.value!,
      lam: smoothing,
      asymmetry: probability,
      iterations: iterationCount,
      offset_correction: offsetCorrection,
    }));
  };

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={4} lg={3}>
        <ParameterCard>
          <Typography variant="subtitle2">Asymmetric least squares</Typography>
          <Typography variant="body2" color="text.secondary">
            Estimates a slowly varying baseline, then returns both the fitted baseline and
            baseline-subtracted series.
          </Typography>
          <TextField label="x values" value={xText} onChange={(event) => setXText(event.target.value)} multiline minRows={3} size="small" helperText="Strictly increasing; arbitrary x units." />
          <TextField label="y values" value={yText} onChange={(event) => setYText(event.target.value)} multiline minRows={3} size="small" helperText="Same length and units as the measured series." />
          <TextField label="Lambda (smoothness)" value={lambda} onChange={(event) => setLambda(event.target.value)} size="small" helperText="Positive; larger values produce a smoother baseline." />
          <TextField label="Asymmetry p" value={asymmetry} onChange={(event) => setAsymmetry(event.target.value)} size="small" helperText="Dimensionless and strictly between 0 and 1." />
          <TextField label="Iterations" value={iterations} onChange={(event) => setIterations(event.target.value)} size="small" helperText={`Integer; runtime cap ${capabilities?.limits.max_baseline_iterations ?? '…'}.`} />
          <FormControlLabel control={<Checkbox checked={offsetCorrection} onChange={(event) => setOffsetCorrection(event.target.checked)} />} label="Apply Stingray offset correction" />
          {validationError && (xText !== '' || yText !== '') ? <Alert severity="error">{validationError}</Alert> : null}
          <RunButton running={runner.running} disabled={Boolean(validationError)} onClick={handleRun}>Estimate baseline</RunButton>
        </ParameterCard>
      </Grid>
      <Grid item xs={12} md={8} lg={9}>
        <ResultCard {...runner} emptyText="Paste a series to estimate its asymmetric least-squares baseline.">
          {(result) => {
            const values = result.plot_preview.values;
            const rows = result.x.map((value, index) => ({ index, x: value, original: result.original[index], baseline: result.baseline[index], corrected: result.corrected[index] }));
            return (
              <>
                <Alert severity="info">x keeps the supplied x unit. Original, baseline and corrected values all share the supplied y unit; corrected = original − baseline.</Alert>
                <PlotlyChart data={[
                  { x: values.x ?? [], y: values.original ?? [], type: 'scattergl', mode: 'lines', name: 'Original' } as Data,
                  { x: values.x ?? [], y: values.baseline ?? [], type: 'scattergl', mode: 'lines', name: 'Baseline' } as Data,
                  { x: values.x ?? [], y: values.corrected ?? [], type: 'scattergl', mode: 'lines', name: 'Corrected' } as Data,
                ]} layout={{ showlegend: true, xaxis: { title: { text: 'x (input units)' } }, yaxis: { title: { text: 'y (input units)' } } }} />
                <NumericResultTable title="Exact baseline result" columns={[
                  { key: 'index', label: 'Index' }, { key: 'x', label: 'x' }, { key: 'original', label: 'Original' }, { key: 'baseline', label: 'Baseline' }, { key: 'corrected', label: 'Corrected' },
                ]} rows={rows} />
              </>
            );
          }}
        </ResultCard>
      </Grid>
    </Grid>
  );
}

function WindowWorkbench({ capabilities }: { capabilities?: MiscCapabilities }): React.ReactElement {
  const [sampleCount, setSampleCount] = React.useState('64');
  const [windowType, setWindowType] = React.useState('');
  const runner = useAnalysisRunner<WindowData>('Window generation');
  React.useEffect(() => {
    if (!windowType && capabilities?.window_types.length) setWindowType(capabilities.window_types[0]);
  }, [capabilities, windowType]);
  const count = parsePositiveInteger(sampleCount);
  const cap = capabilities?.limits.max_exact_output_values;
  const validationError = !capabilities
    ? 'Runtime window capabilities are loading'
    : count === null || count < 2 || count > cap!
      ? `Sample count must be an integer from 2 to ${cap!.toLocaleString()}`
      : !capabilities.window_types.includes(windowType)
        ? 'Choose a window exposed by the installed Stingray runtime'
        : null;
  const handleRun = (): void => {
    if (validationError || count === null) return;
    void runner.run(() => miscApi.generateWindow({ n_samples: count, window_type: windowType }));
  };
  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={4} lg={3}>
        <ParameterCard>
          <Typography variant="subtitle2">Analysis window</Typography>
          <Typography variant="body2" color="text.secondary">The allowlist below comes from the installed public Stingray implementation, including its exact spellings.</Typography>
          <TextField label="Sample count N" value={sampleCount} onChange={(event) => setSampleCount(event.target.value)} size="small" helperText="Dimensionless sample count; N ≥ 2." />
          <FormControl size="small" fullWidth disabled={!capabilities}>
            <InputLabel id="window-type-label">Window type</InputLabel>
            <Select labelId="window-type-label" label="Window type" value={windowType} onChange={(event) => setWindowType(event.target.value)}>
              {(capabilities?.window_types ?? []).map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
            </Select>
          </FormControl>
          {validationError && capabilities ? <Alert severity="error">{validationError}</Alert> : null}
          <RunButton running={runner.running} disabled={Boolean(validationError)} onClick={handleRun}>Generate window</RunButton>
        </ParameterCard>
      </Grid>
      <Grid item xs={12} md={8} lg={9}>
        <ResultCard {...runner} emptyText="Choose a runtime-supported window and generate its coefficients.">
          {(result) => {
            const rows = result.sample_index.map((index, position) => ({ index, coefficient: result.window[position] }));
            const summaryRows = Object.entries(result.summary).map(([metric, value]) => ({ metric, value }));
            return (
              <>
                <Alert severity="info">Sample index and coefficients are dimensionless. ENBW is reported in FFT-bin units; coherent gain is the coefficient mean.</Alert>
                <PlotlyChart data={[{ x: previewValues(result.plot_preview, 'sample_index'), y: previewValues(result.plot_preview, 'window'), type: 'scattergl', mode: 'lines', name: result.window_type } as Data]} layout={{ xaxis: { title: { text: 'Sample index' } }, yaxis: { title: { text: 'Window coefficient' } } }} />
                <Grid container spacing={2}>
                  <Grid item xs={12} lg={5}><NumericResultTable title="Window summary" columns={[{ key: 'metric', label: 'Metric' }, { key: 'value', label: 'Value' }]} rows={summaryRows} /></Grid>
                  <Grid item xs={12} lg={7}><NumericResultTable title="Exact coefficients" columns={[{ key: 'index', label: 'Sample index' }, { key: 'coefficient', label: 'Coefficient' }]} rows={rows} /></Grid>
                </Grid>
              </>
            );
          }}
        </ResultCard>
      </Grid>
    </Grid>
  );
}

function SamplingWorkbench({ capabilities }: { capabilities?: MiscCapabilities }): React.ReactElement {
  const [mode, setMode] = React.useState<SamplingMode>('optimal');
  const [fftLength, setFftLength] = React.useState('512');
  const [proposedBinTime, setProposedBinTime] = React.useState('2.1');
  const [powerValue, setPowerValue] = React.useState('6');
  const [segmentSize, setSegmentSize] = React.useState('10.1');
  const [dt, setDt] = React.useState('1');
  const [tolerance, setTolerance] = React.useState('0.01');
  type SamplingResult = OptimalBinTimeData | NearestPowerOfTwoData | SegmentSizeData;
  const optimalRunner = useAnalysisRunner<SamplingResult>('Optimal FFT bin time');
  const powerRunner = useAnalysisRunner<SamplingResult>('Nearest power of two');
  const segmentRunner = useAnalysisRunner<SamplingResult>('Segment-size adjustment');
  const fft = parsePositiveNumber(fftLength);
  const proposed = parsePositiveNumber(proposedBinTime);
  const requestedPower = parsePositiveInteger(powerValue);
  const requestedSegment = parsePositiveNumber(segmentSize);
  const sampleTime = parsePositiveNumber(dt);
  const toleranceValue = parseNumber(tolerance);
  let validationError: string | null = !capabilities ? 'Runtime capabilities are loading' : null;
  if (!validationError && mode === 'optimal') {
    if (fft === null || proposed === null) validationError = 'FFT length and proposed bin time must be positive';
    else if (proposed > fft) validationError = 'Proposed bin time must not exceed FFT length';
    else if (fft / proposed > capabilities!.limits.max_fft_samples) validationError = 'Requested FFT exceeds the runtime sample cap';
  } else if (!validationError && mode === 'power') {
    if (requestedPower === null || requestedPower < 2 || requestedPower > capabilities!.limits.max_fft_samples) validationError = `Value must be an integer from 2 to ${capabilities!.limits.max_fft_samples.toLocaleString()}`;
  } else if (!validationError && mode === 'segment') {
    if (requestedSegment === null || sampleTime === null) validationError = 'Segment size and dt must be positive';
    else if (requestedSegment < sampleTime) validationError = 'Segment size must be at least one dt';
    else if (requestedSegment / sampleTime > capabilities!.limits.max_fft_samples) validationError = 'Segment exceeds the runtime sample cap';
    else if (toleranceValue === null || toleranceValue < 0 || toleranceValue >= 1) validationError = 'Tolerance must be at least 0 and less than 1';
  }

  const handleRun = (): void => {
    if (validationError) return;
    if (mode === 'optimal' && fft !== null && proposed !== null) void optimalRunner.run(() => miscApi.optimalBinTime({ fft_length: fft, proposed_bin_time: proposed }));
    if (mode === 'power' && requestedPower !== null) void powerRunner.run(() => miscApi.nearestPowerOfTwo({ value: requestedPower }));
    if (mode === 'segment' && requestedSegment !== null && sampleTime !== null && toleranceValue !== null) void segmentRunner.run(() => miscApi.adjustSegmentSize({ segment_size: requestedSegment, dt: sampleTime, tolerance: toleranceValue }));
  };
  const activeRunner = mode === 'optimal' ? optimalRunner : mode === 'power' ? powerRunner : segmentRunner;
  const resultRows = activeRunner.result
    ? mode === 'optimal'
      ? [{ requested: (activeRunner.result as OptimalBinTimeData).requested_bin_time, adjusted: (activeRunner.result as OptimalBinTimeData).adjusted_bin_time, samples: (activeRunner.result as OptimalBinTimeData).sample_count, delta: (activeRunner.result as OptimalBinTimeData).delta, fractionalChange: (activeRunner.result as OptimalBinTimeData).fractional_change }]
      : mode === 'power'
        ? [{ requested: (activeRunner.result as NearestPowerOfTwoData).requested_value, adjusted: (activeRunner.result as NearestPowerOfTwoData).nearest_power_of_two, delta: (activeRunner.result as NearestPowerOfTwoData).delta, fractionalChange: (activeRunner.result as NearestPowerOfTwoData).fractional_change }]
        : [{ requested: (activeRunner.result as SegmentSizeData).requested_segment_size, adjusted: (activeRunner.result as SegmentSizeData).adjusted_segment_size, samples: (activeRunner.result as SegmentSizeData).sample_count, delta: (activeRunner.result as SegmentSizeData).delta, fractionalChange: (activeRunner.result as SegmentSizeData).fractional_change }]
    : [];
  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={4} lg={3}>
        <ParameterCard>
          <Typography variant="subtitle2">Sampling and binning</Typography>
          <FormControl size="small" fullWidth>
            <InputLabel id="sampling-operation-label">Sampling operation</InputLabel>
            <Select labelId="sampling-operation-label" label="Sampling operation" value={mode} onChange={(event) => setMode(event.target.value as SamplingMode)}>
              <MenuItem value="optimal">Optimal FFT bin time</MenuItem>
              <MenuItem value="power">Nearest power of two</MenuItem>
              <MenuItem value="segment">Integer-sample segment</MenuItem>
            </Select>
          </FormControl>
          {mode === 'optimal' ? <>
            <TextField label="FFT length" value={fftLength} onChange={(event) => setFftLength(event.target.value)} size="small" helperText="Duration/span in the chosen time unit." />
            <TextField label="Proposed bin time" value={proposedBinTime} onChange={(event) => setProposedBinTime(event.target.value)} size="small" helperText="Same time unit as FFT length." />
          </> : null}
          {mode === 'power' ? <TextField label="Integer value" value={powerValue} onChange={(event) => setPowerValue(event.target.value)} size="small" helperText="Dimensionless integer ≥ 2; midpoint ties choose the upper power." /> : null}
          {mode === 'power' && capabilities ? (
            <Alert severity="warning">
              {capabilities.runtime_advisories.nearest_power_of_two}
            </Alert>
          ) : null}
          {mode === 'segment' ? <>
            <TextField label="Requested segment size" value={segmentSize} onChange={(event) => setSegmentSize(event.target.value)} size="small" helperText="Duration in the chosen time unit." />
            <TextField label="Sample time dt" value={dt} onChange={(event) => setDt(event.target.value)} size="small" helperText="Same time unit as segment size." />
            <TextField label="Tolerance" value={tolerance} onChange={(event) => setTolerance(event.target.value)} size="small" helperText="Absolute fraction of one sample; 0 ≤ tolerance < 1." />
          </> : null}
          {validationError && capabilities ? <Alert severity="error">{validationError}</Alert> : null}
          <RunButton running={activeRunner.running} disabled={Boolean(validationError)} onClick={handleRun}>{mode === 'optimal' ? 'Calculate bin time' : mode === 'power' ? 'Find nearest power' : 'Adjust segment'}</RunButton>
        </ParameterCard>
      </Grid>
      <Grid item xs={12} md={8} lg={9}>
        <ResultCard {...activeRunner} emptyText="Choose a sampling helper to see the requested and adjusted values.">
          {(result) => <>
            <Alert severity="info">{mode === 'power' ? 'All values are dimensionless integers.' : 'Requested, adjusted and delta values use the same time unit supplied in the form. Fractional change is dimensionless.'}</Alert>
            <NumericResultTable title="Adjustment result" columns={[{ key: 'requested', label: 'Requested' }, { key: 'adjusted', label: 'Adjusted' }, { key: 'samples', label: 'Sample count' }, { key: 'delta', label: 'Delta' }, { key: 'fractionalChange', label: 'Fractional change' }]} rows={resultRows} />
            {result.changed ? <Typography variant="body2">The requested value was changed; see the warning and signed delta above.</Typography> : <Typography variant="body2">The requested value already satisfies the helper.</Typography>}
          </>}
        </ResultCard>
      </Grid>
    </Grid>
  );
}

function ErrorWorkbench({ capabilities }: { capabilities?: MiscCapabilities }): React.ReactElement {
  const [mode, setMode] = React.useState<ErrorMode>('poisson');
  const [countsText, setCountsText] = React.useState('');
  const [matrixText, setMatrixText] = React.useState('');
  const [meanText, setMeanText] = React.useState('');
  type ErrorResult = PoissonErrorData | StandardErrorData;
  const poissonRunner = useAnalysisRunner<ErrorResult>('Poisson errors');
  const standardRunner = useAnalysisRunner<ErrorResult>('Standard error');
  const maxValues = capabilities?.limits.max_array_values;
  const counts = React.useMemo(() => parseNumericArray(countsText, 'Counts', maxValues), [countsText, maxValues]);
  const matrix = React.useMemo(() => parseNumericMatrix(matrixText), [matrixText]);
  const providedMean = React.useMemo(() => meanText.trim() === '' ? { value: null, error: null } : parseNumericArray(meanText, 'Mean', maxValues), [meanText, maxValues]);
  let validationError: string | null = !capabilities ? 'Runtime capabilities are loading' : null;
  if (!validationError && mode === 'poisson') {
    validationError = counts.error;
    if (!validationError && counts.value?.some((value) => !Number.isInteger(value) || value < 0)) validationError = 'Poisson counts must be non-negative integers';
    if (!validationError && counts.value?.some((value) => value > capabilities!.limits.max_poisson_count)) validationError = `Largest count exceeds the ${capabilities!.limits.max_poisson_count.toLocaleString()} lookup cap`;
  } else if (!validationError) {
    validationError = matrix.error ?? providedMean.error;
    if (!validationError && matrix.value && providedMean.value && matrix.value[0].length !== providedMean.value.length) validationError = `Mean must contain exactly ${matrix.value[0].length} values`;
    if (!validationError && matrix.value && providedMean.value) {
      const arithmeticMean = matrix.value[0].map((_value, column) =>
        matrix.value!.reduce((sum, row) => sum + row[column], 0) / matrix.value!.length
      );
      const mismatch = providedMean.value.findIndex((value, column) => {
        const expected = arithmeticMean[column];
        // Mirror numpy.allclose(rtol=1e-10, atol=1e-12) in the backend,
        // especially around a zero reference mean where relative tolerance
        // alone is not meaningful.
        return Math.abs(value - expected) > 1e-12 + 1e-10 * Math.abs(expected);
      });
      if (mismatch >= 0) {
        validationError = `Reference mean column ${mismatch + 1} must match the arithmetic sample mean; leave it blank to calculate automatically`;
      }
    }
    if (!validationError && matrix.value && matrix.value.length * matrix.value[0].length > capabilities!.limits.max_matrix_cells) validationError = `Matrix exceeds the ${capabilities!.limits.max_matrix_cells.toLocaleString()}-cell cap`;
  }
  const handleRun = (): void => {
    if (validationError) return;
    if (mode === 'poisson' && counts.value) void poissonRunner.run(() => miscApi.poissonErrors({ counts: counts.value! }));
    if (mode === 'standard' && matrix.value) void standardRunner.run(() => miscApi.standardError({ samples: matrix.value!, mean: providedMean.value }));
  };
  const activeRunner = mode === 'poisson' ? poissonRunner : standardRunner;
  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={4} lg={3}>
        <ParameterCard>
          <Typography variant="subtitle2">Statistical error helper</Typography>
          <FormControl size="small" fullWidth>
            <InputLabel id="error-operation-label">Error operation</InputLabel>
            <Select labelId="error-operation-label" label="Error operation" value={mode} onChange={(event) => setMode(event.target.value as ErrorMode)}>
              <MenuItem value="poisson">Poisson symmetrical error</MenuItem>
              <MenuItem value="standard">Column-wise standard error</MenuItem>
            </Select>
          </FormControl>
          {mode === 'poisson' ? <TextField label="Poisson counts" value={countsText} onChange={(event) => setCountsText(event.target.value)} multiline minRows={4} size="small" helperText="Independent, non-negative integer counts." /> : <>
            <TextField label="Sample matrix" value={matrixText} onChange={(event) => setMatrixText(event.target.value)} multiline minRows={5} size="small" placeholder={'1, 2, 3\n2, 4, 6'} helperText="One independent sample per line; every row must have the same columns." />
            <TextField label="Reference mean (optional)" value={meanText} onChange={(event) => setMeanText(event.target.value)} multiline minRows={2} size="small" helperText="Leave blank for the arithmetic column mean. A supplied mean must match it, or the request is rejected." />
          </>}
          {validationError && (countsText !== '' || matrixText !== '') ? <Alert severity="error">{validationError}</Alert> : null}
          <RunButton running={activeRunner.running} disabled={Boolean(validationError)} onClick={handleRun}>{mode === 'poisson' ? 'Calculate Poisson errors' : 'Calculate standard error'}</RunButton>
        </ParameterCard>
      </Grid>
      <Grid item xs={12} md={8} lg={9}>
        <ResultCard {...activeRunner} emptyText="Supply counts or a rectangular sample matrix to calculate errors.">
          {(result) => mode === 'poisson' ? (() => {
            const value = result as PoissonErrorData;
            const rows = value.counts.map((count, index) => ({ index, count, error: value.symmetric_error[index] }));
            return <>
              <Alert severity="info">{value.assumptions} Count and error units are counts; the confidence convention is {value.confidence_sigma}σ.</Alert>
              <PlotlyChart data={[{ x: previewValues(value.plot_preview, 'counts'), y: previewValues(value.plot_preview, 'symmetric_error'), type: 'scattergl', mode: 'markers', name: '1σ error' } as Data]} layout={{ xaxis: { title: { text: 'Observed counts' } }, yaxis: { title: { text: 'Symmetric 1σ error (counts)' } } }} />
              <NumericResultTable title="Exact Poisson errors" columns={[{ key: 'index', label: 'Index' }, { key: 'count', label: 'Count' }, { key: 'error', label: 'Symmetric 1σ error' }]} rows={rows} />
            </>;
          })() : (() => {
            const value = result as StandardErrorData;
            const rows = value.mean.map((mean, index) => ({ column: index, mean, sampleMean: value.calculated_sample_mean[index], standardError: value.standard_error[index] }));
            return <>
              <Alert severity="info">{value.assumptions} Mean and standard error retain each input column's units. Samples: {value.sample_count}; mean source: {value.mean_source}.</Alert>
              <PlotlyChart data={[{ x: previewValues(value.plot_preview, 'column_index'), y: previewValues(value.plot_preview, 'mean'), error_y: { type: 'data', array: previewValues(value.plot_preview, 'standard_error'), visible: true }, type: 'scattergl', mode: 'markers', name: 'Mean ± SEM' } as Data]} layout={{ xaxis: { title: { text: 'Column index' } }, yaxis: { title: { text: 'Mean ± standard error (column units)' } } }} />
              <NumericResultTable title="Exact standard errors" columns={[{ key: 'column', label: 'Column' }, { key: 'mean', label: 'Reference mean' }, { key: 'sampleMean', label: 'Sample mean' }, { key: 'standardError', label: 'Standard error' }]} rows={rows} />
            </>;
          })()}
        </ResultCard>
      </Grid>
    </Grid>
  );
}

function EnergyRangesWorkbench({ capabilities }: { capabilities?: MiscCapabilities }): React.ReactElement {
  const [source, setSource] = React.useState<'pasted' | 'event'>('pasted');
  const [energiesText, setEnergiesText] = React.useState('');
  const [eventList, setEventList] = React.useState('');
  const [rangeCount, setRangeCount] = React.useState('4');
  const [minimum, setMinimum] = React.useState('');
  const [maximum, setMaximum] = React.useState('');
  const [unit, setUnit] = React.useState('keV');
  const runner = useAnalysisRunner<EnergyRangesData>('Equal-count energy ranges');
  const maxValues = capabilities?.limits.max_array_values;
  const energies = React.useMemo(() => parseNumericArray(energiesText, 'Energies', maxValues), [energiesText, maxValues]);
  const nRanges = parsePositiveInteger(rangeCount);
  const lower = parseOptionalNumber(minimum, 'Minimum energy');
  const upper = parseOptionalNumber(maximum, 'Maximum energy');
  let validationError: string | null = !capabilities ? 'Runtime capabilities are loading' : null;
  if (!validationError && (nRanges === null || nRanges > capabilities!.limits.max_energy_ranges)) validationError = `Range count must be an integer from 1 to ${capabilities!.limits.max_energy_ranges.toLocaleString()}`;
  if (!validationError && source === 'pasted') {
    validationError = energies.error;
    if (!validationError && energies.value && energies.value.length < 2) validationError = 'At least two energy values are required';
    if (!validationError && energies.value && nRanges !== null && energies.value.length < nRanges) validationError = `At least ${nRanges} energy values are required for ${nRanges} ranges`;
    if (!validationError && unit.trim().length === 0) validationError = 'Energy unit is required for pasted values';
  }
  if (!validationError && source === 'event' && eventList === '') validationError = 'Choose an EventList with energy data';
  if (!validationError && lower.error) validationError = lower.error;
  if (!validationError && upper.error) validationError = upper.error;
  if (!validationError && lower.value !== null && upper.value !== null && lower.value >= upper.value) validationError = 'Minimum energy must be smaller than maximum energy';
  if (!validationError && source === 'pasted' && energies.value && nRanges !== null) {
    const selected = energies.value.filter(
      (value) =>
        (lower.value === null || value >= lower.value) &&
        (upper.value === null || value <= upper.value)
    );
    if (selected.length < nRanges) {
      validationError = `Only ${selected.length} energies fall inside the requested limits; ${nRanges} are required`;
    } else if (new Set(selected).size < nRanges) {
      validationError = 'Too few distinct energies remain for positive-width ranges; reduce the range count';
    }
  }
  const handleRun = (): void => {
    if (validationError || nRanges === null) return;
    const commonParams = {
      n_ranges: nRanges,
      energy_min: lower.value,
      energy_max: upper.value,
      energy_unit: source === 'event' ? 'keV' : unit.trim(),
    };
    if (source === 'pasted' && energies.value) {
      void runner.run(() =>
        miscApi.equalCountEnergyRanges({ ...commonParams, energies: energies.value! })
      );
    } else if (source === 'event') {
      void runner.run(() =>
        miscApi.equalCountEnergyRanges({ ...commonParams, event_list_name: eventList })
      );
    }
  };
  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={4} lg={3}>
        <ParameterCard>
          <Typography variant="subtitle2">Equal-count energy ranges</Typography>
          <Typography variant="body2" color="text.secondary">Percentile edges aim to place the same number of selected events in each positive-width energy range.</Typography>
          <FormControl size="small" fullWidth>
            <InputLabel id="energy-source-label">Energy source</InputLabel>
            <Select labelId="energy-source-label" label="Energy source" value={source} onChange={(event) => setSource(event.target.value as 'pasted' | 'event')}>
              <MenuItem value="pasted">Pasted energies</MenuItem>
              <MenuItem value="event">Loaded EventList</MenuItem>
            </Select>
          </FormControl>
          {source === 'pasted' ? <>
            <TextField label="Energy values" value={energiesText} onChange={(event) => setEnergiesText(event.target.value)} multiline minRows={5} size="small" helperText="Finite values; comma, whitespace or newline separated." />
            <TextField label="Energy unit" value={unit} onChange={(event) => setUnit(event.target.value)} size="small" helperText="For example keV. The backend preserves this label." />
          </> : <>
            <EventListSelector
              label="Energy EventList"
              value={eventList}
              onChange={setEventList}
              requiredCapability="energy"
            />
            <Alert severity="info">Loaded EventList energy follows Stingray's public keV convention. The source object is copied for read-only calculation and is not mutated.</Alert>
          </>}
          <TextField label="Number of ranges" value={rangeCount} onChange={(event) => setRangeCount(event.target.value)} size="small" helperText="Positive integer; every returned range must have nonzero width." />
          <TextField label="Minimum energy (optional)" value={minimum} onChange={(event) => setMinimum(event.target.value)} size="small" helperText="Inclusive lower filter in the selected energy unit." />
          <TextField label="Maximum energy (optional)" value={maximum} onChange={(event) => setMaximum(event.target.value)} size="small" helperText="Inclusive upper filter in the selected energy unit." />
          {validationError && (energiesText !== '' || eventList !== '' || minimum !== '' || maximum !== '') ? <Alert severity="error">{validationError}</Alert> : null}
          <RunButton running={runner.running} disabled={Boolean(validationError)} onClick={handleRun}>Create energy ranges</RunButton>
        </ParameterCard>
      </Grid>
      <Grid item xs={12} md={8} lg={9}>
        <ResultCard {...runner} emptyText="Choose exactly one energy source and calculate equal-count ranges.">
          {(result) => {
            const rows = result.counts.map((count, index) => ({ bin: index + 1, lower: result.bin_edges[index], upper: result.bin_edges[index + 1], count }));
            return <>
              <Alert severity="info">Edges use {result.energy_unit}; counts are dimensionless event counts. {result.selected_count.toLocaleString()} selected and {result.excluded_count.toLocaleString()} excluded by the requested limits.</Alert>
              <PlotlyChart data={[{ x: previewValues(result.plot_preview, 'rank'), y: previewValues(result.plot_preview, 'energy'), type: 'scattergl', mode: 'markers', name: 'Sorted energy' } as Data]} layout={{ xaxis: { title: { text: 'Selected-event rank' } }, yaxis: { title: { text: `Energy (${result.energy_unit})` } } }} />
              <NumericResultTable title="Exact energy ranges" columns={[{ key: 'bin', label: 'Range' }, { key: 'lower', label: 'Lower edge', unit: result.energy_unit }, { key: 'upper', label: 'Upper edge', unit: result.energy_unit }, { key: 'count', label: 'Event count' }]} rows={rows} />
            </>;
          }}
        </ResultCard>
      </Grid>
    </Grid>
  );
}

const MiscPage: React.FC = () => {
  const [tab, setTab] = React.useState<MainTab>('rebin');
  const [visitedTabs, setVisitedTabs] = React.useState<Set<MainTab>>(
    () => new Set<MainTab>(['rebin'])
  );
  const capabilitiesQuery = useQuery({
    queryKey: ['misc-utility-capabilities'],
    queryFn: async () => {
      const response = await miscApi.capabilities();
      if (!response.success || !response.data) throw new Error(response.error || response.message || 'Failed to load Misc utility capabilities');
      return response.data;
    },
    staleTime: Number.POSITIVE_INFINITY,
  });
  const capabilities = capabilitiesQuery.data;
  const handleTabChange = (_event: React.SyntheticEvent, value: MainTab): void => {
    setTab(value);
    setVisitedTabs((current) => {
      if (current.has(value)) return current;
      const next = new Set(current);
      next.add(value);
      return next;
    });
  };
  return (
    <PageTemplate title="Miscellaneous Tools" description="Curated, bounded numerical and time-series helpers from the installed public Stingray API" category="Utilities" status="ready">
      <Stack spacing={2}>
        {capabilitiesQuery.isPending ? <Alert severity="info" icon={<CircularProgress size={18} />}>Loading installed Stingray capabilities and allocation limits…</Alert> : null}
        {capabilitiesQuery.isError ? <Alert severity="error">Could not load runtime capabilities: {capabilitiesQuery.error instanceof Error ? capabilitiesQuery.error.message : 'unknown error'}</Alert> : null}
        {capabilities ? <Alert severity="info">Renderer inputs are checked before submission. Runtime caps: {capabilities.limits.max_array_values.toLocaleString()} values per array, {capabilities.limits.max_matrix_cells.toLocaleString()} matrix cells and {capabilities.limits.max_exact_output_values.toLocaleString()} exact output values. Plot previews may be decimated, but the paginated tables use the exact returned arrays.</Alert> : null}
        <Paper variant="outlined">
          <Tabs value={tab} onChange={handleTabChange} variant="scrollable" scrollButtons="auto" aria-label="Miscellaneous utility tools">
            {MAIN_TABS.map((item) => (
              <Tab
                key={item.value}
                id={`misc-tab-${item.value}`}
                aria-controls={`misc-panel-${item.value}`}
                value={item.value}
                label={item.label}
              />
            ))}
          </Tabs>
        </Paper>
      </Stack>
      <WorkbenchPanel value="rebin" active={tab === 'rebin'}><RebinWorkbench capabilities={capabilities} /></WorkbenchPanel>
      <WorkbenchPanel value="baseline" active={tab === 'baseline'}>{visitedTabs.has('baseline') ? <BaselineWorkbench capabilities={capabilities} /> : null}</WorkbenchPanel>
      <WorkbenchPanel value="window" active={tab === 'window'}>{visitedTabs.has('window') ? <WindowWorkbench capabilities={capabilities} /> : null}</WorkbenchPanel>
      <WorkbenchPanel value="sampling" active={tab === 'sampling'}>{visitedTabs.has('sampling') ? <SamplingWorkbench capabilities={capabilities} /> : null}</WorkbenchPanel>
      <WorkbenchPanel value="errors" active={tab === 'errors'}>{visitedTabs.has('errors') ? <ErrorWorkbench capabilities={capabilities} /> : null}</WorkbenchPanel>
      <WorkbenchPanel value="energy" active={tab === 'energy'}>{visitedTabs.has('energy') ? <EnergyRangesWorkbench capabilities={capabilities} /> : null}</WorkbenchPanel>
    </PageTemplate>
  );
};

export default MiscPage;
