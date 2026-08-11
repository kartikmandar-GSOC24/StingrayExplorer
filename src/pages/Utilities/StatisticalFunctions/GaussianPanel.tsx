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
import type { GaussianResult, StatisticalSidedness } from '@/api/statisticsApi';
import { statisticsApi } from '@/api/statisticsApi';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { ResultFrame, SubmitButton } from './WorkbenchComponents';
import { finiteNumber } from './validation';

type InputMode = 'probability' | 'log_probability';

export function GaussianPanel() {
  const [inputMode, setInputMode] = useState<InputMode>('probability');
  const [rawValue, setRawValue] = useState('0.0027');
  const [sidedness, setSidedness] = useState<StatisticalSidedness>('one-sided');
  const runner = useAnalysisRunner<GaussianResult>('Gaussian Significance');

  const parsed = finiteNumber(
    rawValue,
    inputMode === 'probability' ? 'Tail probability' : 'Natural log probability'
  );
  const domainError =
    parsed.error ??
    (inputMode === 'probability' && parsed.value !== null && !(parsed.value > 0 && parsed.value < 1)
      ? 'Tail probability must be greater than 0 and less than 1'
      : inputMode === 'log_probability' && parsed.value !== null && parsed.value >= 0
        ? 'Natural log probability must be less than 0'
        : null);
  const validValue = domainError === null ? parsed.value : null;

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    if (validValue === null || runner.running) return;
    void runner.run(() =>
      statisticsApi.gaussian(
        inputMode === 'probability'
          ? { probability: validValue, sidedness }
          : { log_probability: validValue, sidedness }
      )
    );
  };

  const rows = runner.result
    ? [
        {
          quantity: runner.result.input_mode === 'probability' ? 'Input probability' : 'Input ln(p)',
          value:
            runner.result.input_mode === 'probability'
              ? runner.result.input_probability
              : runner.result.input_log_probability,
          unit:
            runner.result.input_mode === 'probability'
              ? runner.result.units.input_probability
              : runner.result.units.input_log_probability,
        },
        {
          quantity: 'Effective one-sided upper-tail probability',
          value: runner.result.effective_one_sided_probability,
          unit: 'dimensionless probability',
        },
        {
          quantity: 'ln(effective one-sided probability)',
          value: runner.result.effective_one_sided_log_probability,
          unit: 'natural logarithm',
        },
        {
          quantity: 'Equivalent Gaussian significance',
          value: runner.result.sigma,
          unit: runner.result.units.sigma ?? 'standard deviations',
        },
      ]
    : [];

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={5} lg={4}>
        <Card variant="outlined">
          <CardContent component="form" onSubmit={submit}>
            <Stack spacing={2}>
              <Typography variant="subtitle2">Probability → Gaussian sigma</Typography>
              <Typography variant="body2" color="text.secondary">
                Converts a tail probability to an equivalent standard-normal deviation. Log input
                keeps extremely small probabilities numerically meaningful.
              </Typography>
              <FormControl size="small" fullWidth>
                <InputLabel id="gaussian-input-mode-label">Probability input mode</InputLabel>
                <Select
                  labelId="gaussian-input-mode-label"
                  label="Probability input mode"
                  value={inputMode}
                  onChange={(event) => setInputMode(event.target.value as InputMode)}
                >
                  <MenuItem value="probability">Probability p</MenuItem>
                  <MenuItem value="log_probability">Natural log ln(p)</MenuItem>
                </Select>
              </FormControl>
              <TextField
                label={
                  inputMode === 'probability'
                    ? 'Tail probability p'
                    : 'Natural log probability ln(p)'
                }
                size="small"
                value={rawValue}
                onChange={(event) => setRawValue(event.target.value)}
                error={domainError !== null}
                helperText={
                  domainError ??
                  (inputMode === 'probability'
                    ? 'Domain: 0 < p < 1'
                    : 'Domain: finite ln(p) < 0; natural logarithm')
                }
                inputProps={{ inputMode: 'decimal' }}
              />
              <FormControl size="small" fullWidth>
                <InputLabel id="gaussian-sidedness-label">Tail convention</InputLabel>
                <Select
                  labelId="gaussian-sidedness-label"
                  label="Tail convention"
                  value={sidedness}
                  onChange={(event) =>
                    setSidedness(event.target.value as StatisticalSidedness)
                  }
                >
                  <MenuItem value="one-sided">One-sided upper tail</MenuItem>
                  <MenuItem value="two-sided">Two-sided total probability</MenuItem>
                </Select>
              </FormControl>
              <Alert severity="info" icon={false}>
                {sidedness === 'one-sided'
                  ? 'p is the upper-tail area P(Z ≥ σ).'
                  : 'p is the combined probability in both tails. Each tail uses p / 2 before conversion.'}{' '}
                All log probabilities are natural logarithms.
              </Alert>
              <SubmitButton
                running={runner.running}
                disabled={validValue === null || runner.running}
                label="Convert to Gaussian sigma"
              />
            </Stack>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={7} lg={8}>
        <ResultFrame
          title="Gaussian significance result"
          running={runner.running}
          error={runner.error}
          requestWarnings={runner.warnings}
          result={runner.result}
          rows={rows}
          chips={
            runner.result ? (
              <Chip size="small" variant="outlined" label={runner.result.sidedness} />
            ) : undefined
          }
          emptyText="Enter a probability and choose its tail convention."
        />
      </Grid>
    </Grid>
  );
}
