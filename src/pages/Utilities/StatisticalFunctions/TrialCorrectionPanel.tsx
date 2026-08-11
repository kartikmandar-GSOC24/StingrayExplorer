import { useState, type FormEvent } from 'react';
import {
  Alert,
  Card,
  CardContent,
  Chip,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import type { TrialCorrectionResult, TrialDirection } from '@/api/statisticsApi';
import { statisticsApi } from '@/api/statisticsApi';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { ResultFrame, SubmitButton } from './WorkbenchComponents';
import { count, finiteNumber } from './validation';

export function TrialCorrectionPanel() {
  const [direction, setDirection] = useState<TrialDirection>('single-to-multi');
  const [rawProbability, setRawProbability] = useState('0.001');
  const [rawTrials, setRawTrials] = useState('100');
  const runner = useAnalysisRunner<TrialCorrectionResult>('Independent Trial Correction');

  const parsedProbability = finiteNumber(rawProbability, 'Probability');
  const probabilityError =
    parsedProbability.error ??
    (parsedProbability.value !== null && parsedProbability.value < 0
      ? 'Probability must be at least 0'
      : direction === 'single-to-multi' &&
          parsedProbability.value !== null &&
          parsedProbability.value > 1
        ? 'Single-trial probability must be at most 1'
        : direction === 'multi-to-single' &&
            parsedProbability.value !== null &&
            parsedProbability.value >= 1
          ? 'Overall multi-trial probability must be less than 1'
          : null);
  const validProbability = probabilityError === null ? parsedProbability.value : null;
  const trials = count(rawTrials, 'Independent trials');

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    if (validProbability === null || trials.value === null || runner.running) return;
    const nTrials = trials.value;
    void runner.run(() =>
      statisticsApi.trials({ direction, probability: validProbability, n_trials: nTrials })
    );
  };

  const outputLabel =
    runner.result?.direction === 'single-to-multi'
      ? 'Overall multi-trial probability'
      : 'Equivalent single-trial probability';
  const rows = runner.result
    ? [
        {
          quantity:
            runner.result.direction === 'single-to-multi'
              ? 'Input single-trial probability'
              : 'Input overall multi-trial probability',
          value: runner.result.input_probability,
          unit: runner.result.units.input_probability,
        },
        {
          quantity: outputLabel,
          value: runner.result.output_probability,
          unit: runner.result.units.output_probability,
        },
        {
          quantity: 'Independent trials',
          value: runner.result.n_trials,
          unit: 'count',
        },
      ]
    : [];

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={5} lg={4}>
        <Card variant="outlined">
          <CardContent component="form" onSubmit={submit}>
            <Stack spacing={2}>
              <Typography variant="subtitle2">Independent-trial correction</Typography>
              <Typography variant="body2" color="text.secondary">
                Applies Stingray&apos;s exact independent-trial (Šidák/binomial) conversion in
                either direction, rather than the small-probability approximation.
              </Typography>
              <FormControl size="small" fullWidth>
                <InputLabel id="trial-direction-label">Correction direction</InputLabel>
                <Select
                  labelId="trial-direction-label"
                  label="Correction direction"
                  value={direction}
                  onChange={(event) => setDirection(event.target.value as TrialDirection)}
                >
                  <MenuItem value="single-to-multi">Single trial → overall multi-trial</MenuItem>
                  <MenuItem value="multi-to-single">Overall multi-trial → single trial</MenuItem>
                </Select>
              </FormControl>
              <TextField
                label={
                  direction === 'single-to-multi'
                    ? 'Single-trial probability'
                    : 'Overall multi-trial probability'
                }
                size="small"
                value={rawProbability}
                onChange={(event) => setRawProbability(event.target.value)}
                error={probabilityError !== null}
                helperText={
                  probabilityError ??
                  (direction === 'single-to-multi' ? 'Domain: 0 ≤ p ≤ 1' : 'Domain: 0 ≤ p < 1')
                }
                inputProps={{ inputMode: 'decimal' }}
              />
              <TextField
                label="Independent trials"
                size="small"
                value={rawTrials}
                onChange={(event) => setRawTrials(event.target.value)}
                error={trials.error !== null}
                helperText={
                  trials.error ?? 'Positive integer; trials must be statistically independent'
                }
                inputProps={{ inputMode: 'numeric' }}
              />
              <SubmitButton
                running={runner.running}
                disabled={validProbability === null || trials.value === null || runner.running}
                label="Correct probability"
              />
            </Stack>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={7} lg={8}>
        <ResultFrame
          title="Trial-corrected probability"
          running={runner.running}
          error={runner.error}
          requestWarnings={runner.warnings}
          result={runner.result}
          rows={rows}
          chips={
            runner.result ? (
              <Chip
                size="small"
                variant="outlined"
                label={`${runner.result.n_trials} trials`}
              />
            ) : undefined
          }
          emptyText="Choose a direction and number of independent trials."
        />
        {runner.result && (
          <Alert severity="info" icon={false} sx={{ mt: 2 }}>
            {runner.result.independence_assumption}
          </Alert>
        )}
      </Grid>
    </Grid>
  );
}
