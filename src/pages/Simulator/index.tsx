import React from 'react';
import PageTemplate from '@/components/common/PageTemplate';

const SimulatorPage: React.FC = () => {
  return (
    <PageTemplate
      title="Simulator"
      description="Generate synthetic light curves and event lists with specified power spectra"
      category="Simulation"
      status="coming-soon"
    />
  );
};

export default SimulatorPage;
