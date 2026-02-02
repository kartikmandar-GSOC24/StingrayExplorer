import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Typography,
  Paper,
  Button,
  Grid,
  Card,
  CardContent,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  CircularProgress,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
  Chip,
  Divider,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Collapse,
  LinearProgress,
  FormControlLabel,
  Checkbox,
  Slider,
  Tabs,
  Tab,
} from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import DeleteIcon from '@mui/icons-material/Delete';
import RefreshIcon from '@mui/icons-material/Refresh';
import InfoIcon from '@mui/icons-material/Info';
import CloseIcon from '@mui/icons-material/Close';
import LinkIcon from '@mui/icons-material/Link';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import SettingsIcon from '@mui/icons-material/Settings';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import SaveIcon from '@mui/icons-material/Save';
import ClearAllIcon from '@mui/icons-material/ClearAll';
import VisibilityIcon from '@mui/icons-material/Visibility';
import SpeedIcon from '@mui/icons-material/Speed';
import MemoryIcon from '@mui/icons-material/Memory';
import { dataApi, EventListSummary, EventListInfo, FileSizeInfo, EventListFullPreview } from '@/api/dataApi';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/store/uiStore';

type AlertSeverity = 'success' | 'error' | 'warning' | 'info';

interface AlertState {
  open: boolean;
  message: string;
  severity: AlertSeverity;
}

