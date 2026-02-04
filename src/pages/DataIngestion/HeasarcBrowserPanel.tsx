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
  Alert,
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
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import PublicIcon from '@mui/icons-material/Public';
import MyLocationIcon from '@mui/icons-material/MyLocation';
import TextFieldsIcon from '@mui/icons-material/TextFields';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
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

type SearchMode = 'name' | 'coordinates';

interface FileBrowserState {
  open: boolean;
  mission: string;
  obsid: string;
  obsTime: string;
  targetName: string;
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

  // Search results state
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchResults, setSearchResults] = useState<HeasarcObservation[]>([]);
  const [searchMessage, setSearchMessage] = useState<string>('');
  const [resolvedCoords, setResolvedCoords] = useState<{ ra: number; dec: number } | null>(null);

  // File browser dialog state
  const [fileBrowser, setFileBrowser] = useState<FileBrowserState>({
    open: false,
    mission: '',
    obsid: '',
    obsTime: '',
    targetName: '',
  });

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

  // Handle search
  const handleSearch = async (): Promise<void> => {
    setIsSearching(true);
    setSearchResults([]);
    setSearchMessage('');
    setResolvedCoords(null);

    try {
      if (searchMode === 'name') {
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
        });

        if (response.success && response.data) {
          setSearchResults(response.data.observations);
          setSearchMessage(response.message);
          if (response.data.resolved_ra !== undefined && response.data.resolved_dec !== undefined) {
            setResolvedCoords({
              ra: response.data.resolved_ra,
              dec: response.data.resolved_dec,
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

  // Format coordinates
  const formatCoord = (value: number | null, decimals: number = 4): string => {
    if (value === null || value === undefined) return 'N/A';
    return value.toFixed(decimals);
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
        Search NASA's HEASARC archive for X-ray observations by source name or coordinates
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
          onChange={(_, value) => value && setSearchMode(value)}
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
        </ToggleButtonGroup>
      </Box>

      {/* Search Inputs */}
      {searchMode === 'name' ? (
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
      ) : (
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

      {/* Search Radius */}
      <TextField
        label="Search Radius (degrees)"
        value={searchRadius}
        onChange={(e) => setSearchRadius(parseFloat(e.target.value) || 0.5)}
        size="small"
        sx={{ mb: 2, width: 200 }}
        type="number"
        inputProps={{ step: 0.1, min: 0.01, max: 10 }}
      />

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

      {/* Resolved Coordinates Info */}
      {resolvedCoords && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Source resolved to: RA = {formatCoord(resolvedCoords.ra)}, Dec = {formatCoord(resolvedCoords.dec)}
        </Alert>
      )}

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
                <TableCell>Date</TableCell>
                <TableCell align="center">Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {searchResults.map((obs) => (
                <TableRow key={obs.obsid} hover>
                  <TableCell>
                    <Typography variant="body2" fontFamily="monospace">
                      {obs.obsid}
                    </Typography>
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
                    <Chip
                      label={formatExposure(obs.exposure)}
                      size="small"
                      variant="outlined"
                      color={
                        obs.exposure && obs.exposure > 10000
                          ? 'success'
                          : obs.exposure && obs.exposure > 1000
                          ? 'primary'
                          : 'default'
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary">
                      {obs.time || 'N/A'}
                    </Typography>
                  </TableCell>
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
            <li>Enter a source name or coordinates</li>
            <li>Click Search to find observations</li>
            <li>Click the folder icon to browse available files</li>
            <li>Select an event file and click Download & Load</li>
          </ol>
        </Typography>
        <Typography variant="caption" color="text.secondary">
          The file browser shows all available files in the observation directory.
          Event files are marked with a star icon.
        </Typography>
      </Box>
    </Box>
  );
};

export default HeasarcBrowserPanel;
