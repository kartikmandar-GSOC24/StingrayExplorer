import React, { useState } from 'react';
import type { Data } from 'plotly.js';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import DeleteIcon from '@mui/icons-material/Delete';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import { EVENT_LISTS_QUERY_KEY, useEventLists } from '@/hooks/useEventLists';
import { dataApi, EventListFullPreview, EventListInfo } from '@/api/dataApi';
import { useUIStore } from '@/store/uiStore';

const mono = { fontFamily: '"JetBrains Mono", monospace' };

const formatNum = (v: number | null | undefined, digits = 3): string =>
  v === null || v === undefined
    ? '—'
    : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });

const InfoRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, py: 0.5 }}>
    <Typography variant="body2" color="text.secondary">
      {label}
    </Typography>
    <Typography variant="body2" sx={mono}>
      {value}
    </Typography>
  </Box>
);

const EventListPage: React.FC = () => {
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const addNotification = useUIStore((s) => s.addNotification);
  const queryClient = useQueryClient();
  const { data: eventLists, isLoading, isError, error, refetch, isFetching } = useEventLists();

  const infoQuery = useQuery({
    queryKey: ['eventListInfo', selected],
    enabled: selected !== null,
    queryFn: async (): Promise<EventListInfo> => {
      const res = await dataApi.getEventListInfo(selected as string);
      if (!res.success || !res.data) throw new Error(res.error || res.message);
      return res.data;
    },
  });

  const previewQuery = useQuery({
    queryKey: ['eventListPreview', selected],
    enabled: selected !== null && tab === 1,
    queryFn: async (): Promise<EventListFullPreview> => {
      const res = await dataApi.getEventListFullPreview(selected as string);
      if (!res.success || !res.data) throw new Error(res.error || res.message);
      return res.data;
    },
  });

  const handleDelete = async (): Promise<void> => {
    if (!deleteTarget) return;
    const res = await dataApi.deleteEventList(deleteTarget);
    if (res.success) {
      addNotification({ type: 'success', title: 'Event List', message: `Deleted '${deleteTarget}'` });
      if (selected === deleteTarget) setSelected(null);
      await queryClient.invalidateQueries({ queryKey: EVENT_LISTS_QUERY_KEY });
    } else {
      addNotification({
        type: 'error',
        title: 'Event List',
        message: res.error || res.message || 'Delete failed',
      });
    }
    setDeleteTarget(null);
  };

  const info = infoQuery.data;
  const preview = previewQuery.data;

  return (
    <PageTemplate
      title="Event List"
      description="Inspect event lists loaded in the backend: metadata, GTIs, and arrival-time/energy distributions"
      category="Time Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Typography variant="subtitle2">Loaded event lists</Typography>
                <Tooltip title="Refresh">
                  <span>
                    <IconButton size="small" onClick={() => refetch()} disabled={isFetching}>
                      {isFetching ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
              {isError && (
                <Alert severity="error" sx={{ mt: 1 }}>
                  {error instanceof Error ? error.message : 'Failed to load'}
                </Alert>
              )}
              {isLoading && <CircularProgress size={20} sx={{ mt: 2 }} />}
              {!isLoading && (eventLists?.length ?? 0) === 0 && (
                <Alert severity="info" sx={{ mt: 1 }}>
                  Nothing loaded yet — use Data Ingestion first.
                </Alert>
              )}
              <List dense>
                {(eventLists ?? []).map((ev) => (
                  <ListItemButton
                    key={ev.name}
                    selected={ev.name === selected}
                    onClick={() => setSelected(ev.name)}
                  >
                    <ListItemText
                      primary={ev.name}
                      secondary={`${ev.n_events.toLocaleString()} events`}
                      primaryTypographyProps={{ sx: mono }}
                    />
                    <IconButton
                      edge="end"
                      size="small"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteTarget(ev.name);
                      }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </ListItemButton>
                ))}
              </List>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              {!selected && (
                <Box sx={{ py: 8, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Select an event list to inspect it.
                  </Typography>
                </Box>
              )}
              {selected && (
                <>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Typography variant="h6" sx={mono}>
                      {selected}
                    </Typography>
                    {info?.mission && <Chip size="small" label={info.mission} />}
                    {info?.instrument && <Chip size="small" label={info.instrument} variant="outlined" />}
                  </Box>
                  <Tabs value={tab} onChange={(_e, v: number) => setTab(v)} sx={{ mb: 2 }}>
                    <Tab label="Overview" />
                    <Tab label="Distributions" />
                  </Tabs>

                  {infoQuery.isError && (
                    <Alert severity="error">
                      {infoQuery.error instanceof Error ? infoQuery.error.message : 'Failed to load info'}
                    </Alert>
                  )}
                  {tab === 0 && infoQuery.isLoading && <CircularProgress size={24} />}

                  {tab === 0 && info && (
                    <Grid container spacing={3}>
                      <Grid item xs={12} sm={6}>
                        <InfoRow label="Events" value={formatNum(info.n_events, 0)} />
                        <InfoRow label="Duration (s)" value={formatNum(info.duration)} />
                        <InfoRow
                          label="Time range"
                          value={`${formatNum(info.time_range?.[0])} – ${formatNum(info.time_range?.[1])}`}
                        />
                        <InfoRow label="MJDREF" value={formatNum(info.mjdref, 6)} />
                        <InfoRow label="Mean rate (cts/s)" value={formatNum(info.mean_count_rate)} />
                        <InfoRow
                          label="Energy range (keV)"
                          value={
                            info.energy_range
                              ? `${formatNum(info.energy_range[0])} – ${formatNum(info.energy_range[1])}`
                              : '—'
                          }
                        />
                        <InfoRow label="GTI count" value={formatNum(info.gti_count, 0)} />
                        <InfoRow label="Total GTI time (s)" value={formatNum(info.total_gti_time)} />
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        {(info.validation_issues ?? [])
                          .filter((v) => v.severity === 'error' || v.severity === 'warning')
                          .map((v, i) => (
                            <Alert key={i} severity={v.severity === 'error' ? 'error' : 'warning'} sx={{ mb: 1 }}>
                              {v.message}
                            </Alert>
                          ))}
                        {info.notes && (
                          <Alert severity="info" icon={false}>
                            {info.notes}
                          </Alert>
                        )}
                      </Grid>
                      {(info.gti_list?.length ?? 0) > 0 && (
                        <Grid item xs={12}>
                          <Divider sx={{ mb: 1 }} />
                          <Typography variant="subtitle2" gutterBottom>
                            Good Time Intervals
                          </Typography>
                          <TableContainer sx={{ maxHeight: 260 }}>
                            <Table size="small" stickyHeader>
                              <TableHead>
                                <TableRow>
                                  <TableCell>#</TableCell>
                                  <TableCell>Start</TableCell>
                                  <TableCell>Stop</TableCell>
                                  <TableCell>Dur. (s)</TableCell>
                                  <TableCell>Rate (cts/s)</TableCell>
                                </TableRow>
                              </TableHead>
                              <TableBody>
                                {(info.gti_list ?? []).map((g, i) => {
                                  const rate = info.per_gti_rates?.[i];
                                  return (
                                    <TableRow key={i}>
                                      <TableCell>{i + 1}</TableCell>
                                      <TableCell sx={mono}>{formatNum(g[0])}</TableCell>
                                      <TableCell sx={mono}>{formatNum(g[1])}</TableCell>
                                      <TableCell sx={mono}>{formatNum(g[1] - g[0])}</TableCell>
                                      <TableCell sx={mono}>{formatNum(rate?.rate)}</TableCell>
                                    </TableRow>
                                  );
                                })}
                              </TableBody>
                            </Table>
                          </TableContainer>
                        </Grid>
                      )}
                    </Grid>
                  )}

                  {tab === 1 && previewQuery.isLoading && <CircularProgress size={24} />}
                  {tab === 1 && previewQuery.isError && (
                    <Alert severity="error">
                      {previewQuery.error instanceof Error
                        ? previewQuery.error.message
                        : 'Failed to load preview'}
                    </Alert>
                  )}
                  {tab === 1 && preview && (
                    <Stack spacing={3}>
                      <Box>
                        <Typography variant="subtitle2" gutterBottom>
                          Arrival time distribution (preview sample)
                        </Typography>
                        <PlotlyChart
                          data={[
                            {
                              x: preview.times_preview,
                              type: 'histogram',
                              nbinsx: 200,
                              marker: { color: '#00d4aa' },
                            } as unknown as Data,
                          ]}
                          layout={{
                            xaxis: { title: { text: 'Time (s)' } },
                            yaxis: { title: { text: 'Events / bin' } },
                          }}
                          height={300}
                        />
                      </Box>
                      {preview.has_energy && preview.energy_preview && (
                        <Box>
                          <Typography variant="subtitle2" gutterBottom>
                            Energy distribution (preview sample)
                          </Typography>
                          <PlotlyChart
                            data={[
                              {
                                x: preview.energy_preview,
                                type: 'histogram',
                                nbinsx: 150,
                                marker: { color: '#3b82f6' },
                              } as unknown as Data,
                            ]}
                            layout={{
                              xaxis: { title: { text: 'Energy (keV)' } },
                              yaxis: { title: { text: 'Events / bin' } },
                            }}
                            height={300}
                          />
                        </Box>
                      )}
                    </Stack>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Dialog open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete event list?</DialogTitle>
        <DialogContent>
          <Typography>
            Remove '{deleteTarget}' from backend memory? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={() => void handleDelete()}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </PageTemplate>
  );
};

export default EventListPage;