const DataIngestionPage: React.FC = () => {
  // Global notification store
  const { addNotification } = useUIStore();

  // Form state - Local File
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [eventListName, setEventListName] = useState<string>('');
  const [fileFormat, setFileFormat] = useState<string>('ogip');
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Advanced options state
  const [showAdvancedOptions, setShowAdvancedOptions] = useState<boolean>(false);
  const [rmfFile, setRmfFile] = useState<string>('');
  const [additionalColumns, setAdditionalColumns] = useState<string>('');
  const [fileSizeInfo, setFileSizeInfo] = useState<FileSizeInfo | null>(null);
  const [isCheckingFileSize, setIsCheckingFileSize] = useState<boolean>(false);

  // Lazy loading options
  const [useLazyLoading, setUseLazyLoading] = useState<boolean>(false);
  const [usePreviewMode, setUsePreviewMode] = useState<boolean>(false);
  const [previewDuration, setPreviewDuration] = useState<number>(100);

  // Form state - URL Loading
  const [urlInput, setUrlInput] = useState<string>('');
  const [urlEventListName, setUrlEventListName] = useState<string>('');
  const [urlFormat, setUrlFormat] = useState<string>('ogip');
  const [isLoadingUrl, setIsLoadingUrl] = useState<boolean>(false);

  // Loaded data state
  const [loadedEventLists, setLoadedEventLists] = useState<EventListSummary[]>([]);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // Alert state (local page alert)
  const [alert, setAlert] = useState<AlertState>({
    open: false,
    message: '',
    severity: 'info',
  });

  // Details dialog state
  const [detailsOpen, setDetailsOpen] = useState<boolean>(false);
  const [detailsLoading, setDetailsLoading] = useState<boolean>(false);
  const [selectedEventListDetails, setSelectedEventListDetails] = useState<EventListInfo | null>(null);

  // Full preview dialog state
  const [fullPreviewOpen, setFullPreviewOpen] = useState<boolean>(false);
  const [fullPreviewLoading, setFullPreviewLoading] = useState<boolean>(false);
  const [fullPreviewData, setFullPreviewData] = useState<EventListFullPreview | null>(null);
  const [previewTabValue, setPreviewTabValue] = useState<number>(0);

  // Fetch loaded event lists on mount and after operations
  const fetchEventLists = useCallback(async (): Promise<void> => {
    setIsRefreshing(true);
    try {
      // Ensure we have the correct port
      await apiClient.getPort();
      const response = await dataApi.listEventLists();
      if (response.success && response.data) {
        setLoadedEventLists(response.data);
      }
    } catch (error) {
      console.error('Failed to fetch event lists:', error);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchEventLists();
  }, [fetchEventLists]);

  // Show alert helper - uses global notifications for success/error, local alert for warnings/info
  const showAlert = (message: string, severity: AlertSeverity, title?: string): void => {
    if (severity === 'success' || severity === 'error') {
      // Use global notification for success/error (no local alert to avoid duplication)
      addNotification({
        type: severity === 'success' ? 'success' : 'error',
        title: title || (severity === 'success' ? 'Success' : 'Error'),
        message,
      });
      // Clear any existing local alert
      setAlert({ open: false, message: '', severity: 'info' });
    } else {
      // Use local page alert for warnings/info (immediate feedback without cluttering notifications)
      setAlert({ open: true, message, severity });
    }
  };

  // Check file size when file is selected
  const checkFileSize = async (filePath: string): Promise<void> => {
    setIsCheckingFileSize(true);
    try {
      await apiClient.getPort();
      const response = await dataApi.checkFileSize(filePath);
      if (response.success && response.data) {
        setFileSizeInfo(response.data);
        // Auto-enable lazy loading if recommended
        if (response.data.recommend_lazy && !useLazyLoading) {
          setUseLazyLoading(true);
        }
        // Auto-enable preview mode for critical files
        if (response.data.risk_level === 'critical' && !usePreviewMode) {
          setUsePreviewMode(true);
        }
      }
    } catch (error) {
      console.error('Failed to check file size:', error);
      setFileSizeInfo(null);
    } finally {
      setIsCheckingFileSize(false);
    }
  };

  // Handle file selection via Electron dialog
  const handleBrowseFiles = async (): Promise<void> => {
    if (!window.electronAPI) {
      showAlert('File dialog not available (Electron API not found)', 'error');
      return;
    }

    const files = await window.electronAPI.openFile({
      title: 'Select Event List Files',
      filters: [
        { name: 'FITS Files', extensions: ['fits', 'fit', 'fts', 'evt'] },
        { name: 'HDF5 Files', extensions: ['hdf5', 'h5'] },
        { name: 'Text Files', extensions: ['txt', 'csv', 'dat'] },
        { name: 'All Files', extensions: ['*'] },
      ],
      multiple: false,
    });

    if (files && files.length > 0) {
      setSelectedFiles(files);
      // Auto-generate name from filename
      const fileName = files[0].split('/').pop()?.split('.')[0] || '';
      if (!eventListName) {
        setEventListName(fileName);
      }
      // Check file size
      checkFileSize(files[0]);
    }
  };

  // Handle RMF file selection
  const handleBrowseRmfFile = async (): Promise<void> => {
    if (!window.electronAPI) {
      showAlert('File dialog not available (Electron API not found)', 'error');
      return;
    }

    const files = await window.electronAPI.openFile({
      title: 'Select RMF (Response Matrix) File',
      filters: [
        { name: 'RMF Files', extensions: ['rmf', 'rsp'] },
        { name: 'FITS Files', extensions: ['fits', 'fit'] },
        { name: 'All Files', extensions: ['*'] },
      ],
      multiple: false,
    });

    if (files && files.length > 0) {
      setRmfFile(files[0]);
    }
  };

  // Handle loading the selected file
  const handleLoadFile = async (): Promise<void> => {
    if (selectedFiles.length === 0) {
      showAlert('Please select a file first', 'warning');
      return;
    }

    if (!eventListName.trim()) {
      showAlert('Please provide a name for the Event List', 'warning');
      return;
    }

    setIsLoading(true);
    setAlert({ open: false, message: '', severity: 'info' });

    try {
      // Ensure we have the correct port
      await apiClient.getPort();

      // Parse additional columns if provided
      const additionalColumnsArray = additionalColumns.trim()
        ? additionalColumns.split(',').map((col) => col.trim()).filter((col) => col)
        : undefined;

      let response;

      if (usePreviewMode) {
        // Use preview mode for extremely large files
        response = await dataApi.loadEventListPreview({
          file_path: selectedFiles[0],
          name: eventListName.trim(),
          preview_duration: previewDuration,
          fmt: fileFormat,
        });
      } else if (useLazyLoading) {
        // Use lazy loading for large files
        response = await dataApi.loadEventListLazy({
          file_path: selectedFiles[0],
          name: eventListName.trim(),
          fmt: fileFormat,
          rmf_file: rmfFile || undefined,
          additional_columns: additionalColumnsArray,
        });
      } else {
        // Standard loading
        response = await dataApi.loadEventList({
          file_path: selectedFiles[0],
          name: eventListName.trim(),
          fmt: fileFormat,
          rmf_file: rmfFile || undefined,
          additional_columns: additionalColumnsArray,
        });
      }

      if (response.success) {
        const loadMethod = usePreviewMode ? ' (Preview Mode)' : useLazyLoading ? ' (Lazy Loading)' : '';
        showAlert(response.message || `Event List loaded successfully!${loadMethod}`, 'success', 'Data Loaded');
        // Reset form
        setSelectedFiles([]);
        setEventListName('');
        setRmfFile('');
        setAdditionalColumns('');
        setFileSizeInfo(null);
        setUseLazyLoading(false);
        setUsePreviewMode(false);
        // Refresh the list
        await fetchEventLists();
      } else {
        showAlert(response.message || 'Failed to load Event List', 'error', 'Load Failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      showAlert(`Error: ${errorMessage}`, 'error', 'Load Error');
    } finally {
      setIsLoading(false);
    }
  };

  // Handle deleting an event list
  const handleDeleteEventList = async (name: string): Promise<void> => {
    try {
      await apiClient.getPort();
      const response = await dataApi.deleteEventList(name);

      if (response.success) {
        showAlert(`Event List '${name}' deleted`, 'success', 'Data Deleted');
        await fetchEventLists();
      } else {
        showAlert(response.message || 'Failed to delete Event List', 'error', 'Delete Failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      showAlert(`Error: ${errorMessage}`, 'error', 'Delete Error');
    }
  };

  // Handle saving an event list to disk
  const handleSaveEventList = async (name: string): Promise<void> => {
    if (!window.electronAPI) {
      showAlert('Save dialog not available (Electron API not found)', 'error');
      return;
    }

    const filePath = await window.electronAPI.saveFile({
      title: `Save Event List: ${name}`,
      defaultPath: `${name}.fits`,
      filters: [
        { name: 'FITS Files', extensions: ['fits'] },
        { name: 'HDF5 Files', extensions: ['hdf5', 'h5'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    });

    if (!filePath) {
      return; // User cancelled
    }

    try {
      await apiClient.getPort();

      // Determine format from file extension
      const ext = filePath.split('.').pop()?.toLowerCase();
      let fmt = 'fits';
      if (ext === 'hdf5' || ext === 'h5') {
        fmt = 'hdf5';
      }

      const response = await dataApi.saveEventList({
        name,
        file_path: filePath,
        fmt,
      });

      if (response.success) {
        showAlert(`Event List '${name}' saved to ${filePath}`, 'success', 'Data Saved');
      } else {
        showAlert(response.message || 'Failed to save Event List', 'error', 'Save Failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      showAlert(`Error: ${errorMessage}`, 'error', 'Save Error');
    }
  };

  // Handle clearing all event lists
  const handleClearAll = async (): Promise<void> => {
    if (loadedEventLists.length === 0) {
      showAlert('No event lists to clear', 'warning');
      return;
    }

    try {
      await apiClient.getPort();
      const response = await dataApi.clearAllEventLists();

      if (response.success) {
        showAlert(response.message || 'All event lists cleared', 'success', 'Data Cleared');
        await fetchEventLists();
      } else {
        showAlert(response.message || 'Failed to clear event lists', 'error', 'Clear Failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      showAlert(`Error: ${errorMessage}`, 'error', 'Clear Error');
    }
  };

  // Handle loading from URL
  const handleLoadFromUrl = async (): Promise<void> => {
    if (!urlInput.trim()) {
      showAlert('Please enter a URL', 'warning');
      return;
    }

    if (!urlEventListName.trim()) {
      showAlert('Please provide a name for the Event List', 'warning');
      return;
    }

    // Basic URL validation
    try {
      new URL(urlInput.trim());
    } catch {
      showAlert('Please enter a valid URL', 'warning');
      return;
    }

    setIsLoadingUrl(true);
    setAlert({ open: false, message: '', severity: 'info' });

    try {
      await apiClient.getPort();

      const response = await dataApi.loadEventListFromUrl({
        url: urlInput.trim(),
        name: urlEventListName.trim(),
        fmt: urlFormat,
      });

      if (response.success) {
        showAlert(response.message || 'Event List loaded from URL successfully!', 'success', 'URL Data Loaded');
        // Reset form
        setUrlInput('');
        setUrlEventListName('');
        // Refresh the list
        await fetchEventLists();
      } else {
        showAlert(response.message || 'Failed to load Event List from URL', 'error', 'URL Load Failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      showAlert(`Error: ${errorMessage}`, 'error', 'URL Load Error');
    } finally {
      setIsLoadingUrl(false);
    }
  };

  // Handle viewing event list details
  const handleViewDetails = async (name: string): Promise<void> => {
    setDetailsLoading(true);
    setDetailsOpen(true);

    try {
      await apiClient.getPort();
      const response = await dataApi.getEventListInfo(name);

      if (response.success && response.data) {
        setSelectedEventListDetails(response.data);
      } else {
        showAlert(response.message || 'Failed to fetch details', 'error', 'Details Error');
        setDetailsOpen(false);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      showAlert(`Error: ${errorMessage}`, 'error', 'Details Error');
      setDetailsOpen(false);
    } finally {
      setDetailsLoading(false);
    }
  };

  // Close details dialog
  const handleCloseDetails = (): void => {
    setDetailsOpen(false);
    setSelectedEventListDetails(null);
  };

  // Handle viewing full preview of event list
  const handleViewFullPreview = async (name: string): Promise<void> => {
    setFullPreviewLoading(true);
    setFullPreviewOpen(true);
    setPreviewTabValue(0);

    try {
      await apiClient.getPort();
      const response = await dataApi.getEventListFullPreview(name, 10);

      if (response.success && response.data) {
        setFullPreviewData(response.data);
      } else {
        showAlert(response.message || 'Failed to fetch full preview', 'error', 'Preview Error');
        setFullPreviewOpen(false);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      showAlert(`Error: ${errorMessage}`, 'error', 'Preview Error');
      setFullPreviewOpen(false);
    } finally {
      setFullPreviewLoading(false);
    }
  };

  // Close full preview dialog
  const handleCloseFullPreview = (): void => {
    setFullPreviewOpen(false);
    setFullPreviewData(null);
    setPreviewTabValue(0);
  };

  // Format number with commas
  const formatNumber = (num: number): string => {
    return num.toLocaleString();
  };

  // Format time range
  const formatTimeRange = (range: [number, number]): string => {
    const duration = range[1] - range[0];
    return `${duration.toFixed(2)}s`;
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Data Ingestion
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 4 }}>
        Load X-ray astronomy event list files for analysis
      </Typography>

      {/* Alert */}
      {alert.open && (
        <Alert
          severity={alert.severity}
          onClose={() => setAlert({ ...alert, open: false })}
          sx={{ mb: 3 }}
        >
          {alert.message}
        </Alert>
      )}

      <Grid container spacing={3}>
        {/* Load from Local File */}
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <UploadFileIcon sx={{ fontSize: 32, color: 'primary.main', mr: 1 }} />
                <Typography variant="h6">Load Local File</Typography>
              </Box>

              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                Load FITS, HDF5, or text event list files from your computer
              </Typography>

              {/* File Selection */}
              <Box sx={{ mb: 2 }}>
                <Button
                  variant="outlined"
                  startIcon={<FolderOpenIcon />}
                  onClick={handleBrowseFiles}
                  fullWidth
                  sx={{ mb: 1 }}
                >
                  Browse Files
                </Button>
                {selectedFiles.length > 0 && (
                  <Typography variant="body2" color="text.secondary" noWrap>
                    Selected: {selectedFiles[0].split('/').pop()}
                  </Typography>
                )}
                {/* File Size Info */}
                {isCheckingFileSize && (
                  <Box sx={{ mt: 1 }}>
                    <LinearProgress />
                    <Typography variant="caption" color="text.secondary">
                      Checking file size...
                    </Typography>
                  </Box>
                )}
                {fileSizeInfo && !isCheckingFileSize && (
                  <Box
                    sx={{
                      mt: 1,
                      p: 1.5,
                      borderRadius: 1,
                      bgcolor: fileSizeInfo.risk_level === 'safe' ? 'success.50' :
                               fileSizeInfo.risk_level === 'caution' ? 'warning.50' :
                               'error.50',
                      border: '1px solid',
                      borderColor: fileSizeInfo.risk_level === 'safe' ? 'success.main' :
                                   fileSizeInfo.risk_level === 'caution' ? 'warning.main' :
                                   'error.main',
                    }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      {fileSizeInfo.risk_level === 'safe' ? (
                        <CheckCircleIcon fontSize="small" color="success" />
                      ) : (
                        <WarningAmberIcon fontSize="small" color={fileSizeInfo.risk_level === 'caution' ? 'warning' : 'error'} />
                      )}
                      <Typography variant="body2" fontWeight="medium">
                        {fileSizeInfo.file_size_mb < 1
                          ? `${(fileSizeInfo.file_size_bytes / 1024).toFixed(1)} KB`
                          : fileSizeInfo.file_size_gb >= 1
                          ? `${fileSizeInfo.file_size_gb.toFixed(2)} GB`
                          : `${fileSizeInfo.file_size_mb.toFixed(1)} MB`}
                      </Typography>
                      <Chip
                        label={fileSizeInfo.risk_level.toUpperCase()}
                        size="small"
                        color={fileSizeInfo.risk_level === 'safe' ? 'success' :
                               fileSizeInfo.risk_level === 'caution' ? 'warning' : 'error'}
                        sx={{ ml: 'auto' }}
                      />
                    </Box>
                    {fileSizeInfo.estimated_memory_mb && fileSizeInfo.memory_info && (
                      <Box sx={{ display: 'flex', gap: 2, mt: 0.5, flexWrap: 'wrap' }}>
                        <Typography variant="caption" color="text.secondary">
                          Est. Memory: ~{fileSizeInfo.estimated_memory_mb.toFixed(0)} MB
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          Available RAM: {fileSizeInfo.memory_info.available_mb.toFixed(0)} MB ({(100 - fileSizeInfo.memory_info.percent).toFixed(0)}% free)
                        </Typography>
                      </Box>
                    )}
                    {fileSizeInfo.recommend_lazy && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                        Large file detected. Lazy loading has been auto-enabled.
                      </Typography>
                    )}
                    {fileSizeInfo.risk_level === 'critical' && (
                      <Typography variant="caption" color="error" sx={{ display: 'block', mt: 0.5 }}>
                        Critical: File may be too large to load. Consider using Preview Mode.
                      </Typography>
                    )}
                  </Box>
                )}
              </Box>

              {/* Event List Name */}
              <TextField
                label="Event List Name"
                value={eventListName}
                onChange={(e) => setEventListName(e.target.value)}
                fullWidth
                size="small"
                sx={{ mb: 2 }}
                placeholder="Enter a name for this event list"
                helperText="This name will be used to reference the data"
              />

              {/* File Format */}
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>File Format</InputLabel>
                <Select
                  value={fileFormat}
                  label="File Format"
                  onChange={(e) => setFileFormat(e.target.value)}
                >
                  <MenuItem value="ogip">OGIP/FITS (recommended)</MenuItem>
                  <MenuItem value="hdf5">HDF5</MenuItem>
                  <MenuItem value="fits">FITS (generic)</MenuItem>
                  <MenuItem value="ascii.ecsv">ASCII ECSV</MenuItem>
                </Select>
              </FormControl>

              {/* Advanced Options Toggle */}
              <Button
                size="small"
                onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
                startIcon={<SettingsIcon />}
                endIcon={showAdvancedOptions ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                sx={{ mb: 2, textTransform: 'none' }}
              >
                Advanced Options
              </Button>

              {/* Advanced Options Content */}
              <Collapse in={showAdvancedOptions}>
                <Box sx={{ mb: 2, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
                  {/* RMF File */}
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    RMF File (for PI → Energy calibration)
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                    <TextField
                      value={rmfFile}
                      onChange={(e) => setRmfFile(e.target.value)}
                      fullWidth
                      size="small"
                      placeholder="Optional: Path to RMF file"
                      InputProps={{
                        readOnly: true,
                      }}
                    />
                    <Button
                      variant="outlined"
                      size="small"
                      onClick={handleBrowseRmfFile}
                      sx={{ minWidth: 'auto', px: 2 }}
                    >
                      Browse
                    </Button>
                    {rmfFile && (
                      <IconButton size="small" onClick={() => setRmfFile('')}>
                        <CloseIcon fontSize="small" />
                      </IconButton>
                    )}
                  </Box>

                  {/* Additional Columns */}
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    Additional Columns
                  </Typography>
                  <TextField
                    value={additionalColumns}
                    onChange={(e) => setAdditionalColumns(e.target.value)}
                    fullWidth
                    size="small"
                    placeholder="e.g., PI, ENERGY, DET_ID (comma-separated)"
                    helperText="Extra columns to read from the file"
                    sx={{ mb: 2 }}
                  />

                  <Divider sx={{ my: 2 }} />

                  {/* Loading Options */}
                  <Typography variant="subtitle2" color="primary" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                    <MemoryIcon fontSize="small" />
                    Loading Options
                  </Typography>

                  {/* Lazy Loading */}
                  <Tooltip title="Recommended for files >1GB. Uses memory-efficient loading that checks available RAM before loading.">
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={useLazyLoading}
                          onChange={(e) => {
                            setUseLazyLoading(e.target.checked);
                            if (e.target.checked) setUsePreviewMode(false);
                          }}
                          size="small"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <SpeedIcon fontSize="small" color="primary" />
                          <Typography variant="body2">Use lazy loading (recommended for large files)</Typography>
                        </Box>
                      }
                    />
                  </Tooltip>

                  {/* Preview Mode */}
                  <Tooltip title="Load only the first segment of data. Useful for extremely large files that cannot fit in memory.">
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={usePreviewMode}
                          onChange={(e) => {
                            setUsePreviewMode(e.target.checked);
                            if (e.target.checked) setUseLazyLoading(false);
                          }}
                          size="small"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <VisibilityIcon fontSize="small" color="secondary" />
                          <Typography variant="body2">Preview mode (load only first segment)</Typography>
                        </Box>
                      }
                    />
                  </Tooltip>

                  {/* Preview Duration Slider */}
                  {usePreviewMode && (
                    <Box sx={{ mt: 2, px: 1 }}>
                      <Typography variant="caption" color="text.secondary" gutterBottom>
                        Preview Duration: {previewDuration}s
                      </Typography>
                      <Slider
                        value={previewDuration}
                        onChange={(_, value) => setPreviewDuration(value as number)}
                        min={10}
                        max={1000}
                        step={10}
                        marks={[
                          { value: 10, label: '10s' },
                          { value: 100, label: '100s' },
                          { value: 500, label: '500s' },
                          { value: 1000, label: '1000s' },
                        ]}
                        size="small"
                      />
                    </Box>
                  )}

                  {/* Loading mode indicator */}
                  {(useLazyLoading || usePreviewMode) && (
                    <Alert severity="info" sx={{ mt: 2 }} icon={useLazyLoading ? <SpeedIcon /> : <VisibilityIcon />}>
                      {useLazyLoading
                        ? 'Lazy loading enabled: Memory usage will be checked before loading.'
                        : `Preview mode: Only the first ${previewDuration}s of data will be loaded.`}
                    </Alert>
                  )}
                </Box>
              </Collapse>

              {/* Load Button */}
              <Button
                variant="contained"
                onClick={handleLoadFile}
                disabled={isLoading || selectedFiles.length === 0}
                fullWidth
                startIcon={isLoading ? <CircularProgress size={20} /> : <UploadFileIcon />}
              >
                {isLoading ? 'Loading...' : 'Load Event List'}
              </Button>
            </CardContent>
          </Card>
        </Grid>

        {/* Load from URL */}
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <CloudUploadIcon sx={{ fontSize: 32, color: 'primary.main', mr: 1 }} />
                <Typography variant="h6">Load from URL</Typography>
              </Box>

              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                Fetch event list data directly from a remote URL (use raw links for GitHub)
              </Typography>

              {/* URL Input */}
              <TextField
                label="URL"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                fullWidth
                size="small"
                sx={{ mb: 2 }}
                placeholder="https://example.com/data/events.fits"
                helperText="Enter the direct link to the event file"
                InputProps={{
                  startAdornment: <LinkIcon sx={{ mr: 1, color: 'text.secondary' }} />,
                }}
              />

              {/* Event List Name */}
              <TextField
                label="Event List Name"
                value={urlEventListName}
                onChange={(e) => setUrlEventListName(e.target.value)}
                fullWidth
                size="small"
                sx={{ mb: 2 }}
                placeholder="Enter a name for this event list"
                helperText="This name will be used to reference the data"
              />

              {/* File Format */}
              <FormControl fullWidth size="small" sx={{ mb: 3 }}>
                <InputLabel>File Format</InputLabel>
                <Select
                  value={urlFormat}
                  label="File Format"
                  onChange={(e) => setUrlFormat(e.target.value)}
                >
                  <MenuItem value="ogip">OGIP/FITS (recommended)</MenuItem>
                  <MenuItem value="hdf5">HDF5</MenuItem>
                  <MenuItem value="fits">FITS (generic)</MenuItem>
                  <MenuItem value="ascii.ecsv">ASCII ECSV</MenuItem>
                </Select>
              </FormControl>

              {/* Load Button */}
              <Button
                variant="contained"
                onClick={handleLoadFromUrl}
                disabled={isLoadingUrl || !urlInput.trim()}
                fullWidth
                startIcon={isLoadingUrl ? <CircularProgress size={20} /> : <CloudUploadIcon />}
              >
                {isLoadingUrl ? 'Fetching...' : 'Fetch from URL'}
              </Button>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Loaded Event Lists */}
      <Paper variant="outlined" sx={{ mt: 4, p: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">Loaded Event Lists</Typography>
          <Box sx={{ display: 'flex', gap: 1 }}>
            {loadedEventLists.length > 0 && (
              <Button
                size="small"
                color="warning"
                startIcon={<ClearAllIcon />}
                onClick={handleClearAll}
                sx={{ textTransform: 'none' }}
              >
                Clear All
              </Button>
            )}
            <Tooltip title="Refresh list">
              <IconButton onClick={fetchEventLists} disabled={isRefreshing} size="small">
                <RefreshIcon sx={{ animation: isRefreshing ? 'spin 1s linear infinite' : 'none' }} />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        {loadedEventLists.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No event lists loaded yet. Use the options above to load your data.
          </Typography>
        ) : (
          <List>
            {loadedEventLists.map((eventList, index) => (
              <React.Fragment key={eventList.name}>
                {index > 0 && <Divider />}
                <ListItem>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="subtitle1" fontWeight="medium">
                          {eventList.name}
                        </Typography>
                        {eventList.has_energy && (
                          <Chip label="Energy" size="small" color="primary" variant="outlined" />
                        )}
                        {eventList.has_pi && (
                          <Chip label="PI" size="small" color="secondary" variant="outlined" />
                        )}
                      </Box>
                    }
                    secondary={
                      <Box sx={{ mt: 0.5 }}>
                        <Typography variant="body2" color="text.secondary" component="span">
                          {formatNumber(eventList.n_events)} events
                        </Typography>
                        <Typography variant="body2" color="text.secondary" component="span" sx={{ mx: 1 }}>
                          •
                        </Typography>
                        <Typography variant="body2" color="text.secondary" component="span">
                          Duration: {formatTimeRange(eventList.time_range)}
                        </Typography>
                        {eventList.gti_count !== undefined && eventList.gti_count > 0 && (
                          <>
                            <Typography variant="body2" color="text.secondary" component="span" sx={{ mx: 1 }}>
                              •
                            </Typography>
                            <Typography variant="body2" color="text.secondary" component="span">
                              {eventList.gti_count} GTI(s)
                            </Typography>
                          </>
                        )}
                      </Box>
                    }
                  />
                  <ListItemSecondaryAction>
                    <Tooltip title="View details">
                      <IconButton
                        edge="end"
                        sx={{ mr: 0.5 }}
                        onClick={() => handleViewDetails(eventList.name)}
                      >
                        <InfoIcon />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Full preview with all attributes">
                      <IconButton
                        edge="end"
                        sx={{ mr: 0.5 }}
                        onClick={() => handleViewFullPreview(eventList.name)}
                        color="secondary"
                      >
                        <VisibilityIcon />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Save to disk">
                      <IconButton
                        edge="end"
                        sx={{ mr: 0.5 }}
                        onClick={() => handleSaveEventList(eventList.name)}
                        color="primary"
                      >
                        <SaveIcon />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton
                        edge="end"
                        onClick={() => handleDeleteEventList(eventList.name)}
                        color="error"
                      >
                        <DeleteIcon />
                      </IconButton>
                    </Tooltip>
                  </ListItemSecondaryAction>
                </ListItem>
              </React.Fragment>
            ))}
          </List>
        )}
      </Paper>

      {/* Event List Details Dialog */}
      <Dialog
        open={detailsOpen}
        onClose={handleCloseDetails}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="h6">
            Event List Details: {selectedEventListDetails?.name || ''}
          </Typography>
          <IconButton onClick={handleCloseDetails} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {detailsLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : selectedEventListDetails ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {/* Basic Info */}
              <Box>
                <Typography variant="subtitle2" color="primary" gutterBottom>
                  Basic Information
                </Typography>
                <Grid container spacing={2}>
                  <Grid item xs={6} sm={4}>
                    <Typography variant="caption" color="text.secondary">Events</Typography>
                    <Typography variant="body1">{formatNumber(selectedEventListDetails.n_events)}</Typography>
                  </Grid>
                  <Grid item xs={6} sm={4}>
                    <Typography variant="caption" color="text.secondary">Duration</Typography>
                    <Typography variant="body1">{selectedEventListDetails.duration.toFixed(2)}s</Typography>
                  </Grid>
                  <Grid item xs={6} sm={4}>
                    <Typography variant="caption" color="text.secondary">Mean Count Rate</Typography>
                    <Typography variant="body1">
                      {selectedEventListDetails.mean_count_rate?.toFixed(2) || 'N/A'} cts/s
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={4}>
                    <Typography variant="caption" color="text.secondary">MJDREF</Typography>
                    <Typography variant="body1">{selectedEventListDetails.mjdref || 'N/A'}</Typography>
                  </Grid>
                  {selectedEventListDetails.mission && (
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Mission</Typography>
                      <Typography variant="body1">{selectedEventListDetails.mission}</Typography>
                    </Grid>
                  )}
                  {selectedEventListDetails.instrument && (
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Instrument</Typography>
                      <Typography variant="body1">{selectedEventListDetails.instrument}</Typography>
                    </Grid>
                  )}
                </Grid>
              </Box>

              <Divider />

              {/* Time Range */}
              <Box>
                <Typography variant="subtitle2" color="primary" gutterBottom>
                  Time Information
                </Typography>
                <Grid container spacing={2}>
                  <Grid item xs={6} sm={4}>
                    <Typography variant="caption" color="text.secondary">Start Time</Typography>
                    <Typography variant="body1">{selectedEventListDetails.time_range[0].toFixed(6)}</Typography>
                  </Grid>
                  <Grid item xs={6} sm={4}>
                    <Typography variant="caption" color="text.secondary">End Time</Typography>
                    <Typography variant="body1">{selectedEventListDetails.time_range[1].toFixed(6)}</Typography>
                  </Grid>
                  {selectedEventListDetails.min_time_diff !== undefined && (
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Min Time Diff</Typography>
                      <Typography variant="body1">{selectedEventListDetails.min_time_diff.toExponential(3)}s</Typography>
                    </Grid>
                  )}
                </Grid>
              </Box>

              <Divider />

              {/* Data Columns */}
              <Box>
                <Typography variant="subtitle2" color="primary" gutterBottom>
                  Data Columns
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  <Chip label="Time" color="primary" size="small" />
                  {selectedEventListDetails.has_energy && (
                    <Chip
                      label={`Energy${selectedEventListDetails.energy_range ? ` (${selectedEventListDetails.energy_range[0].toFixed(2)}-${selectedEventListDetails.energy_range[1].toFixed(2)} keV)` : ''}`}
                      color="success"
                      size="small"
                    />
                  )}
                  {selectedEventListDetails.has_pi && (
                    <Chip
                      label={`PI${selectedEventListDetails.pi_range ? ` (${selectedEventListDetails.pi_range[0]}-${selectedEventListDetails.pi_range[1]})` : ''}`}
                      color="secondary"
                      size="small"
                    />
                  )}
                </Box>
              </Box>

              {/* GTI Table */}
              {selectedEventListDetails.gti_list && selectedEventListDetails.gti_list.length > 0 && (
                <>
                  <Divider />
                  <Box>
                    <Typography variant="subtitle2" color="primary" gutterBottom>
                      Good Time Intervals ({selectedEventListDetails.gti_count} GTI{selectedEventListDetails.gti_count !== 1 ? 's' : ''})
                      {selectedEventListDetails.total_gti_time && (
                        <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                          Total: {selectedEventListDetails.total_gti_time.toFixed(2)}s
                        </Typography>
                      )}
                    </Typography>
                    <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 200 }}>
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            <TableCell>#</TableCell>
                            <TableCell>Start</TableCell>
                            <TableCell>Stop</TableCell>
                            <TableCell>Duration</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {selectedEventListDetails.gti_list.map((gti, index) => (
                            <TableRow key={index}>
                              <TableCell>{index + 1}</TableCell>
                              <TableCell>{gti[0].toFixed(4)}</TableCell>
                              <TableCell>{gti[1].toFixed(4)}</TableCell>
                              <TableCell>{(gti[1] - gti[0]).toFixed(4)}s</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Box>
                </>
              )}
            </Box>
          ) : (
            <Typography color="text.secondary">No details available</Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDetails}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Full Preview Dialog */}
      <Dialog
        open={fullPreviewOpen}
        onClose={handleCloseFullPreview}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <VisibilityIcon color="secondary" />
            <Typography variant="h6">
              Full Preview: {fullPreviewData?.name || ''}
            </Typography>
          </Box>
          <IconButton onClick={handleCloseFullPreview} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {fullPreviewLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : fullPreviewData ? (
            <Box>
              {/* Tabs for different sections */}
              <Tabs
                value={previewTabValue}
                onChange={(_, newValue) => setPreviewTabValue(newValue)}
                sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
              >
                <Tab label="Overview" />
                <Tab label="Time Data" />
                <Tab label="Energy & PI" />
                <Tab label="GTIs" />
                <Tab label="Metadata" />
              </Tabs>

              {/* Overview Tab */}
              {previewTabValue === 0 && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <Grid container spacing={2}>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                        <Typography variant="h4" color="primary">
                          {formatNumber(fullPreviewData.n_events)}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">Total Events</Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                        <Typography variant="h4" color="secondary">
                          {fullPreviewData.duration.toFixed(2)}s
                        </Typography>
                        <Typography variant="caption" color="text.secondary">Duration</Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                        <Typography variant="h4" color="success.main">
                          {fullPreviewData.mean_count_rate?.toFixed(1) || 'N/A'}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">Mean Count Rate (cts/s)</Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                        <Typography variant="h4" color="info.main">
                          {fullPreviewData.gti_count}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">GTI Count</Typography>
                      </Paper>
                    </Grid>
                  </Grid>

                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    <Chip label="Time" color="primary" />
                    {fullPreviewData.has_energy && <Chip label="Energy" color="success" />}
                    {fullPreviewData.has_pi && <Chip label="PI" color="secondary" />}
                    {fullPreviewData.mission && <Chip label={fullPreviewData.mission} variant="outlined" />}
                    {fullPreviewData.instrument && <Chip label={fullPreviewData.instrument} variant="outlined" />}
                  </Box>
                </Box>
              )}

              {/* Time Data Tab */}
              {previewTabValue === 1 && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <Typography variant="subtitle2" color="primary">Time Range</Typography>
                  <Grid container spacing={2}>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Start Time</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.time_range[0].toFixed(6)}
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">End Time</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.time_range[1].toFixed(6)}
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">MJDREF</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.mjdref || 'N/A'}
                      </Typography>
                    </Grid>
                  </Grid>

                  <Divider />

                  <Typography variant="subtitle2" color="primary">Time Statistics</Typography>
                  <Grid container spacing={2}>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Min Time Diff</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.min_time_diff?.toExponential(3) || 'N/A'}s
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Max Time Diff</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.max_time_diff?.toExponential(3) || 'N/A'}s
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Mean Time Diff</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.mean_time_diff?.toExponential(3) || 'N/A'}s
                      </Typography>
                    </Grid>
                  </Grid>

                  <Divider />

                  <Typography variant="subtitle2" color="primary">
                    Time Preview (first {fullPreviewData.times_preview.length} entries)
                  </Typography>
                  <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 200 }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>#</TableCell>
                          <TableCell>Time (s)</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {fullPreviewData.times_preview.map((time, index) => (
                          <TableRow key={index}>
                            <TableCell>{index + 1}</TableCell>
                            <TableCell sx={{ fontFamily: 'monospace' }}>{time.toFixed(6)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {/* Energy & PI Tab */}
              {previewTabValue === 2 && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {/* Energy Section */}
                  <Typography variant="subtitle2" color="primary">Energy Data</Typography>
                  {fullPreviewData.has_energy ? (
                    <>
                      <Grid container spacing={2}>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">Energy Range</Typography>
                          <Typography variant="body1" fontFamily="monospace">
                            {fullPreviewData.energy_range
                              ? `${fullPreviewData.energy_range[0].toFixed(2)} - ${fullPreviewData.energy_range[1].toFixed(2)} keV`
                              : 'N/A'}
                          </Typography>
                        </Grid>
                      </Grid>
                      {fullPreviewData.energy_preview && (
                        <>
                          <Typography variant="caption" color="text.secondary">
                            Energy Preview (first {fullPreviewData.energy_preview.length} entries)
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {fullPreviewData.energy_preview.map((energy, index) => (
                              <Chip
                                key={index}
                                label={`${energy.toFixed(2)} keV`}
                                size="small"
                                variant="outlined"
                                color="success"
                              />
                            ))}
                          </Box>
                        </>
                      )}
                    </>
                  ) : (
                    <Alert severity="info">No energy data available in this EventList</Alert>
                  )}

                  <Divider />

                  {/* PI Section */}
                  <Typography variant="subtitle2" color="primary">PI (Pulse Invariant) Data</Typography>
                  {fullPreviewData.has_pi ? (
                    <>
                      <Grid container spacing={2}>
                        <Grid item xs={6}>
                          <Typography variant="caption" color="text.secondary">PI Range</Typography>
                          <Typography variant="body1" fontFamily="monospace">
                            {fullPreviewData.pi_range
                              ? `${fullPreviewData.pi_range[0]} - ${fullPreviewData.pi_range[1]}`
                              : 'N/A'}
                          </Typography>
                        </Grid>
                      </Grid>
                      {fullPreviewData.pi_preview && (
                        <>
                          <Typography variant="caption" color="text.secondary">
                            PI Preview (first {fullPreviewData.pi_preview.length} entries)
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {fullPreviewData.pi_preview.map((pi, index) => (
                              <Chip
                                key={index}
                                label={pi.toString()}
                                size="small"
                                variant="outlined"
                                color="secondary"
                              />
                            ))}
                          </Box>
                        </>
                      )}
                    </>
                  ) : (
                    <Alert severity="info">No PI data available in this EventList</Alert>
                  )}
                </Box>
              )}

              {/* GTIs Tab */}
              {previewTabValue === 3 && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <Typography variant="subtitle2" color="primary">
                    Good Time Intervals ({fullPreviewData.gti_count} GTI{fullPreviewData.gti_count !== 1 ? 's' : ''})
                  </Typography>
                  {fullPreviewData.total_gti_time && (
                    <Typography variant="body2" color="text.secondary">
                      Total GTI Time: {fullPreviewData.total_gti_time.toFixed(2)}s
                    </Typography>
                  )}
                  {fullPreviewData.gti_list && fullPreviewData.gti_list.length > 0 ? (
                    <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 300 }}>
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            <TableCell>#</TableCell>
                            <TableCell>Start (s)</TableCell>
                            <TableCell>Stop (s)</TableCell>
                            <TableCell>Duration (s)</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {fullPreviewData.gti_list.map((gti, index) => (
                            <TableRow key={index}>
                              <TableCell>{index + 1}</TableCell>
                              <TableCell sx={{ fontFamily: 'monospace' }}>{gti[0].toFixed(4)}</TableCell>
                              <TableCell sx={{ fontFamily: 'monospace' }}>{gti[1].toFixed(4)}</TableCell>
                              <TableCell sx={{ fontFamily: 'monospace' }}>{(gti[1] - gti[0]).toFixed(4)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  ) : (
                    <Alert severity="info">No GTI data available</Alert>
                  )}
                </Box>
              )}

              {/* Metadata Tab */}
              {previewTabValue === 4 && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <Typography variant="subtitle2" color="primary">Mission Metadata</Typography>
                  <Grid container spacing={2}>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Mission</Typography>
                      <Typography variant="body1">{fullPreviewData.mission || 'N/A'}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Instrument</Typography>
                      <Typography variant="body1">{fullPreviewData.instrument || 'N/A'}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Detector ID</Typography>
                      <Typography variant="body1">{fullPreviewData.detector_id || 'N/A'}</Typography>
                    </Grid>
                  </Grid>

                  <Divider />

                  <Typography variant="subtitle2" color="primary">Time System</Typography>
                  <Grid container spacing={2}>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Time Reference</Typography>
                      <Typography variant="body1">{fullPreviewData.timeref || 'N/A'}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Time System</Typography>
                      <Typography variant="body1">{fullPreviewData.timesys || 'N/A'}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Ephemeris</Typography>
                      <Typography variant="body1">{fullPreviewData.ephem || 'N/A'}</Typography>
                    </Grid>
                  </Grid>

                  {fullPreviewData.additional_columns && fullPreviewData.additional_columns.length > 0 && (
                    <>
                      <Divider />
                      <Typography variant="subtitle2" color="primary">Additional Columns</Typography>
                      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        {fullPreviewData.additional_columns.map((col, index) => (
                          <Chip key={index} label={col} size="small" variant="outlined" />
                        ))}
                      </Box>
                    </>
                  )}
                </Box>
              )}
            </Box>
          ) : (
            <Typography color="text.secondary">No preview data available</Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseFullPreview}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* CSS for refresh animation */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </Box>
  );
};

export default DataIngestionPage;
