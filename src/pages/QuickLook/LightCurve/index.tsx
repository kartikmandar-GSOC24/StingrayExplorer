import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import DeleteIcon from '@mui/icons-material/Delete';
import VisibilityIcon from '@mui/icons-material/Visibility';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { lightcurveApi, LightcurveData, LightcurveSummary } from '@/api/lightcurveApi';
import { parsePositiveNumber } from '@/utils/numbers';
import { useUIStore } from '@/store/uiStore';

const LIGHTCURVES_QUERY_KEY = ['lightcurves'] as const;

const LightCurvePage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('1.0');
  const [outputName, setOutputName] = useState('');
  const [existingSelection, setExistingSelection] = useState('');
  const [rebinFactor, setRebinFactor] = useState('2');
  const addNotification = useUIStore((s) => s.addNotification);
  const queryClient = useQueryClient();
  const { result, running, error, run } = useAnalysisRunner<LightcurveData>('Light Curve');

  const existingQuery = useQuery({
    queryKey: LIGHTCURVES_QUERY_KEY,
    queryFn: async (): Promise<LightcurveSummary[]> => {
      const res = await lightcurveApi.listLightcurves();
      if (!res.success) throw new Error(res.error || res.message);
      return res.data ?? [];
    },
  });

  // Any successful create/rebin changes the stored set — refresh the list.
  useEffect(() => {
    if (result) void queryClient.invalidateQueries({ queryKey: LIGHTCURVES_QUERY_KEY });
  }, [result, queryClient]);

  const dtNum = parsePositiveNumber(dt);
  const canRun = eventList !== '' && dtNum !== null && !running;
  const rebinNum = parsePositiveNumber(rebinFactor);

  const handleGenerate = (): void => {
    if (!dtNum || !eventList) return;
    const name = outputName.trim() || `${eventList}_lc`;
    void run(() =>
      lightcurveApi.createFromEventList({ event_list_name: eventList, dt: dtNum, output_name: name })
    );
  };

  const handleView = (): void => {
    if (!existingSelection) return;
    void run(() => lightcurveApi.getLightcurveData(existingSelection));
  };

  const handleRebin = (): void => {
    if (!result?.name || !rebinNum) return;
    void run(() =>
      lightcurveApi.rebin({
        name: result.name,
        rebin_factor: rebinNum,
        output_name: `${result.name}_r${rebinNum}`,
      })
    );
  };

  const handleDelete = async (name: string): Promise<void> => {
    const res = await lightcurveApi.deleteLightcurve(name);
    if (res.success) {
      addNotification({ type: 'success', title: 'Light Curve', message: `Deleted '${name}'` });
      await queryClient.invalidateQueries({ queryKey: LIGHTCURVES_QUERY_KEY });
    } else {
      addNotification({
        type: 'error',
        title: 'Light Curve',
        message: res.error || res.message || 'Delete failed',
      });
    }
  };

  const plotData: Data[] = result
    ? [
        {
          x: result.time,
          y: result.counts,
          type: 'scattergl',
          mode: 'lines',
          line: { color: '#00d4aa', width: 1 },
        } as Data,
      ]
    : [];

  return (
    <PageTemplate
      title="Light Curve"
      description="Bin event arrival times into a light curve, rebin it, and inspect stored light curves"
      category="Time Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Generate from event list</Typography>
                <EventListSelector label="Event list" value={eventList} onChange={setEventList} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Store as"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                  placeholder={eventList ? `${eventList}_lc` : 'name'}
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleGenerate}
                >
                  Generate
                </Button>
              </Stack>

              {result?.name && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Stack spacing={2}>
                    <Typography variant="subtitle2">Rebin '{result.name}'</Typography>
                    <TextField
                      label="Rebin factor (× dt)"
                      size="small"
                      value={rebinFactor}
                      onChange={(e) => setRebinFactor(e.target.value)}
                      error={rebinFactor !== '' && rebinNum === null}
                      helperText={
                        rebinFactor !== '' && rebinNum === null ? 'Must be a positive number' : ' '
                      }
                    />
                    <Button variant="outlined" disabled={!rebinNum || running} onClick={handleRebin}>
                      Rebin
                    </Button>
                  </Stack>
                </>
              )}

              <Divider sx={{ my: 2 }} />
              <Stack spacing={2}>
                <Typography variant="subtitle2">Stored light curves</Typography>
                <FormControl size="small" fullWidth>
                  <InputLabel id="existing-lc-label">Light curve</InputLabel>
                  <Select
                    labelId="existing-lc-label"
                    label="Light curve"
                    value={existingSelection}
                    onChange={(e) => setExistingSelection(e.target.value)}
                  >
                    {(existingQuery.data ?? []).map((lc) => (
                      <MenuItem key={lc.name} value={lc.name}>
                        {lc.name} ({lc.n_bins.toLocaleString()} bins)
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<VisibilityIcon />}
                    disabled={!existingSelection || running}
                    onClick={handleView}
                  >
                    View
                  </Button>
                  <Tooltip title="Delete selected">
                    <span>
                      <IconButton
                        size="small"
                        color="error"
                        aria-label="Delete selected light curve"
                        disabled={!existingSelection}
                        onClick={() => {
                          void handleDelete(existingSelection);
                          setExistingSelection('');
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                  {result?.name ? `Light curve: ${result.name}` : 'Result'}
                </Typography>
                {result && <Chip size="small" label={`${result.n_bins.toLocaleString()} bins`} />}
                {result && <Chip size="small" label={`dt = ${result.dt} s`} variant="outlined" />}
                {result?.count_rate_mean !== undefined && (
                  <Chip
                    size="small"
                    label={`mean ${result.count_rate_mean.toFixed(2)} cts/s`}
                    variant="outlined"
                  />
                )}
              </Box>
              {result?.plot_stride !== undefined && result.plot_stride > 1 && (
                <Alert severity="info" sx={{ mb: 1 }}>
                  Showing every {result.plot_stride}th bin for display performance (full resolution
                  is stored in the backend).
                </Alert>
              )}
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={plotData}
                  layout={{
                    xaxis: { title: { text: 'Time (s)' } },
                    yaxis: { title: { text: `Counts / ${result.dt} s bin` } },
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Generate a light curve or view a stored one.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default LightCurvePage;
