import { useState } from 'react';
import { Box, Stack, ToggleButton, ToggleButtonGroup } from '@mui/material';
import { GaussianPanel } from './GaussianPanel';
import { TrialCorrectionPanel } from './TrialCorrectionPanel';

type ProbabilityTool = 'gaussian' | 'trials';

export function ProbabilityWorkbench() {
  const [tool, setTool] = useState<ProbabilityTool>('gaussian');

  return (
    <Stack spacing={2}>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={tool}
        onChange={(_event, value: ProbabilityTool | null) => value && setTool(value)}
        aria-label="Probability tool"
      >
        <ToggleButton value="gaussian">Gaussian significance</ToggleButton>
        <ToggleButton value="trials">Trial correction</ToggleButton>
      </ToggleButtonGroup>
      <Box hidden={tool !== 'gaussian'}>
        <GaussianPanel />
      </Box>
      <Box hidden={tool !== 'trials'}>
        <TrialCorrectionPanel />
      </Box>
    </Stack>
  );
}
