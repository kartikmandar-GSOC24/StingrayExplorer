/**
 * HEASARC Browser Panel
 *
 * Allows users to search and download X-ray observation data
 * from NASA's HEASARC archive.
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  IconButton,
  Collapse,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import PublicIcon from '@mui/icons-material/Public';
import MyLocationIcon from '@mui/icons-material/MyLocation';
import TextFieldsIcon from '@mui/icons-material/TextFields';
import TagIcon from '@mui/icons-material/Tag';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import FilterListIcon from '@mui/icons-material/FilterList';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import {
  archiveApi,
  HeasarcCatalog,
  HeasarcObservation,
} from '@/api/archiveApi';
import { useUIStore } from '@/store/uiStore';
import FileBrowserDialog from './FileBrowserDialog';

interface HeasarcBrowserPanelProps {
  onDataLoaded?: () => void;
}

type SearchMode = 'name' | 'coordinates' | 'obsid';
type SortOrder = 'none' | 'asc' | 'desc';

interface ObsData {
  ra?: number | null;
  dec?: number | null;
  prnb?: string;
}

interface FileBrowserState {
  open: boolean;
  mission: string;
  obsid: string;
  obsTime: string;
  targetName: string;
  obsData?: ObsData;
}

const HeasarcBrowserPanel: React.FC<HeasarcBrowserPanelProps> = ({ onDataLoaded }) => {
  const { addNotification } = useUIStore();

  // Catalogs state
  const [catalogs, setCatalogs] = useState<HeasarcCatalog[]>([]);
  const [loadingCatalogs, setLoadingCatalogs] = useState<boolean>(true);

  // Search form state
  const [searchMode, setSearchMode] = useState<SearchMode>('name');
  const [selectedMission, setSelectedMission] = useState<string>('NICER');
  const [sourceName, setSourceName] = useState<string>('');
  const [ra, setRa] = useState<string>('');
  const [dec, setDec] = useState<string>('');
  const [searchRadius, setSearchRadius] = useState<number>(0.5);
  const [obsidInput, setObsidInput] = useState<string>('');
  const [maxResults, setMaxResults] = useState<number>(100);

  // Filter state
  const [showFilters, setShowFilters] = useState<boolean>(false);
  const [minExposure, setMinExposure] = useState<string>('');
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');

  // Search results state
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchResults, setSearchResults] = useState<HeasarcObservation[]>([]);
  const [searchMessage, setSearchMessage] = useState<string>('');

  // File browser dialog state
  const [fileBrowser, setFileBrowser] = useState<FileBrowserState>({
    open: false,
    mission: '',
    obsid: '',
    obsTime: '',
    targetName: '',
  });

  // Sort state for Date/Time column
  const [dateSortOrder, setDateSortOrder] = useState<SortOrder>('none');

  // Mission-specific display flags
  const isNicer = selectedMission === 'NICER';
  const isNuSTAR = selectedMission === 'NuSTAR';

  // Fetch supported catalogs on mount
  useEffect(() => {
    const fetchCatalogs = async (): Promise<void> => {
      try {
        const response = await archiveApi.getCatalogs();
        if (response.success && response.data) {
          setCatalogs(response.data.catalogs);
        }
      } catch (error) {
        console.error('Failed to fetch catalogs:', error);
        addNotification({
          type: 'error',
          title: 'Error',
          message: 'Failed to fetch HEASARC catalogs',
        });
      } finally {
        setLoadingCatalogs(false);
      }
    };
    fetchCatalogs();
  }, [addNotification]);

  /** Build filter params for name/coordinate searches */
  const getFilterParams = (): {
    min_exposure?: number;
    start_date?: string;
    end_date?: string;
  } => {
    const params: { min_exposure?: number; start_date?: string; end_date?: string } = {};
    const minExpVal = parseFloat(minExposure);
    if (!isNaN(minExpVal) && minExpVal > 0) {
      params.min_exposure = minExpVal;
    }
    if (startDate) {
      params.start_date = startDate;
    }
    if (endDate) {
      params.end_date = endDate;
    }
    return params;
  };

  // Handle search
  const handleSearch = async (): Promise<void> => {
    setIsSearching(true);
    setSearchResults([]);
    setSearchMessage('');
    setDateSortOrder('none'); // Reset sort order on new search

    try {
      if (searchMode === 'obsid') {
        // ObsID search
        if (!obsidInput.trim()) {
          addNotification({
            type: 'warning',
            title: 'Missing Input',
            message: 'Please enter an Observation ID',
          });
          setIsSearching(false);
          return;
        }

        const response = await archiveApi.searchByObsid({
          obsid: obsidInput.trim(),
          mission: selectedMission,
        });

        if (response.success && response.data) {
          setSearchResults(response.data.observations);
          setSearchMessage(response.message);
        } else {
          addNotification({
            type: 'error',
            title: 'Search Failed',
            message: response.message || 'Search failed',
          });
        }
      } else if (searchMode === 'name') {
        if (!sourceName.trim()) {
          addNotification({
            type: 'warning',
            title: 'Missing Input',
            message: 'Please enter a source name',
          });
          setIsSearching(false);
          return;
        }

        const response = await archiveApi.searchByName({
          source_name: sourceName.trim(),
          mission: selectedMission,
          radius: searchRadius,
          max_results: maxResults,
          ...getFilterParams(),
        });

        if (response.success && response.data) {
          setSearchResults(response.data.observations);
          setSearchMessage(response.message);
          if (response.data.resolved_ra !== undefined && response.data.resolved_dec !== undefined) {
            addNotification({
              type: 'info',
              title: 'Source Resolved',
              message: `Source resolved to: RA = ${response.data.resolved_ra.toFixed(4)}, Dec = ${response.data.resolved_dec.toFixed(4)}`,
            });
          }
        } else {
          addNotification({
            type: 'error',
            title: 'Search Failed',
            message: response.message || 'Search failed',
          });
        }
      } else {
        // Coordinate search
        const raNum = parseFloat(ra);
        const decNum = parseFloat(dec);

        if (isNaN(raNum) || isNaN(decNum)) {
          addNotification({
            type: 'warning',
            title: 'Invalid Coordinates',
            message: 'Please enter valid RA and Dec values in degrees',
          });
          setIsSearching(false);
          return;
        }

        const response = await archiveApi.searchByCoordinates({
          ra: raNum,
          dec: decNum,
          mission: selectedMission,
          radius: searchRadius,
          max_results: maxResults,
          ...getFilterParams(),
        });

        if (response.success && response.data) {
          setSearchResults(response.data.observations);
          setSearchMessage(response.message);
        } else {
          addNotification({
            type: 'error',
            title: 'Search Failed',
            message: response.message || 'Search failed',
          });
        }
      }
    } catch (error) {
      console.error('Search error:', error);
      addNotification({
        type: 'error',
        title: 'Error',
        message: `Search failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
      });
    } finally {
      setIsSearching(false);
    }
  };

  // Handle opening the file browser for an observation
  const handleBrowseFiles = (obs: HeasarcObservation): void => {
    setFileBrowser({
      open: true,
      mission: selectedMission,
      obsid: obs.obsid,
      obsTime: obs.time,
      targetName: obs.name,
      obsData: {
        ra: obs.ra,
        dec: obs.dec,
        prnb: obs.prnb,
      },
    });
  };

  // Handle closing the file browser
  const handleCloseFileBrowser = (): void => {
    setFileBrowser((prev) => ({ ...prev, open: false }));
  };

  // Handle download complete - file was saved to disk
  const handleDownloadComplete = (filePath: string): void => {
    console.log('File downloaded to:', filePath);
    // Could optionally switch to the Local tab or pre-fill the file path
    onDataLoaded?.();
  };

  // Handle fallback to browse page
  const handleBrowseFallback = async (obs: HeasarcObservation): Promise<void> => {
    const response = await archiveApi.getObservationUrls(selectedMission, obs.obsid);
    if (response.success && response.data?.urls?.browse) {
      window.open(response.data.urls.browse, '_blank');
      addNotification({
        type: 'info',
        title: 'HEASARC Browser',
        message: `Opening HEASARC browse page for ${obs.obsid}. Download the event file manually.`,
      });
    }
  };

  // Format exposure time
  const formatExposure = (seconds: number | null): string => {
    if (seconds === null || seconds === undefined) return 'N/A';
    if (seconds < 60) return `${seconds.toFixed(0)}s`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
    return `${(seconds / 3600).toFixed(2)} hr`;
  };

  /**
   * Format exposure for display, with Swift instrument awareness.
   * For Swift observations where XRT exposure is 0 but BAT has data,
   * shows BAT exposure with an instrument label.
   */
  const formatObservationExposure = (obs: HeasarcObservation): { label: string; instrument: string | null } => {
    // For Swift, check instrument-specific exposures
    if (selectedMission === 'Swift' && obs.xrt_exposure !== undefined) {
      const xrt = obs.xrt_exposure ?? 0;
      const bat = obs.bat_exposure ?? 0;
      const uvot = obs.uvot_exposure ?? 0;

      if (xrt > 0) {
        return { label: formatExposure(xrt), instrument: 'XRT' };
      }
      if (bat > 0) {
        return { label: formatExposure(bat), instrument: 'BAT' };
      }
      if (uvot > 0) {
        return { label: formatExposure(uvot), instrument: 'UVOT' };
      }
      return { label: '0s', instrument: null };
    }

    // For NuSTAR: only show FPMA label when FPMB data is also available (ADQL/ObsID search)
    // query_region() doesn't return exposure_b, so don't mislead with "FPMA" label
    if (selectedMission === 'NuSTAR') {
      const instrument = obs.exposure_b != null ? 'FPMA' : null;
      return { label: formatExposure(obs.exposure), instrument };
    }

    // For IXPE, show main exposure (per-DU breakdown available in tooltip)
    if (selectedMission === 'IXPE' && obs.exposure_du1 !== undefined) {
      return { label: formatExposure(obs.exposure), instrument: null };
    }

    return { label: formatExposure(obs.exposure), instrument: null };
  };

  // Format coordinates
  const formatCoord = (value: number | null, decimals: number = 4): string => {
    if (value === null || value === undefined) return 'N/A';
    return value.toFixed(decimals);
  };

  /**
   * Convert Modified Julian Date (MJD) to human-readable date+time string.
   * MJD is days since midnight on November 17, 1858.
   * The fractional part represents the time of day.
   */
  const formatMjdToDateTime = (mjdString: string): string => {
    if (!mjdString || mjdString === 'N/A') return 'N/A';

    try {
      const mjd = parseFloat(mjdString);
      if (isNaN(mjd)) return 'N/A';

      // MJD epoch: November 17, 1858 00:00:00 UTC
      // Convert MJD to JavaScript Date
      // JD = MJD + 2400000.5
      // Unix epoch (Jan 1, 1970) = JD 2440587.5
      // So: Unix days = MJD - 40587
      const unixDays = mjd - 40587;
      const unixMs = unixDays * 24 * 60 * 60 * 1000;
      const date = new Date(unixMs);

      // Format as DD-MM-YYYY HH:MM:SS
      const day = date.getUTCDate().toString().padStart(2, '0');
      const month = (date.getUTCMonth() + 1).toString().padStart(2, '0');
      const year = date.getUTCFullYear();
      const hours = date.getUTCHours().toString().padStart(2, '0');
      const minutes = date.getUTCMinutes().toString().padStart(2, '0');
      const seconds = date.getUTCSeconds().toString().padStart(2, '0');

      return `${day}-${month}-${year} ${hours}:${minutes}:${seconds}`;
    } catch {
      return 'N/A';
    }
  };

  // Handle Date/Time column header click for sorting
  const handleDateSortClick = (): void => {
    setDateSortOrder((prev) => {
      if (prev === 'none') return 'asc';
      if (prev === 'asc') return 'desc';
      return 'none';
    });
  };

  // Get sorted results based on current sort order
  const getSortedResults = (): HeasarcObservation[] => {
    if (dateSortOrder === 'none') {
      return searchResults; // Original order from API
    }

    return [...searchResults].sort((a, b) => {
      const mjdA = parseFloat(a.time) || 0;
      const mjdB = parseFloat(b.time) || 0;

      if (dateSortOrder === 'asc') {
        return mjdA - mjdB; // Oldest first
      } else {
        return mjdB - mjdA; // Newest first
      }
    });
  };

  /** Get processing status color for NICER Chip */
  const getStatusColor = (status: string | undefined): 'success' | 'warning' | 'default' => {
    if (!status) return 'default';
    const upper = status.toUpperCase();
    if (upper === 'VALIDATED') return 'success';
    if (upper === 'PROCESSED') return 'warning';
    return 'default';
  };

  /** Get processing status tooltip description */
  const getStatusTooltip = (status: string | undefined): string => {
    if (!status) return '';
    const upper = status.toUpperCase();
    if (upper === 'VALIDATED') return 'Data is fully processed, quality-checked, and available in the archive';
    if (upper === 'PROCESSED') return 'Data has been processed but not yet validated by the NICER team';
    if (upper === 'NOTPROCESSED') return 'Data has not been processed yet';
    return status;
  };

  if (loadingCatalogs) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <PublicIcon sx={{ fontSize: 32, color: 'primary.main', mr: 1 }} />
        <Typography variant="h6">Browse HEASARC Archive</Typography>
      </Box>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Search NASA&apos;s HEASARC archive for X-ray observations by source name, coordinates, or ObsID
      </Typography>

      {/* Mission Selector */}
      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel>Mission</InputLabel>
        <Select
          value={selectedMission}
          label="Mission"
          onChange={(e) => setSelectedMission(e.target.value)}
        >
          {catalogs.map((cat) => (
            <MenuItem key={cat.id} value={cat.id}>
              {cat.display_name} - {cat.description}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Search Mode Toggle */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Search by:
        </Typography>
        <ToggleButtonGroup
          value={searchMode}
          exclusive
          onChange={(_, value: SearchMode | null) => value && setSearchMode(value)}
          size="small"
          fullWidth
        >
          <ToggleButton value="name">
            <TextFieldsIcon sx={{ mr: 1 }} />
            Source Name
          </ToggleButton>
          <ToggleButton value="coordinates">
            <MyLocationIcon sx={{ mr: 1 }} />
            Coordinates
          </ToggleButton>
          <ToggleButton value="obsid">
            <TagIcon sx={{ mr: 1 }} />
            ObsID
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {/* Search Inputs */}
      {searchMode === 'name' && (
        <TextField
          label="Source Name"
          value={sourceName}
          onChange={(e) => setSourceName(e.target.value)}
          fullWidth
          size="small"
          sx={{ mb: 2 }}
          placeholder="e.g., Crab, Cyg X-1, NGC 3783, GRS 1915+105"
          helperText="Enter an astronomical source name (resolved via SIMBAD/NED)"
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
      )}

      {searchMode === 'coordinates' && (
        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
          <TextField
            label="RA (degrees)"
            value={ra}
            onChange={(e) => setRa(e.target.value)}
            size="small"
            sx={{ flex: 1 }}
            placeholder="e.g., 83.6287"
            helperText="Right Ascension"
            type="number"
            inputProps={{ step: 0.0001 }}
          />
          <TextField
            label="Dec (degrees)"
            value={dec}
            onChange={(e) => setDec(e.target.value)}
            size="small"
            sx={{ flex: 1 }}
            placeholder="e.g., 22.0145"
            helperText="Declination"
            type="number"
            inputProps={{ step: 0.0001 }}
          />
        </Box>
      )}

      {searchMode === 'obsid' && (
        <TextField
          label="Observation ID"
          value={obsidInput}
          onChange={(e) => setObsidInput(e.target.value)}
          fullWidth
          size="small"
          sx={{ mb: 2 }}
          placeholder="e.g., 4010080142"
          helperText="Enter an exact Observation ID to look up"
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
      )}

      {/* Search Radius + Max Results (hidden for ObsID mode) */}
      {searchMode !== 'obsid' && (
        <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
          <TextField
            label="Search Radius (degrees)"
            value={searchRadius}
            onChange={(e) => setSearchRadius(parseFloat(e.target.value) || 0.5)}
            size="small"
            sx={{ width: 200 }}
            type="number"
            inputProps={{ step: 0.1, min: 0.01, max: 10 }}
          />
          <TextField
            label="Max Results"
            value={maxResults}
            onChange={(e) => {
              const val = parseInt(e.target.value, 10);
              if (!isNaN(val) && val > 0) setMaxResults(val);
            }}
            size="small"
            sx={{ width: 140 }}
            type="number"
            inputProps={{ min: 1, step: 50 }}
          />
        </Box>
      )}

      {/* Filters (shown for name/coordinates modes) */}
      {searchMode !== 'obsid' && (
        <Box sx={{ mb: 2 }}>
          <Button
            size="small"
            startIcon={<FilterListIcon />}
            onClick={() => setShowFilters(!showFilters)}
            sx={{ mb: 1, textTransform: 'none' }}
          >
            {showFilters ? 'Hide Filters' : 'Show Filters'}
          </Button>
          <Collapse in={showFilters}>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
                <TextField
                  label="Min Exposure (s)"
                  value={minExposure}
                  onChange={(e) => setMinExposure(e.target.value)}
                  size="small"
                  sx={{ width: 160 }}
                  type="number"
                  inputProps={{ min: 0, step: 100 }}
                  placeholder="e.g., 1000"
                />
                <TextField
                  label="Start Date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  size="small"
                  sx={{ width: 180 }}
                  type="date"
                  InputLabelProps={{ shrink: true }}
                />
                <TextField
                  label="End Date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  size="small"
                  sx={{ width: 180 }}
                  type="date"
                  InputLabelProps={{ shrink: true }}
                />
                {(minExposure || startDate || endDate) && (
                  <Button
                    size="small"
                    onClick={() => {
                      setMinExposure('');
                      setStartDate('');
                      setEndDate('');
                    }}
                    sx={{ textTransform: 'none' }}
                  >
                    Clear Filters
                  </Button>
                )}
              </Box>
            </Paper>
          </Collapse>
        </Box>
      )}

      {/* Search Button */}
      <Button
        variant="contained"
        onClick={handleSearch}
        disabled={isSearching}
        fullWidth
        startIcon={isSearching ? <CircularProgress size={20} /> : <SearchIcon />}
        sx={{ mb: 3 }}
      >
        {isSearching ? 'Searching...' : 'Search HEASARC'}
      </Button>

      {/* Search Results */}
      {searchMessage && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {searchMessage}
        </Typography>
      )}

      {searchResults.length > 0 && (
        <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 400 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>ObsID</TableCell>
                <TableCell>Target</TableCell>
                <TableCell align="right">RA</TableCell>
                <TableCell align="right">Dec</TableCell>
                <TableCell align="right">Exposure</TableCell>
                <TableCell
                  onClick={handleDateSortClick}
                  sx={{ cursor: 'pointer', userSelect: 'none' }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    Date/Time (UTC)
                    {dateSortOrder === 'asc' && <ArrowUpwardIcon fontSize="small" />}
                    {dateSortOrder === 'desc' && <ArrowDownwardIcon fontSize="small" />}
                  </Box>
                </TableCell>
                <TableCell>MJD</TableCell>
                {isNicer && <TableCell>Status</TableCell>}
                {isNuSTAR && <TableCell>Mode</TableCell>}
                <TableCell align="center">Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {getSortedResults().map((obs) => (
                <TableRow
                  key={obs.obsid}
                  hover
                  sx={
                    isNuSTAR && obs.observation_mode?.toUpperCase() === 'SLEW'
                      ? { opacity: 0.5 }
                      : undefined
                  }
                >
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <Typography variant="body2" fontFamily="monospace">
                        {obs.obsid}
                      </Typography>
                      {isNuSTAR && obs.issue_flag === 1 && (
                        <Tooltip title="Known issues may affect analysis">
                          <WarningAmberIcon fontSize="small" color="warning" />
                        </Tooltip>
                      )}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Tooltip title={obs.name}>
                      <Typography variant="body2" noWrap sx={{ maxWidth: 150 }}>
                        {obs.name}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body2" fontFamily="monospace">
                      {formatCoord(obs.ra)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body2" fontFamily="monospace">
                      {formatCoord(obs.dec)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    {(() => {
                      const { label, instrument } = formatObservationExposure(obs);
                      const effectiveExposure = instrument === 'BAT'
                        ? obs.bat_exposure ?? 0
                        : instrument === 'UVOT'
                        ? obs.uvot_exposure ?? 0
                        : obs.exposure ?? 0;
                      return (
                        <Tooltip
                          title={
                            selectedMission === 'Swift' && obs.xrt_exposure !== undefined
                              ? `XRT: ${formatExposure(obs.xrt_exposure ?? 0)} | BAT: ${formatExposure(obs.bat_exposure ?? 0)} | UVOT: ${formatExposure(obs.uvot_exposure ?? 0)}`
                              : selectedMission === 'NuSTAR' && obs.exposure_b != null
                              ? `FPMA: ${formatExposure(obs.exposure ?? 0)} | FPMB: ${formatExposure(obs.exposure_b)}`
                              : selectedMission === 'NuSTAR'
                              ? `Exposure: ${formatExposure(obs.exposure ?? 0)}`
                              : selectedMission === 'IXPE' && obs.exposure_du1 !== undefined
                              ? `DU1: ${formatExposure(obs.exposure_du1 ?? 0)} | DU2: ${formatExposure(obs.exposure_du2 ?? 0)} | DU3: ${formatExposure(obs.exposure_du3 ?? 0)}`
                              : ''
                          }
                        >
                          <Chip
                            label={instrument ? `${label} (${instrument})` : label}
                            size="small"
                            variant="outlined"
                            color={
                              effectiveExposure > 10000
                                ? 'success'
                                : effectiveExposure > 1000
                                ? 'primary'
                                : 'default'
                            }
                          />
                        </Tooltip>
                      );
                    })()}
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {formatMjdToDateTime(obs.time)}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary">
                      {obs.time || 'N/A'}
                    </Typography>
                  </TableCell>
                  {isNicer && (
                    <TableCell>
                      {obs.processing_status ? (
                        <Tooltip title={getStatusTooltip(obs.processing_status)}>
                          <Chip
                            label={obs.processing_status}
                            size="small"
                            color={getStatusColor(obs.processing_status)}
                            variant="outlined"
                          />
                        </Tooltip>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          —
                        </Typography>
                      )}
                    </TableCell>
                  )}
                  {isNuSTAR && (
                    <TableCell>
                      {obs.observation_mode ? (
                        <Tooltip title={
                          obs.observation_mode.toUpperCase() === 'SCIENCE'
                            ? 'Normal science observation — telescope pointed at target'
                            : obs.observation_mode.toUpperCase() === 'SLEW'
                            ? 'Telescope slewing between targets — data usually not useful for analysis'
                            : obs.observation_mode
                        }>
                          <Chip
                            label={obs.observation_mode}
                            size="small"
                            variant="outlined"
                            color={obs.observation_mode.toUpperCase() === 'SCIENCE' ? 'success' : 'default'}
                          />
                        </Tooltip>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          —
                        </Typography>
                      )}
                    </TableCell>
                  )}
                  <TableCell align="center">
                    <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'center' }}>
                      <Tooltip title="Browse and download files">
                        <IconButton
                          size="small"
                          color="primary"
                          onClick={() => handleBrowseFiles(obs)}
                        >
                          <FolderOpenIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Open in HEASARC Browser">
                        <IconButton
                          size="small"
                          color="default"
                          onClick={() => handleBrowseFallback(obs)}
                        >
                          <OpenInNewIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* File Browser Dialog */}
      <FileBrowserDialog
        open={fileBrowser.open}
        onClose={handleCloseFileBrowser}
        mission={fileBrowser.mission}
        obsid={fileBrowser.obsid}
        obsTime={fileBrowser.obsTime}
        targetName={fileBrowser.targetName}
        obsData={fileBrowser.obsData}
        onDownloadComplete={handleDownloadComplete}
      />

      {/* Help Text */}
      <Box sx={{ mt: 3, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          <strong>How to use:</strong>
        </Typography>
        <Typography variant="body2" color="text.secondary" component="div">
          <ol style={{ margin: '8px 0', paddingLeft: 20 }}>
            <li>Select a mission (e.g., NICER, NuSTAR)</li>
            <li>Enter a source name, coordinates, or ObsID</li>
            <li>Click Search to find observations</li>
            <li>Click the folder icon to browse available files</li>
            <li>Select an event file and click Download & Load</li>
          </ol>
        </Typography>
        <Typography variant="caption" color="text.secondary">
          The file browser shows all available files in the observation directory.
          Event files are marked with a star icon.
          Use &quot;Show Filters&quot; to filter by minimum exposure or date range.
        </Typography>
      </Box>
    </Box>
  );
};

export default HeasarcBrowserPanel;
