import { Chip, Grid } from '@mui/material';
import type { FamilyConfig } from './familyConfigs';
import { StatisticFamilyForm } from './StatisticFamilyForm';
import { ResultFrame } from './WorkbenchComponents';
import { useStatisticFamily } from './useStatisticFamily';

interface StatisticFamilyPanelProps {
  config: FamilyConfig;
}

export function StatisticFamilyPanel({ config }: StatisticFamilyPanelProps) {
  const model = useStatisticFamily(config);

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={5} lg={4}>
        <StatisticFamilyForm config={config} model={model} />
      </Grid>
      <Grid item xs={12} md={7} lg={8}>
        <ResultFrame
          title={
            model.operation === 'evaluate'
              ? 'Observed-statistic result'
              : 'Detection-threshold result'
          }
          running={model.activeRunner.running}
          error={model.activeRunner.error}
          requestWarnings={model.activeRunner.warnings}
          result={model.activeResult}
          rows={model.activeRows}
          chips={
            model.activeResult ? (
              <>
                <Chip
                  size="small"
                  variant="outlined"
                  label={`${model.activeResult.n_trials} trial${model.activeResult.n_trials === 1 ? '' : 's'}`}
                />
                <Chip
                  size="small"
                  color={model.activeResult.tail === 'lower' ? 'secondary' : 'primary'}
                  variant="outlined"
                  label={`${model.activeResult.tail} tail`}
                />
              </>
            ) : undefined
          }
          emptyText={
            model.operation === 'evaluate'
              ? 'Enter an observed statistic to evaluate its global false-alarm probability.'
              : 'Enter a desired global false-alarm probability to calculate the threshold.'
          }
        />
      </Grid>
    </Grid>
  );
}
