import {
  Alert,
  Box,
  Card,
  CardContent,
  Divider,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import type { FamilyConfig } from './familyConfigs';
import { SubmitButton } from './WorkbenchComponents';
import type { FamilyOperation, StatisticFamilyModel } from './useStatisticFamily';

interface StatisticFamilyFormProps {
  config: FamilyConfig;
  model: StatisticFamilyModel;
}

export function StatisticFamilyForm({ config, model }: StatisticFamilyFormProps) {
  return (
    <Card variant="outlined">
      <CardContent component="form" onSubmit={model.submit}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="subtitle2">{config.title}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              {config.description}
            </Typography>
          </Box>
          <Divider />
          <ToggleButtonGroup
            exclusive
            fullWidth
            size="small"
            value={model.operation}
            onChange={(_event, value: FamilyOperation | null) =>
              value && model.setOperation(value)
            }
            aria-label={`${config.title} operation`}
          >
            <ToggleButton value="evaluate">Evaluate observation</ToggleButton>
            <ToggleButton value="detection">Find detection level</ToggleButton>
          </ToggleButtonGroup>
          {model.operation === 'evaluate' ? (
            <TextField
              label={config.statisticLabel}
              size="small"
              value={model.rawStatistic}
              onChange={(event) => model.setRawStatistic(event.target.value)}
              error={model.statisticError !== null}
              helperText={model.statisticError ?? config.statisticDomain}
              inputProps={{ inputMode: 'decimal' }}
            />
          ) : (
            <TextField
              label="Overall false-alarm probability"
              size="small"
              value={model.rawFalseAlarm}
              onChange={(event) => model.setRawFalseAlarm(event.target.value)}
              error={model.falseAlarm.error !== null}
              helperText={
                model.falseAlarm.error ?? 'Desired global/post-trial FAP; domain: 0 < p < 1'
              }
              inputProps={{ inputMode: 'decimal' }}
            />
          )}
          <TextField
            label="Independent trials"
            size="small"
            value={model.rawTrials}
            onChange={(event) => model.setRawTrials(event.target.value)}
            error={model.trials.error !== null}
            helperText={
              model.trials.error ?? 'Exact independent-trial correction; positive integer'
            }
            inputProps={{ inputMode: 'numeric' }}
          />
          {config.hasHarmonics && (
            <TextField
              label="Harmonics"
              size="small"
              value={model.rawHarmonics}
              onChange={(event) => model.setRawHarmonics(event.target.value)}
              error={model.harmonics.error !== null}
              helperText={model.harmonics.error ?? 'Includes the fundamental; positive integer'}
              inputProps={{ inputMode: 'numeric' }}
            />
          )}
          {config.hasSummedSpectra && (
            <TextField
              label={config.key === 'z2' ? 'Averaged periodograms' : 'Averaged spectra'}
              size="small"
              value={model.rawSummed}
              onChange={(event) => model.setRawSummed(event.target.value)}
              error={model.summed.error !== null}
              helperText={model.summed.error ?? 'Number averaged; positive integer'}
              inputProps={{ inputMode: 'numeric' }}
            />
          )}
          {config.hasRebin && (
            <TextField
              label="Rebin factor"
              size="small"
              value={model.rawRebin}
              onChange={(event) => model.setRawRebin(event.target.value)}
              error={model.rebin.error !== null}
              helperText={model.rebin.error ?? 'Averaged frequency bins per output power'}
              inputProps={{ inputMode: 'numeric' }}
            />
          )}
          {config.hasSamples && (
            <TextField
              label="Time-series samples"
              size="small"
              value={model.rawSamples}
              onChange={(event) => model.setRawSamples(event.target.value)}
              error={model.samples.error !== null || model.sampleRelationError !== null}
              helperText={
                model.samples.error ??
                model.sampleRelationError ??
                'Integer ≥ 3 and greater than phase bins'
              }
              inputProps={{ inputMode: 'numeric' }}
            />
          )}
          {config.hasPhaseBins && (
            <TextField
              label="Phase bins"
              size="small"
              value={model.rawPhaseBins}
              onChange={(event) => model.setRawPhaseBins(event.target.value)}
              error={model.phaseBins.error !== null || model.sampleRelationError !== null}
              helperText={
                model.phaseBins.error ??
                model.sampleRelationError ??
                `Integer ≥ ${config.minimumPhaseBins ?? 1}${config.hasSamples ? ' and less than samples' : ''}`
              }
              inputProps={{ inputMode: 'numeric' }}
            />
          )}
          <Alert severity="info" icon={false}>
            {model.operation === 'evaluate'
              ? `The result is an overall false-alarm probability after ${model.rawTrials || 'n'} independent trial(s). ${config.significantDirection === 'larger' ? 'Larger' : 'Smaller'} observed values are more significant.`
              : `The input is the desired overall false-alarm probability. The backend applies the trial correction before finding the ${config.significantDirection === 'larger' ? 'upper' : 'lower'}-tail threshold.`}
          </Alert>
          <SubmitButton
            running={model.activeRunner.running}
            disabled={!model.canSubmit}
            label={
              model.operation === 'evaluate'
                ? 'Evaluate false-alarm probability'
                : 'Calculate detection level'
            }
          />
        </Stack>
      </CardContent>
    </Card>
  );
}
