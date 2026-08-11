import React from 'react';
import { Box, Tab, Tabs } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import StorageIcon from '@mui/icons-material/Storage';
import CalculateIcon from '@mui/icons-material/Calculate';
import PreviewIcon from '@mui/icons-material/Preview';
import PageTemplate from '@/components/common/PageTemplate';
import IdentificationPanel from './IdentificationPanel';
import MissionDatabasePanel from './MissionDatabasePanel';
import RoughConversionPanel from './RoughConversionPanel';
import InterpretationPanel from './InterpretationPanel';

const TabPanel: React.FC<{
  active: number;
  index: number;
  children: React.ReactNode;
}> = ({ active, index, children }) =>
  active === index ? (
    <Box role="tabpanel" aria-labelledby={`mission-io-tab-${index}`} sx={{ pt: 2.5 }}>
      {children}
    </Box>
  ) : null;

const MissionIOPage: React.FC = () => {
  const [activeTab, setActiveTab] = React.useState(0);

  return (
    <PageTemplate
      title="Mission-Specific I/O"
      description="Inspect mission metadata and runtime mappings, preview approximate PI conversions, and run supported read-only interpreters"
      category="Utilities"
      status="ready"
    >
      <Tabs
        value={activeTab}
        onChange={(_event, value: number) => setActiveTab(value)}
        variant="scrollable"
        scrollButtons="auto"
        aria-label="Mission-specific I/O tools"
      >
        <Tab id="mission-io-tab-0" icon={<SearchIcon />} iconPosition="start" label="Identify" />
        <Tab
          id="mission-io-tab-1"
          icon={<StorageIcon />}
          iconPosition="start"
          label="Mission database"
        />
        <Tab
          id="mission-io-tab-2"
          icon={<CalculateIcon />}
          iconPosition="start"
          label="Approximate conversion"
        />
        <Tab
          id="mission-io-tab-3"
          icon={<PreviewIcon />}
          iconPosition="start"
          label="Specialized interpretation"
        />
      </Tabs>
      <TabPanel active={activeTab} index={0}>
        <IdentificationPanel />
      </TabPanel>
      <TabPanel active={activeTab} index={1}>
        <MissionDatabasePanel />
      </TabPanel>
      <TabPanel active={activeTab} index={2}>
        <RoughConversionPanel />
      </TabPanel>
      <TabPanel active={activeTab} index={3}>
        <InterpretationPanel />
      </TabPanel>
    </PageTemplate>
  );
};

export default MissionIOPage;
