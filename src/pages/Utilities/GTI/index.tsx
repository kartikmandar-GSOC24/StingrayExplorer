import React, { useCallback, useState } from 'react';
import { Box, Paper, Tab, Tabs } from '@mui/material';
import PageTemplate from '@/components/common/PageTemplate';
import type { GtiTimeReference } from '@/api/gtiApi';
import { TabPanel, type InspectedGtiRows } from './GtiCommon';
import InspectionPanel from './InspectionPanel';
import MaskSavePanel from './MaskSavePanel';
import SegmentationPanel from './SegmentationPanel';
import SetOperationsPanel from './SetOperationsPanel';
import ValidationPanel from './ValidationPanel';

const TAB_LABELS = [
  'Inspection',
  'Edit & validate',
  'Set operations & BTIs',
  'Mask & save',
  'Segmentation',
] as const;

const GTIPage: React.FC = () => {
  const [tab, setTab] = useState(0);
  const [inspectedRows, setInspectedRows] = useState<InspectedGtiRows | null>(null);
  const [setRows, setSetRows] = useState('');
  const [setTimeReference, setSetTimeReference] =
    useState<GtiTimeReference>('absolute_mission_time');
  const [maskRows, setMaskRows] = useState('');
  const [segmentRows, setSegmentRows] = useState('');
  const [segmentTimeReference, setSegmentTimeReference] =
    useState<GtiTimeReference>('absolute_mission_time');

  const useValidatedRows = useCallback(
    (rows: string, reference: GtiTimeReference): void => {
      setSetRows(rows);
      setSetTimeReference(reference);
      setSegmentRows(rows);
      setSegmentTimeReference(reference);
      if (reference === 'absolute_mission_time') setMaskRows(rows);
    },
    []
  );

  return (
    <PageTemplate
      title="GTI Functionality"
      description="Inspect, validate, combine, filter, and segment Good Time Intervals without mutating source data"
      category="Utilities"
      status="ready"
    >
      <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
        <Tabs
          value={tab}
          onChange={(_event, next: number) => setTab(next)}
          variant="scrollable"
          scrollButtons="auto"
          aria-label="GTI workbench tools"
          sx={{ borderBottom: 1, borderColor: 'divider', px: 1 }}
        >
          {TAB_LABELS.map((label, index) => (
            <Tab
              key={label}
              label={label}
              id={`gti-tab-${index}`}
              aria-controls={`gti-tabpanel-${index}`}
            />
          ))}
        </Tabs>

        <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <TabPanel active={tab} index={0}>
            <InspectionPanel onInspectedRowsChange={setInspectedRows} />
          </TabPanel>
          <TabPanel active={tab} index={1}>
            <ValidationPanel
              inspectedRows={inspectedRows}
              onUseValidatedRows={useValidatedRows}
            />
          </TabPanel>
          <TabPanel active={tab} index={2}>
            <SetOperationsPanel
              inspectedRows={inspectedRows}
              leftRows={setRows}
              onLeftRowsChange={setSetRows}
              timeReference={setTimeReference}
              onTimeReferenceChange={setSetTimeReference}
            />
          </TabPanel>
          <TabPanel active={tab} index={3}>
            <MaskSavePanel
              inspectedRows={inspectedRows}
              rows={maskRows}
              onRowsChange={setMaskRows}
            />
          </TabPanel>
          <TabPanel active={tab} index={4}>
            <SegmentationPanel
              inspectedRows={inspectedRows}
              rows={segmentRows}
              onRowsChange={setSegmentRows}
              timeReference={segmentTimeReference}
              onTimeReferenceChange={setSegmentTimeReference}
            />
          </TabPanel>
        </Box>
      </Paper>
    </PageTemplate>
  );
};

export default GTIPage;
