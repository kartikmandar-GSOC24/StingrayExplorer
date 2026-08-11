import { useState } from 'react';
import { Alert, Card, Tab, Tabs } from '@mui/material';
import PageTemplate from '@/components/common/PageTemplate';
import { FAMILY_CONFIGS } from './familyConfigs';
import { ProbabilityWorkbench } from './ProbabilityWorkbench';
import { StatisticFamilyPanel } from './StatisticFamilyPanel';
import { WorkbenchTabPanel } from './WorkbenchComponents';

const TAB_LABELS = [
  'Probability & trials',
  'Power spectrum',
  'Z-squared',
  'Epoch folding',
  'Phase dispersion',
];

export default function StatisticalFunctionsPage() {
  const [tab, setTab] = useState(0);

  return (
    <PageTemplate
      title="Statistical Functions"
      description="Probability, significance, trial correction, and detection thresholds backed by public Stingray statistics APIs"
      category="Utilities"
      status="ready"
    >
      <Alert severity="info" sx={{ mb: 2 }}>
        Every probability reported by a statistic is a false-alarm probability under its stated
        noise model. Evaluate uses an observed statistic; detection computes the statistic threshold
        for a requested global false-alarm probability. All log probabilities are natural logarithms.
      </Alert>
      <Card variant="outlined">
        <Tabs
          value={tab}
          onChange={(_event, value: number) => setTab(value)}
          variant="scrollable"
          scrollButtons="auto"
          aria-label="Statistical function categories"
        >
          {TAB_LABELS.map((label, index) => (
            <Tab
              key={label}
              label={label}
              id={`statistics-tab-${index}`}
              aria-controls={`statistics-panel-${index}`}
            />
          ))}
        </Tabs>
      </Card>
      <WorkbenchTabPanel active={tab} index={0}>
        <ProbabilityWorkbench />
      </WorkbenchTabPanel>
      <WorkbenchTabPanel active={tab} index={1}>
        <StatisticFamilyPanel config={FAMILY_CONFIGS.pds} />
      </WorkbenchTabPanel>
      <WorkbenchTabPanel active={tab} index={2}>
        <StatisticFamilyPanel config={FAMILY_CONFIGS.z2} />
      </WorkbenchTabPanel>
      <WorkbenchTabPanel active={tab} index={3}>
        <StatisticFamilyPanel config={FAMILY_CONFIGS.fold} />
      </WorkbenchTabPanel>
      <WorkbenchTabPanel active={tab} index={4}>
        <StatisticFamilyPanel config={FAMILY_CONFIGS.pdm} />
      </WorkbenchTabPanel>
    </PageTemplate>
  );
}
