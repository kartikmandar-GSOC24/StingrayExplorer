import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  Tabs,
  Tab,
  Radio,
  RadioGroup,
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
import ErrorIcon from '@mui/icons-material/Error';
import SaveIcon from '@mui/icons-material/Save';
import ClearAllIcon from '@mui/icons-material/ClearAll';
import HistoryIcon from '@mui/icons-material/History';
import VisibilityIcon from '@mui/icons-material/Visibility';
import MemoryIcon from '@mui/icons-material/Memory';
import PrecisionManufacturingIcon from '@mui/icons-material/PrecisionManufacturing';
import BoltIcon from '@mui/icons-material/Bolt';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import NumbersIcon from '@mui/icons-material/Numbers';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import PublicIcon from '@mui/icons-material/Public';
import {
  dataApi,
  EventListSummary,
  EventListInfo,
  FileSizeInfo,
  EventListFullPreview,
  FileMetadata,
  SingleFileConfig,
  BatchSizeResult,
  ValidationIssue,
  type EventInputFormat,
} from '@/api/dataApi';
import { ioApi, type UtilityExportFormat } from '@/api/ioApi';
import { jobApi } from '@/api/jobApi';
import type { BatchFileConfig } from '@/types/job';
import type { GrantedFileSelection } from '@/components/utilities/GrantedFileField';
import HeasarcBrowserPanel from './HeasarcBrowserPanel';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/store/uiStore';
import { useJobStore } from '@/store/jobStore';

type AlertSeverity = 'success' | 'error' | 'warning' | 'info';

interface AlertState {
  open: boolean;
  message: string;
  severity: AlertSeverity;
}

// localStorage persistence for last loaded files
const LAST_LOADED_FILES_KEY = 'lastLoadedFiles';

export interface LastLoadedFilesData {
  files: string[];
  fileNames: Record<string, string>;
  timestamp: number;
}

const EVENT_FILE_FILTERS = [
  {
    name: 'FITS / OGIP Event Files',
    extensions: ['fits', 'fit', 'fts', 'evt', 'gz', 'fits.gz', 'fit.gz', 'fts.gz', 'evt.gz'],
  },
  { name: 'HDF5 Event Files', extensions: ['hdf5', 'h5'] },
  { name: 'ECSV Event Files', extensions: ['ecsv'] },
];

const RMF_FILE_FILTERS = [
  { name: 'Response Matrix Files', extensions: ['rmf', 'rsp'] },
  { name: 'FITS Files', extensions: ['fits', 'fit'] },
];

type PerFileUiConfig = Omit<
  Partial<SingleFileConfig>,
  'file_path' | 'file_grant' | 'name' | 'rmf_file' | 'rmf_grant'
>;

type LegacySaveFormat = Extract<UtilityExportFormat, 'hdf5' | 'ecsv'>;

export const saveLastLoadedFiles = (
  files: GrantedFileSelection[],
  names: Record<string, string>
): void => {
  const data: LastLoadedFilesData = {
    files: files.map((file) => file.path),
    fileNames: names,
    timestamp: Date.now(),
  };
  localStorage.setItem(LAST_LOADED_FILES_KEY, JSON.stringify(data));
};

export const getLastLoadedFiles = (): LastLoadedFilesData | null => {
  const saved = localStorage.getItem(LAST_LOADED_FILES_KEY);
  if (!saved) return null;
  try {
    const parsed: unknown = JSON.parse(saved);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const record = parsed as Record<string, unknown>;
    if (!Array.isArray(record.files)) return null;
    const files = record.files.filter(
      (file): file is string =>
        typeof file === 'string' && file.length > 0 && file.length <= 4096 && !/[\0\r\n]/.test(file)
    );
    const rawNames =
      record.fileNames && typeof record.fileNames === 'object' && !Array.isArray(record.fileNames)
        ? (record.fileNames as Record<string, unknown>)
        : {};
    const fileNames = Object.fromEntries(
      files.flatMap((file) => {
        const name = rawNames[file];
        return typeof name === 'string' && name.length <= 256 ? [[file, name]] : [];
      })
    );
    return {
      files,
      fileNames,
      timestamp:
        typeof record.timestamp === 'number' && Number.isFinite(record.timestamp)
          ? record.timestamp
          : 0,
    };
  } catch {
    return null;
  }
};

export const detectFormatFromExtension = (filePath: string): EventInputFormat => {
  const ext = filePath.toLowerCase().split('.').pop();
  if (ext === 'hdf5' || ext === 'h5') return 'hdf5';
  if (ext === 'ecsv') return 'ascii.ecsv';
  return 'ogip';
};

export const validateRemoteSourceUrl = (value: string): string | null => {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'https:'
      ? null
      : 'Only HTTPS URLs are supported for remote event files.';
  } catch {
    return 'Please enter a valid HTTPS URL.';
  }
};

export const mergeGrantedSelections = (
  current: GrantedFileSelection[],
  incoming: GrantedFileSelection[]
): { merged: GrantedFileSelection[]; added: GrantedFileSelection[] } => {
  const incomingByPath = new Map(incoming.map((selection) => [selection.path, selection]));
  const uniqueIncoming = [...incomingByPath.values()];
  const currentPaths = new Set(current.map((selection) => selection.path));
  const merged = current.map((selection) => incomingByPath.get(selection.path) ?? selection);
  const added = uniqueIncoming.filter((selection) => !currentPaths.has(selection.path));
  return { merged: [...merged, ...added], added };
};

const DataIngestionPage: React.FC = () => {
  // Global notification store
  const { addNotification } = useUIStore();

  // Job store for watching job completions and refreshing data
  const { jobs } = useJobStore();

  // Form state - Local File (batch mode)
  const [selectedFiles, setSelectedFiles] = useState<GrantedFileSelection[]>([]);
  const [fileNames, setFileNames] = useState<Record<string, string>>({});
  const [fileFormat, setFileFormat] = useState<EventInputFormat>('ogip');
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Batch file settings mode
  const [useSameSettings, setUseSameSettings] = useState<boolean>(true);
  const [perFileConfigs, setPerFileConfigs] = useState<Record<string, PerFileUiConfig>>({});
  const [perFileRmfSelections, setPerFileRmfSelections] = useState<
    Record<string, GrantedFileSelection | undefined>
  >({});
  const [expandedFileSettings, setExpandedFileSettings] = useState<Record<string, boolean>>({});

  // Batch size info
  const [batchSizeInfo, setBatchSizeInfo] = useState<BatchSizeResult | null>(null);
  const [batchSizeSelectionPaths, setBatchSizeSelectionPaths] = useState<string[]>([]);
  const [isCheckingBatchSize, setIsCheckingBatchSize] = useState<boolean>(false);

  // Batch loading progress - kept for potential future use but not used with job queue
  const [_batchProgress, _setBatchProgress] = useState<{
    loading: boolean;
    total: number;
    completed: number;
  } | null>(null);
  // Note: batchResult removed - job queue handles results in sidebar

  // Advanced options state
  const [showAdvancedOptions, setShowAdvancedOptions] = useState<boolean>(false);
  const [rmfSelection, setRmfSelection] = useState<GrantedFileSelection | null>(null);
  const [additionalColumns, setAdditionalColumns] = useState<string>('');
  const [fileSizeInfo, setFileSizeInfo] = useState<FileSizeInfo | null>(null);
  const [isCheckingFileSize, setIsCheckingFileSize] = useState<boolean>(false);

  // Notes/Comments for the data
  const [eventNotes, setEventNotes] = useState<string>('');


  // Advanced loading options
  const [highPrecision, setHighPrecision] = useState<boolean>(false);
  const [skipChecks, setSkipChecks] = useState<boolean>(false);

  // True lazy loading options
  const [useTrueLazyLoading, setUseTrueLazyLoading] = useState<boolean>(false);
  const [trueLazyMode, setTrueLazyMode] = useState<'time_range' | 'event_count'>('time_range');
  const [timeRangeStart, setTimeRangeStart] = useState<number>(0);
  const [timeRangeEnd, setTimeRangeEnd] = useState<number>(100);
  const [eventCountStart, setEventCountStart] = useState<number>(0);
  const [eventCount, setEventCount] = useState<number>(10000);
  const [fileMetadata, setFileMetadata] = useState<FileMetadata | null>(null);
  const [isLoadingMetadata, setIsLoadingMetadata] = useState<boolean>(false);

  // Tab state for data input method
  const [dataInputTab, setDataInputTab] = useState<number>(0);

  // Form state - URL Loading
  const [urlInput, setUrlInput] = useState<string>('');
  const [urlEventListName, setUrlEventListName] = useState<string>('');
  const [urlFormat, setUrlFormat] = useState<EventInputFormat>('ogip');
  const [isLoadingUrl, setIsLoadingUrl] = useState<boolean>(false);
  // Note: urlDownloadProgress removed - job queue handles progress in sidebar

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

  // Save format dialog state
  const [saveFormatDialogOpen, setSaveFormatDialogOpen] = useState<boolean>(false);
  const [saveEventListName, setSaveEventListName] = useState<string>('');
  const [selectedSaveFormat, setSelectedSaveFormat] = useState<LegacySaveFormat>('hdf5');
  const [availableSaveFormats, setAvailableSaveFormats] = useState<LegacySaveFormat[]>([]);
  const [hdf5UnavailableReason, setHdf5UnavailableReason] = useState<string | null>(null);
  const [saveFormatsLoadingName, setSaveFormatsLoadingName] = useState<string | null>(null);
  const saveFormatsRequestIdRef = useRef(0);

  // Last loaded files state (for restore functionality)
  const [hasLastLoadedFiles, setHasLastLoadedFiles] = useState<boolean>(false);
  const [lastLoadedHints, setLastLoadedHints] = useState<string[]>([]);

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

  // Refresh event list when jobs complete
  useEffect(() => {
    // Count completed load jobs
    const completedLoadJobs = Object.values(jobs).filter(
      (job) =>
        job.status === 'completed' &&
        (job.type === 'load_event_list' || job.type === 'load_batch' || job.type === 'load_from_url')
    );

    if (completedLoadJobs.length > 0) {
      // Refresh the event list to show newly loaded data
      fetchEventLists();
    }
  }, [jobs, fetchEventLists]);

  // Check for last loaded files on mount
  useEffect(() => {
    const lastLoaded = getLastLoadedFiles();
    setHasLastLoadedFiles(lastLoaded !== null && lastLoaded.files.length > 0);
    setLastLoadedHints(lastLoaded?.files ?? []);
  }, []);

  // Show alert helper - sends all alerts to the global notification center
  const showAlert = (message: string, severity: AlertSeverity, title?: string): void => {
    // Map severity to notification type
    const typeMap: Record<AlertSeverity, 'success' | 'error' | 'warning' | 'info'> = {
      success: 'success',
      error: 'error',
      warning: 'warning',
      info: 'info',
    };
    const defaultTitles: Record<AlertSeverity, string> = {
      success: 'Success',
      error: 'Error',
      warning: 'Warning',
      info: 'Info',
    };

    addNotification({
      type: typeMap[severity],
      title: title || defaultTitles[severity],
      message,
    });

    // Clear any existing local alert
    setAlert({ open: false, message: '', severity: 'info' });
  };

  // Check file size when file is selected (single file)
  const checkFileSize = async (file: GrantedFileSelection): Promise<void> => {
    setIsCheckingFileSize(true);
    try {
      await apiClient.getPort();
      const response = await dataApi.checkFileSize({
        file_path: file.path,
        file_grant: file.grant,
      });
      if (response.success && response.data) {
        setFileSizeInfo(response.data);
        // Auto-enable lazy loading if recommended for large files
        if (response.data.recommend_lazy && !useTrueLazyLoading) {
          setUseTrueLazyLoading(true);
        }
      }
    } catch (error) {
      console.error('Failed to check file size:', error);
      setFileSizeInfo(null);
    } finally {
      setIsCheckingFileSize(false);
    }
  };

  // Check batch file sizes when multiple files are selected
  const checkBatchFileSize = async (files: GrantedFileSelection[]): Promise<void> => {
    if (files.length === 0) return;

    setIsCheckingBatchSize(true);
    try {
      await apiClient.getPort();
      const response = await dataApi.checkBatchFileSize(
        files.map((file) => ({ file_path: file.path, file_grant: file.grant }))
      );
      if (response.success && response.data) {
        setBatchSizeInfo(response.data);
        setBatchSizeSelectionPaths(files.map((file) => file.path));
        // Auto-enable lazy loading if recommended
        if (response.data.recommend_partial_loading && !useTrueLazyLoading) {
          setUseTrueLazyLoading(true);
        }
      } else {
        setBatchSizeInfo(null);
        setBatchSizeSelectionPaths([]);
      }
    } catch (error) {
      console.error('Failed to check batch file sizes:', error);
      setBatchSizeInfo(null);
      setBatchSizeSelectionPaths([]);
    } finally {
      setIsCheckingBatchSize(false);
    }
  };

  // Fetch file metadata for true lazy loading (uses first selected file as reference)
  const fetchFileMetadata = async (): Promise<void> => {
    if (selectedFiles.length === 0) {
      showAlert('Please select a file first', 'warning');
      return;
    }

    setIsLoadingMetadata(true);
    try {
      await apiClient.getPort();
      // Use first file for metadata preview
      const response = await dataApi.getFileMetadata({
        file_path: selectedFiles[0].path,
        file_grant: selectedFiles[0].grant,
        fmt: fileFormat,
      });
      if (response.success && response.data) {
        setFileMetadata(response.data);
        // Auto-populate time range with full file duration
        if (response.data.time_range[0] !== null && response.data.time_range[1] !== null) {
          setTimeRangeStart(0);
          setTimeRangeEnd(Math.min(response.data.duration, 100));
        }
        // Auto-populate event count with recommendation
        if (response.data.recommended_loading.suggested_chunk_size) {
          setEventCount(response.data.recommended_loading.suggested_chunk_size);
        }
        const message = selectedFiles.length > 1
          ? `First file has ${response.data.total_events.toLocaleString()} events over ${response.data.duration.toFixed(1)}s (settings will apply to all files)`
          : `File has ${response.data.total_events.toLocaleString()} events over ${response.data.duration.toFixed(1)}s`;
        showAlert(message, 'success', 'File Metadata');
      } else {
        showAlert(response.message || 'Failed to fetch file metadata', 'error', 'Metadata Error');
      }
    } catch (error) {
      console.error('Failed to fetch file metadata:', error);
      showAlert('Failed to fetch file metadata', 'error', 'Metadata Error');
    } finally {
      setIsLoadingMetadata(false);
    }
  };

  const addGrantedFiles = (
    files: GrantedFileSelection[],
    preferredNames: Record<string, string> = {}
  ): void => {
    const { merged: mergedFiles, added: newFiles } = mergeGrantedSelections(
      selectedFiles,
      files
    );
    setSelectedFiles(mergedFiles);

    if (newFiles.length > 0 && selectedFiles.length === 0) {
      setFileFormat(detectFormatFromExtension(newFiles[0].path));
    }

    const mergedNames = { ...fileNames };
    newFiles.forEach((file) => {
      const filename = file.path.split(/[\\/]/).pop() || 'event_list';
      const fallbackName = filename.split('.')[0] || 'event_list';
      const preferredName = preferredNames[file.path]?.trim();
      const baseName = preferredName || fallbackName;
      let uniqueName = baseName;
      let counter = 1;
      while (Object.values(mergedNames).includes(uniqueName)) {
        uniqueName = `${baseName}_${counter}`;
        counter++;
      }
      mergedNames[file.path] = uniqueName;
    });
    setFileNames(mergedNames);

    const mergedConfigs = { ...perFileConfigs };
    newFiles.forEach((file) => {
      mergedConfigs[file.path] = {
        fmt: detectFormatFromExtension(file.path),
        high_precision: false,
        skip_checks: false,
        use_partial_loading: false,
        partial_mode: 'time_range',
        time_range_start: 0,
        time_range_end: 100,
        event_start_index: 0,
        event_count: 10000,
        notes: '',
      };
    });
    setPerFileConfigs(mergedConfigs);

    if (mergedFiles.length > 1) {
      void checkBatchFileSize(mergedFiles);
      setFileSizeInfo(null);
    } else if (mergedFiles.length === 1) {
      void checkFileSize(mergedFiles[0]);
      setBatchSizeInfo(null);
      setBatchSizeSelectionPaths([]);
    }
  };

  // Handle file selection via Electron dialog (supports multiple files).
  const handleBrowseFiles = async (): Promise<void> => {
    if (!window.electronAPI?.openGrantedFile) {
      showAlert('Granted file dialog not available (Electron API not found)', 'error');
      return;
    }

    try {
      const files = await window.electronAPI.openGrantedFile({
        title: 'Select Event List Files',
        filters: EVENT_FILE_FILTERS,
        multiple: true,
      });
      if (files?.length) addGrantedFiles(files);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      showAlert(`Could not open the granted file dialog: ${detail}`, 'error');
    }
  };

  // Remove a file from the selection
  const handleRemoveFile = (filePath: string): void => {
    const newFiles = selectedFiles.filter((file) => file.path !== filePath);
    setSelectedFiles(newFiles);

    // Update file names
    const newNames = { ...fileNames };
    delete newNames[filePath];
    setFileNames(newNames);

    // Update per-file configs
    const newConfigs = { ...perFileConfigs };
    delete newConfigs[filePath];
    setPerFileConfigs(newConfigs);

    setPerFileRmfSelections((previous) => {
      const updated = { ...previous };
      delete updated[filePath];
      return updated;
    });

    // Re-check sizes
    if (newFiles.length > 1) {
      checkBatchFileSize(newFiles);
      setFileSizeInfo(null);
    } else if (newFiles.length === 1) {
      checkFileSize(newFiles[0]);
      setBatchSizeInfo(null);
      setBatchSizeSelectionPaths([]);
    } else {
      setFileSizeInfo(null);
      setBatchSizeInfo(null);
      setBatchSizeSelectionPaths([]);
    }
  };

  // Clear all selected files
  const handleClearSelection = (): void => {
    setSelectedFiles([]);
    setFileNames({});
    setPerFileConfigs({});
    setPerFileRmfSelections({});
    setBatchSizeInfo(null);
    setBatchSizeSelectionPaths([]);
    setFileSizeInfo(null);
    // Batch result cleared (job queue handles results)
    setExpandedFileSettings({});
  };

  // Historical paths are display hints only. A fresh native selection creates new grants.
  const handleRestoreLastFiles = async (): Promise<void> => {
    const lastLoaded = getLastLoadedFiles();
    if (!lastLoaded || lastLoaded.files.length === 0) {
      showAlert('No previously loaded files found', 'info');
      return;
    }

    if (!window.electronAPI?.openGrantedFile) {
      showAlert('Granted file dialog not available (Electron API not found)', 'error');
      return;
    }

    try {
      const files = await window.electronAPI.openGrantedFile({
        title: 'Reselect previously loaded Event List files',
        filters: EVENT_FILE_FILTERS,
        multiple: true,
      });
      if (!files?.length) return;
      addGrantedFiles(files, lastLoaded.fileNames);
      showAlert(
        `Granted ${files.length} freshly selected file${files.length === 1 ? '' : 's'}.`,
        'success'
      );
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      showAlert(`Could not reselect previous files: ${detail}`, 'error');
    }
  };

  // Update file name
  const handleFileNameChange = (filePath: string, newName: string): void => {
    setFileNames((prev) => ({
      ...prev,
      [filePath]: newName,
    }));
  };

  // Update per-file config
  const handlePerFileConfigChange = (
    filePath: string,
    updates: PerFileUiConfig
  ): void => {
    setPerFileConfigs((prev) => ({
      ...prev,
      [filePath]: {
        ...prev[filePath],
        ...updates,
      },
    }));
  };

  // Toggle per-file settings expansion
  const toggleFileSettings = (filePath: string): void => {
    setExpandedFileSettings((prev) => ({
      ...prev,
      [filePath]: !prev[filePath],
    }));
  };

  // Handle RMF file selection
  const handleBrowseRmfFile = async (): Promise<void> => {
    if (!window.electronAPI?.openGrantedFile) {
      showAlert('Granted file dialog not available (Electron API not found)', 'error');
      return;
    }

    try {
      const files = await window.electronAPI.openGrantedFile({
        title: 'Select RMF (Response Matrix) File',
        filters: RMF_FILE_FILTERS,
        multiple: false,
      });
      if (files?.length) setRmfSelection(files[0]);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      showAlert(`Could not open the granted RMF dialog: ${detail}`, 'error');
    }
  };

  // Handle per-file RMF file browsing
  const handleBrowsePerFileRmf = async (filePath: string): Promise<void> => {
    if (!window.electronAPI?.openGrantedFile) {
      showAlert('Granted file dialog not available (Electron API not found)', 'error');
      return;
    }

    try {
      const files = await window.electronAPI.openGrantedFile({
        title: 'Select RMF (Response Matrix) File',
        filters: RMF_FILE_FILTERS,
        multiple: false,
      });
      if (files?.length) {
        setPerFileRmfSelections((previous) => ({
          ...previous,
          [filePath]: files[0],
        }));
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      showAlert(`Could not open the granted RMF dialog: ${detail}`, 'error');
    }
  };

  // Handle loading files (single or batch) - submits background jobs
  const handleLoadFile = async (): Promise<void> => {
    if (selectedFiles.length === 0) {
      showAlert('Please select a file first', 'warning');
      return;
    }

    // Validate names
    const names = Object.values(fileNames);
    const emptyNames = selectedFiles.filter((file) => !fileNames[file.path]?.trim());
    if (emptyNames.length > 0) {
      showAlert('Please provide names for all selected files', 'warning');
      return;
    }

    // Check for duplicate names
    const uniqueNames = new Set(names);
    if (uniqueNames.size !== names.length) {
      showAlert('File names must be unique', 'warning');
      return;
    }

    setIsLoading(true);
    // Batch result cleared (job queue handles results)
    setAlert({ open: false, message: '', severity: 'info' });

    try {
      await apiClient.getPort();

      // Parse additional columns if provided (for shared settings)
      const additionalColumnsArray = additionalColumns.trim()
        ? additionalColumns.split(',').map((col) => col.trim()).filter((col) => col)
        : undefined;

      // Single file: submit a single load job
      if (selectedFiles.length === 1) {
        const source = selectedFiles[0];
        const jobParams = {
          file_path: source.path,
          file_grant: source.grant,
          name: fileNames[source.path].trim(),
          fmt: fileFormat,
          additional_columns: additionalColumnsArray,
          high_precision: highPrecision,
          skip_checks: skipChecks,
          notes: eventNotes.trim() || undefined,
          use_partial_loading: useTrueLazyLoading,
          partial_mode: trueLazyMode,
          time_range_start: useTrueLazyLoading && trueLazyMode === 'time_range' ? timeRangeStart : undefined,
          time_range_end: useTrueLazyLoading && trueLazyMode === 'time_range' ? timeRangeEnd : undefined,
          event_start_index: useTrueLazyLoading && trueLazyMode === 'event_count' ? eventCountStart : undefined,
          event_count: useTrueLazyLoading && trueLazyMode === 'event_count' ? eventCount : undefined,
        };
        const response = await jobApi.submitLoadJob(
          rmfSelection
            ? {
                ...jobParams,
                rmf_file: rmfSelection.path,
                rmf_grant: rmfSelection.grant,
              }
            : jobParams
        );

        if (response.success && response.data) {
          showAlert(
            `Job submitted: ${response.data.display_name}. Check sidebar for progress.`,
            'info',
            'Job Submitted'
          );
          // Save files to localStorage before clearing form
          saveLastLoadedFiles(selectedFiles, fileNames);
          setHasLastLoadedFiles(true);
          setLastLoadedHints(selectedFiles.map((file) => file.path));
          resetForm();
        } else {
          showAlert(response.message || 'Failed to submit load job', 'error', 'Job Submit Failed');
        }
      } else {
        // Multiple files: submit a batch load job
        const fileConfigs: BatchFileConfig[] = selectedFiles.map((file) => {
          const perFile = perFileConfigs[file.path] || {};
          const perFileRmf = useSameSettings
            ? undefined
            : perFileRmfSelections[file.path];
          const fileConfig = {
            file_path: file.path,
            file_grant: file.grant,
            name: fileNames[file.path].trim(),
            fmt: useSameSettings ? fileFormat : (perFile.fmt || 'ogip'),
            additional_columns: useSameSettings ? additionalColumnsArray : perFile.additional_columns,
            high_precision: useSameSettings ? highPrecision : (perFile.high_precision || false),
            skip_checks: useSameSettings ? skipChecks : (perFile.skip_checks || false),
            use_partial_loading: useSameSettings ? useTrueLazyLoading : (perFile.use_partial_loading || false),
            partial_mode: useSameSettings ? trueLazyMode : (perFile.partial_mode || 'time_range'),
            time_range_start: useSameSettings ? timeRangeStart : perFile.time_range_start,
            time_range_end: useSameSettings ? timeRangeEnd : perFile.time_range_end,
            event_start_index: useSameSettings ? eventCountStart : perFile.event_start_index,
            event_count: useSameSettings ? eventCount : perFile.event_count,
            notes: useSameSettings ? (eventNotes.trim() || undefined) : (perFile.notes?.trim() || undefined),
          };
          return perFileRmf
            ? {
                ...fileConfig,
                rmf_file: perFileRmf.path,
                rmf_grant: perFileRmf.grant,
              }
            : fileConfig;
        });

        const batchParams = {
          files: fileConfigs,
          use_same_settings: useSameSettings,
          shared_fmt: fileFormat,
          shared_additional_columns: additionalColumnsArray,
          shared_high_precision: highPrecision,
          shared_skip_checks: skipChecks,
          shared_use_partial_loading: useTrueLazyLoading,
          shared_partial_mode: trueLazyMode,
          shared_time_range_start: useTrueLazyLoading ? timeRangeStart : undefined,
          shared_time_range_end: useTrueLazyLoading ? timeRangeEnd : undefined,
          shared_event_start_index: useTrueLazyLoading ? eventCountStart : undefined,
          shared_event_count: useTrueLazyLoading ? eventCount : undefined,
        };
        const response = await jobApi.submitBatchJob(
          useSameSettings && rmfSelection
            ? {
                ...batchParams,
                shared_rmf_file: rmfSelection.path,
                shared_rmf_grant: rmfSelection.grant,
              }
            : batchParams
        );

        if (response.success && response.data) {
          showAlert(
            `Batch job submitted: ${selectedFiles.length} files. Check sidebar for progress.`,
            'info',
            'Batch Job Submitted'
          );
          // Save files to localStorage and clear form
          saveLastLoadedFiles(selectedFiles, fileNames);
          setHasLastLoadedFiles(true);
          setLastLoadedHints(selectedFiles.map((file) => file.path));
          resetForm();
        } else {
          showAlert(response.message || 'Failed to submit batch job', 'error', 'Batch Job Submit Failed');
        }
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      showAlert(`Error: ${errorMessage}`, 'error', 'Job Submit Error');
    } finally {
      setIsLoading(false);
    }
  };

  // Reset form after successful load
  const resetForm = (): void => {
    setSelectedFiles([]);
    setFileNames({});
    setPerFileConfigs({});
    setPerFileRmfSelections({});
    setExpandedFileSettings({});
    setRmfSelection(null);
    setAdditionalColumns('');
    setEventNotes('');
    setFileSizeInfo(null);
    setBatchSizeInfo(null);
    setBatchSizeSelectionPaths([]);
    setFileMetadata(null);
    setUseTrueLazyLoading(false);
    setHighPrecision(false);
    setSkipChecks(false);
    setTimeRangeStart(0);
    setTimeRangeEnd(100);
    setEventCountStart(0);
    setEventCount(10000);
    // Batch result cleared (job queue handles results)
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

  // Discover verified export capabilities before opening the format dialog.
  const handleSaveEventList = async (name: string): Promise<void> => {
    const requestId = ++saveFormatsRequestIdRef.current;
    setSaveFormatsLoadingName(name);
    try {
      const response = await ioApi.listExportableObjects();
      if (requestId !== saveFormatsRequestIdRef.current) return;

      const eventList = response.data?.objects.find(
        (object) => object.object_type === 'event_list' && object.name === name
      );
      const formats = (eventList?.formats ?? []).filter(
        (format): format is LegacySaveFormat =>
          (format === 'hdf5' || format === 'ecsv') &&
          Boolean(response.data?.format_allowlist.includes(format)) &&
          Boolean(response.data?.capability_matrix?.event_list?.[format]?.supported)
      );
      if (!response.success || !eventList?.exportable || formats.length === 0) {
        showAlert(
          eventList?.reason || response.message || 'No verified export format is available.',
          'error',
          'Export Unavailable'
        );
        return;
      }

      setSaveEventListName(name);
      setAvailableSaveFormats(formats);
      setHdf5UnavailableReason(
        formats.includes('hdf5')
          ? null
          : response.data?.capability_matrix?.event_list?.hdf5?.notes ||
              response.data?.excluded_formats.hdf5 ||
              'HDF5 is unavailable in this runtime.'
      );
      setSelectedSaveFormat(formats.includes('hdf5') ? 'hdf5' : formats[0]);
      setSaveFormatDialogOpen(true);
    } catch (error) {
      if (requestId !== saveFormatsRequestIdRef.current) return;
      const detail = error instanceof Error ? error.message : String(error);
      showAlert(`Could not determine export capabilities: ${detail}`, 'error');
    } finally {
      if (requestId === saveFormatsRequestIdRef.current) {
        setSaveFormatsLoadingName(null);
      }
    }
  };

  // Export through a native write grant after a verified format is selected.
  const handleConfirmSave = async (): Promise<void> => {
    setSaveFormatDialogOpen(false);

    if (!window.electronAPI?.saveGrantedFile) {
      showAlert('Granted save dialog not available (Electron API not found)', 'error');
      return;
    }

    const filterMap: Record<LegacySaveFormat, { name: string; extensions: string[] }> = {
      hdf5: { name: 'HDF5 Files', extensions: ['hdf5'] },
      ecsv: { name: 'ECSV Files', extensions: ['ecsv'] },
    };
    const filter = filterMap[selectedSaveFormat];

    try {
      const destination = await window.electronAPI.saveGrantedFile({
        title: `Export Event List: ${saveEventListName}`,
        defaultPath: `${saveEventListName}.${selectedSaveFormat}`,
        filters: [filter],
      });
      if (!destination) return;

      const response = await ioApi.exportObject({
        object_type: 'event_list',
        object_name: saveEventListName,
        format: selectedSaveFormat,
        destination_path: destination.path,
        destination_grant: destination.grant,
      });

      if (response.success) {
        showAlert(
          `Event List '${saveEventListName}' exported to ${destination.path}`,
          'success',
          'Data Exported'
        );
      } else {
        showAlert(response.message || 'Failed to export Event List', 'error', 'Export Failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      showAlert(`Error: ${errorMessage}`, 'error', 'Export Error');
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

  // Handle loading from URL - submits a background job
  const handleLoadFromUrl = async (): Promise<void> => {
    if (!urlInput.trim()) {
      showAlert('Please enter a URL', 'warning');
      return;
    }

    if (!urlEventListName.trim()) {
      showAlert('Please provide a name for the Event List', 'warning');
      return;
    }

    const urlValidationError = validateRemoteSourceUrl(urlInput.trim());
    if (urlValidationError) {
      showAlert(urlValidationError, 'warning');
      return;
    }

    setIsLoadingUrl(true);
    setAlert({ open: false, message: '', severity: 'info' });

    try {
      await apiClient.getPort();

      // Submit URL download job
      const response = await jobApi.submitUrlJob({
        url: urlInput.trim(),
        name: urlEventListName.trim(),
        fmt: urlFormat,
        high_precision: highPrecision,
        skip_checks: skipChecks,
      });

      if (response.success && response.data) {
        showAlert(
          `URL download job submitted: ${response.data.display_name}. Check sidebar for progress.`,
          'info',
          'Job Submitted'
        );
        // Reset form
        setUrlInput('');
        setUrlEventListName('');
      } else {
        showAlert(response.message || 'Failed to submit URL job', 'error', 'Job Submit Failed');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
      showAlert(`Error: ${errorMessage}`, 'error', 'URL Job Submit Error');
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

      {/* Data Input Tabs */}
      <Card variant="outlined" sx={{ mb: 4 }}>
        <Tabs
          value={dataInputTab}
          onChange={(_, newValue) => setDataInputTab(newValue)}
          variant="fullWidth"
          sx={{ borderBottom: 1, borderColor: 'divider' }}
        >
          <Tab
            icon={<UploadFileIcon />}
            iconPosition="start"
            label="Local File"
            sx={{ textTransform: 'none' }}
          />
          <Tab
            icon={<CloudUploadIcon />}
            iconPosition="start"
            label="From URL"
            sx={{ textTransform: 'none' }}
          />
          <Tab
            icon={<PublicIcon />}
            iconPosition="start"
            label="Browse HEASARC"
            sx={{ textTransform: 'none' }}
          />
        </Tabs>

        <CardContent>
          {/* Tab 0: Load from Local File */}
          {dataInputTab === 0 && (
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <UploadFileIcon sx={{ fontSize: 32, color: 'primary.main', mr: 1 }} />
                <Typography variant="h6">Load Local File</Typography>
              </Box>

              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                Load FITS/OGIP, HDF5, or ECSV event lists through the native file picker.
              </Typography>

              {/* File Selection */}
              <Box sx={{ mb: 2 }}>
                <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                  <Button
                    variant="outlined"
                    startIcon={<FolderOpenIcon />}
                    onClick={handleBrowseFiles}
                    sx={{ flex: 1 }}
                  >
                    Browse Files
                  </Button>
                  {hasLastLoadedFiles && (
                    <Tooltip title="Historical paths are hints only; choose the files again to renew access">
                      <Button
                        variant="outlined"
                        color="secondary"
                        aria-label="Reselect Last Files"
                        startIcon={<HistoryIcon />}
                        onClick={handleRestoreLastFiles}
                      >
                        Reselect Last Files
                      </Button>
                    </Tooltip>
                  )}
                </Box>
                {hasLastLoadedFiles && lastLoadedHints.length > 0 && (
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ display: 'block', overflowWrap: 'anywhere' }}
                  >
                    Previous path hints (fresh native selection required): {lastLoadedHints.join(', ')}
                  </Typography>
                )}

                {/* Selected Files List */}
                {selectedFiles.length > 0 && (
                  <Box sx={{ mt: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                      <Typography variant="subtitle2" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        Selected Files ({selectedFiles.length})
                        {selectedFiles.length > 1 && (
                          <Chip label="Batch Mode" size="small" color="primary" variant="outlined" />
                        )}
                      </Typography>
                      <Button
                        variant="text"
                        size="small"
                        startIcon={<ClearAllIcon />}
                        onClick={handleClearSelection}
                        color="error"
                      >
                        Clear All
                      </Button>
                    </Box>

                    {/* Batch Size Info (for multiple files) */}
                    {(isCheckingBatchSize || isCheckingFileSize) && (
                      <Box sx={{ mb: 2 }}>
                        <LinearProgress />
                        <Typography variant="caption" color="text.secondary">
                          Checking file sizes...
                        </Typography>
                      </Box>
                    )}

                    {/* Batch Size Summary */}
                    {batchSizeInfo && !isCheckingBatchSize && (
                      <Box
                        sx={{
                          mb: 2,
                          p: 1.5,
                          borderRadius: 1,
                          bgcolor: batchSizeInfo.total.risk_level === 'safe' ? 'success.50' :
                                   batchSizeInfo.total.risk_level === 'caution' ? 'warning.50' :
                                   'error.50',
                          border: '1px solid',
                          borderColor: batchSizeInfo.total.risk_level === 'safe' ? 'success.main' :
                                       batchSizeInfo.total.risk_level === 'caution' ? 'warning.main' :
                                       'error.main',
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            {batchSizeInfo.total.risk_level === 'safe' ? (
                              <CheckCircleIcon fontSize="small" color="success" />
                            ) : (
                              <WarningAmberIcon fontSize="small" color={batchSizeInfo.total.risk_level === 'caution' ? 'warning' : 'error'} />
                            )}
                            <Typography variant="body2" fontWeight="medium">
                              Total: {batchSizeInfo.total.size_mb.toFixed(1)} MB → ~{batchSizeInfo.total.estimated_ram_mb.toFixed(0)} MB RAM
                            </Typography>
                          </Box>
                          <Chip
                            label={`${batchSizeInfo.total.ram_percent.toFixed(0)}% RAM`}
                            size="small"
                            color={batchSizeInfo.total.risk_level === 'safe' ? 'success' :
                                   batchSizeInfo.total.risk_level === 'caution' ? 'warning' : 'error'}
                          />
                        </Box>
                        <Typography variant="caption" color="text.secondary">
                          Available RAM: {batchSizeInfo.available_ram_mb.toFixed(0)} MB
                        </Typography>
                        {batchSizeInfo.recommend_partial_loading && (
                          <Typography variant="caption" color="warning.main" sx={{ display: 'block', mt: 0.5 }}>
                            Consider using partial loading to reduce memory usage.
                          </Typography>
                        )}
                      </Box>
                    )}

                    {/* Single file size info */}
                    {fileSizeInfo && !isCheckingFileSize && selectedFiles.length === 1 && (
                      <Box
                        sx={{
                          mb: 2,
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
                        {fileSizeInfo.ram_usage_percent !== undefined && (
                          <Typography variant="caption" color="text.secondary">
                            Would use ~{fileSizeInfo.ram_usage_percent.toFixed(0)}% of available RAM
                          </Typography>
                        )}
                      </Box>
                    )}

                    {/* Settings Mode Toggle (only for batch) */}
                    {selectedFiles.length > 1 && (
                      <Box sx={{ mb: 2, p: 1.5, bgcolor: 'action.hover', borderRadius: 1 }}>
                        <FormControlLabel
                          control={
                            <Checkbox
                              checked={useSameSettings}
                              onChange={(e) => setUseSameSettings(e.target.checked)}
                              size="small"
                            />
                          }
                          label={
                            <Typography variant="body2">
                              Apply same settings to all files
                            </Typography>
                          }
                        />
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 3.5 }}>
                          {useSameSettings
                            ? 'All files will use the format and options below'
                            : 'Each file can have different settings (expand to configure)'}
                        </Typography>
                      </Box>
                    )}

                    {/* File List */}
                    <Paper variant="outlined" sx={{ maxHeight: 300, overflow: 'auto' }}>
                      <List dense disablePadding>
                        {selectedFiles.map((selection, index) => {
                          const filePath = selection.path;
                          const fileName = filePath.split(/[\\/]/).pop() || filePath;
                          const sizeInfoIndex = batchSizeSelectionPaths.indexOf(filePath);
                          const sizeInfo = sizeInfoIndex >= 0
                            ? batchSizeInfo?.files[sizeInfoIndex]
                            : undefined;
                          const isExpanded = expandedFileSettings[filePath];

                          return (
                            <React.Fragment key={filePath}>
                              {index > 0 && <Divider />}
                              <ListItem
                                sx={{ py: 1, flexDirection: 'column', alignItems: 'stretch' }}
                              >
                                <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', gap: 1 }}>
                                  <TextField
                                    size="small"
                                    value={fileNames[filePath] || ''}
                                    onChange={(e) => handleFileNameChange(filePath, e.target.value)}
                                    placeholder="Name"
                                    sx={{ width: 140, flexShrink: 0 }}
                                    inputProps={{ style: { fontSize: '0.875rem' } }}
                                  />
                                  <Box sx={{ flex: 1, minWidth: 0 }}>
                                    <Typography variant="body2" noWrap title={fileName}>
                                      {fileName}
                                    </Typography>
                                    {sizeInfo && (
                                      <Typography variant="caption" color="text.secondary">
                                        {sizeInfo.size_mb.toFixed(1)} MB
                                        {sizeInfo.ram_percent > 30 && (
                                          <Chip
                                            label={`${sizeInfo.ram_percent.toFixed(0)}%`}
                                            size="small"
                                            color={sizeInfo.risk_level === 'safe' ? 'success' :
                                                   sizeInfo.risk_level === 'caution' ? 'warning' : 'error'}
                                            sx={{ ml: 1, height: 18 }}
                                          />
                                        )}
                                      </Typography>
                                    )}
                                  </Box>
                                  {/* Per-file settings button (only when not using same settings) */}
                                  {selectedFiles.length > 1 && !useSameSettings && (
                                    <IconButton
                                      size="small"
                                      onClick={() => toggleFileSettings(filePath)}
                                      color={isExpanded ? 'primary' : 'default'}
                                    >
                                      <SettingsIcon fontSize="small" />
                                    </IconButton>
                                  )}
                                  <IconButton
                                    size="small"
                                    onClick={() => handleRemoveFile(filePath)}
                                    color="error"
                                  >
                                    <CloseIcon fontSize="small" />
                                  </IconButton>
                                </Box>

                                {/* Per-file settings (collapsed) */}
                                {!useSameSettings && isExpanded && (
                                  <Box sx={{ mt: 1, pl: 2, pr: 1, pb: 1, bgcolor: 'action.hover', borderRadius: 1 }}>
                                    <Grid container spacing={1} sx={{ mt: 0.5 }}>
                                      {/* Format */}
                                      <Grid item xs={12}>
                                        <FormControl fullWidth size="small">
                                          <InputLabel>Format</InputLabel>
                                          <Select
                                            value={perFileConfigs[filePath]?.fmt || 'ogip'}
                                            label="Format"
                                            onChange={(e) => handlePerFileConfigChange(filePath, {
                                              fmt: e.target.value as EventInputFormat,
                                            })}
                                          >
                                            <MenuItem value="ogip">OGIP</MenuItem>
                                            <MenuItem value="hdf5">HDF5</MenuItem>
                                            <MenuItem value="fits">FITS</MenuItem>
                                            <MenuItem value="ascii.ecsv">ASCII ECSV</MenuItem>
                                          </Select>
                                        </FormControl>
                                      </Grid>

                                      {/* RMF File */}
                                      <Grid item xs={12}>
                                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                                          RMF File (optional)
                                        </Typography>
                                        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
                                          <TextField
                                            size="small"
                                            value={perFileRmfSelections[filePath]?.path || ''}
                                            fullWidth
                                            placeholder="Choose an RMF file"
                                            InputProps={{ readOnly: true }}
                                            inputProps={{ style: { fontSize: '0.75rem' } }}
                                          />
                                          <Button
                                            size="small"
                                            variant="outlined"
                                            onClick={() => handleBrowsePerFileRmf(filePath)}
                                            sx={{ minWidth: 'auto', px: 1, fontSize: '0.7rem' }}
                                          >
                                            Browse
                                          </Button>
                                          {perFileRmfSelections[filePath] && (
                                            <IconButton
                                              size="small"
                                              onClick={() => setPerFileRmfSelections((previous) => ({
                                                ...previous,
                                                [filePath]: undefined,
                                              }))}
                                            >
                                              <CloseIcon sx={{ fontSize: '0.875rem' }} />
                                            </IconButton>
                                          )}
                                        </Box>
                                      </Grid>

                                      {/* Additional Columns */}
                                      <Grid item xs={12}>
                                        <TextField
                                          size="small"
                                          label="Additional Columns"
                                          value={perFileConfigs[filePath]?.additional_columns?.join(', ') || ''}
                                          onChange={(e) => handlePerFileConfigChange(filePath, {
                                            additional_columns: e.target.value
                                              .split(',')
                                              .map((s) => s.trim())
                                              .filter(Boolean)
                                          })}
                                          fullWidth
                                          placeholder="e.g., PI, ENERGY, DET_ID"
                                          helperText="Comma-separated"
                                          inputProps={{ style: { fontSize: '0.75rem' } }}
                                        />
                                      </Grid>

                                      {/* Notes */}
                                      <Grid item xs={12}>
                                        <TextField
                                          size="small"
                                          label="Notes"
                                          value={perFileConfigs[filePath]?.notes || ''}
                                          onChange={(e) => handlePerFileConfigChange(filePath, {
                                            notes: e.target.value
                                          })}
                                          fullWidth
                                          multiline
                                          rows={2}
                                          placeholder="Add notes about this file..."
                                          inputProps={{ style: { fontSize: '0.75rem' } }}
                                        />
                                      </Grid>

                                      {/* High Precision & Skip Checks */}
                                      <Grid item xs={6}>
                                        <Tooltip title="Uses float128 for time arrays (nanosecond precision)" arrow placement="top">
                                          <FormControlLabel
                                            control={
                                              <Checkbox
                                                checked={perFileConfigs[filePath]?.high_precision || false}
                                                onChange={(e) => handlePerFileConfigChange(filePath, { high_precision: e.target.checked })}
                                                size="small"
                                              />
                                            }
                                            label={
                                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                <PrecisionManufacturingIcon sx={{ fontSize: '0.875rem' }} color="info" />
                                                <Typography variant="caption">High precision</Typography>
                                              </Box>
                                            }
                                          />
                                        </Tooltip>
                                      </Grid>
                                      <Grid item xs={6}>
                                        <Tooltip title="Skip time ordering and GTI validation" arrow placement="top">
                                          <FormControlLabel
                                            control={
                                              <Checkbox
                                                checked={perFileConfigs[filePath]?.skip_checks || false}
                                                onChange={(e) => handlePerFileConfigChange(filePath, { skip_checks: e.target.checked })}
                                                size="small"
                                              />
                                            }
                                            label={
                                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                <BoltIcon sx={{ fontSize: '0.875rem' }} color="warning" />
                                                <Typography variant="caption">Skip checks</Typography>
                                              </Box>
                                            }
                                          />
                                        </Tooltip>
                                      </Grid>

                                      {/* Partial Loading */}
                                      <Grid item xs={12}>
                                        <Tooltip title="Load only a portion of the file (FITS only)" arrow placement="top">
                                          <FormControlLabel
                                            control={
                                              <Checkbox
                                                checked={perFileConfigs[filePath]?.use_partial_loading || false}
                                                onChange={(e) => handlePerFileConfigChange(filePath, { use_partial_loading: e.target.checked })}
                                                size="small"
                                                color="secondary"
                                              />
                                            }
                                            label={
                                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                <QueryStatsIcon sx={{ fontSize: '0.875rem' }} color="secondary" />
                                                <Typography variant="caption">Partial loading</Typography>
                                              </Box>
                                            }
                                          />
                                        </Tooltip>
                                      </Grid>

                                      {perFileConfigs[filePath]?.use_partial_loading && (
                                        <>
                                          <Grid item xs={12}>
                                            <FormControl fullWidth size="small">
                                              <InputLabel>Mode</InputLabel>
                                              <Select
                                                value={perFileConfigs[filePath]?.partial_mode || 'time_range'}
                                                label="Mode"
                                                onChange={(e) => handlePerFileConfigChange(filePath, { partial_mode: e.target.value as 'time_range' | 'event_count' })}
                                              >
                                                <MenuItem value="time_range">Time Range</MenuItem>
                                                <MenuItem value="event_count">Event Count</MenuItem>
                                              </Select>
                                            </FormControl>
                                          </Grid>
                                          {perFileConfigs[filePath]?.partial_mode === 'time_range' ? (
                                            <>
                                              <Grid item xs={6}>
                                                <TextField
                                                  size="small"
                                                  label="Start (s)"
                                                  type="number"
                                                  value={perFileConfigs[filePath]?.time_range_start ?? 0}
                                                  onChange={(e) => handlePerFileConfigChange(filePath, { time_range_start: parseFloat(e.target.value) || 0 })}
                                                  fullWidth
                                                />
                                              </Grid>
                                              <Grid item xs={6}>
                                                <TextField
                                                  size="small"
                                                  label="End (s)"
                                                  type="number"
                                                  value={perFileConfigs[filePath]?.time_range_end ?? 100}
                                                  onChange={(e) => handlePerFileConfigChange(filePath, { time_range_end: parseFloat(e.target.value) || 100 })}
                                                  fullWidth
                                                />
                                              </Grid>
                                            </>
                                          ) : (
                                            <>
                                              <Grid item xs={6}>
                                                <TextField
                                                  size="small"
                                                  label="Start Index"
                                                  type="number"
                                                  value={perFileConfigs[filePath]?.event_start_index ?? 0}
                                                  onChange={(e) => handlePerFileConfigChange(filePath, { event_start_index: parseInt(e.target.value) || 0 })}
                                                  fullWidth
                                                />
                                              </Grid>
                                              <Grid item xs={6}>
                                                <TextField
                                                  size="small"
                                                  label="Count"
                                                  type="number"
                                                  value={perFileConfigs[filePath]?.event_count ?? 10000}
                                                  onChange={(e) => handlePerFileConfigChange(filePath, { event_count: parseInt(e.target.value) || 10000 })}
                                                  fullWidth
                                                />
                                              </Grid>
                                            </>
                                          )}
                                        </>
                                      )}
                                    </Grid>
                                  </Box>
                                )}
                              </ListItem>
                            </React.Fragment>
                          );
                        })}
                      </List>
                    </Paper>
                  </Box>
                )}

              </Box>

              {/* File Format - only shown when using same settings for all files */}
              {useSameSettings && (
                <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                  <InputLabel>File Format</InputLabel>
                  <Select
                    value={fileFormat}
                    label="File Format"
                    onChange={(e) => setFileFormat(e.target.value as EventInputFormat)}
                  >
                    <MenuItem value="ogip">OGIP/FITS (recommended)</MenuItem>
                    <MenuItem value="hdf5">HDF5</MenuItem>
                    <MenuItem value="fits">FITS (generic)</MenuItem>
                    <MenuItem value="ascii.ecsv">ASCII ECSV</MenuItem>
                  </Select>
                </FormControl>
              )}

              {/* Advanced Options Toggle - only shown when using same settings for all files */}
              {useSameSettings && (
                <Button
                  size="small"
                  onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
                  startIcon={<SettingsIcon />}
                  endIcon={showAdvancedOptions ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                  sx={{ mb: 2, textTransform: 'none' }}
                >
                  Advanced Options
                </Button>
              )}

              {/* Advanced Options Content - only shown when using same settings for all files */}
              <Collapse in={showAdvancedOptions && useSameSettings}>
                <Box sx={{ mb: 2, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
                  {/* RMF File */}
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    RMF File (for PI → Energy calibration)
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                    <TextField
                      value={rmfSelection?.path || ''}
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
                    {rmfSelection && (
                      <IconButton size="small" onClick={() => setRmfSelection(null)}>
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

                  {/* Notes/Comments */}
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    Notes / Comments
                  </Typography>
                  <TextField
                    value={eventNotes}
                    onChange={(e) => setEventNotes(e.target.value)}
                    fullWidth
                    size="small"
                    multiline
                    rows={2}
                    placeholder="Add notes about this data (e.g., observation details, analysis purpose...)"
                    helperText="Optional annotations stored with the event list"
                    sx={{ mb: 2 }}
                  />

                  <Divider sx={{ my: 2 }} />

                  {/* Loading Options */}
                  <Typography variant="subtitle2" color="primary" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                    <MemoryIcon fontSize="small" />
                    Loading Options
                  </Typography>

                  {/* High Precision */}
                  <Tooltip
                    title={
                      <Box>
                        <Typography variant="body2" fontWeight="bold" gutterBottom>High Precision Timing</Typography>
                        <Typography variant="caption" component="p" gutterBottom>
                          Uses numpy.float128 (128-bit) instead of float64 for time arrays, providing ~18 more decimal digits of precision.
                        </Typography>
                        <Typography variant="caption" component="p" sx={{ mt: 1 }}>
                          <strong>Use when:</strong> Pulsar timing analysis, millisecond pulsars, phase-coherent timing, or any analysis requiring nanosecond-level accuracy.
                        </Typography>
                        <Typography variant="caption" component="p" sx={{ mt: 1 }}>
                          <strong>Avoid when:</strong> General spectral/timing analysis, large files (increases memory ~2x), or when float64 precision is sufficient.
                        </Typography>
                      </Box>
                    }
                    arrow
                    placement="right"
                  >
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={highPrecision}
                          onChange={(e) => setHighPrecision(e.target.checked)}
                          size="small"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <PrecisionManufacturingIcon fontSize="small" color="info" />
                          <Typography variant="body2">High precision timing</Typography>
                        </Box>
                      }
                    />
                  </Tooltip>

                  {/* Skip Checks */}
                  <Tooltip
                    title={
                      <Box>
                        <Typography variant="body2" fontWeight="bold" gutterBottom>Skip Validation Checks</Typography>
                        <Typography variant="caption" component="p" gutterBottom>
                          Bypasses time ordering verification and GTI (Good Time Interval) validation during loading.
                        </Typography>
                        <Typography variant="caption" component="p" sx={{ mt: 1 }}>
                          <strong>Use when:</strong> Loading trusted/verified data, re-loading previously validated files, or when you need faster loading and will validate manually.
                        </Typography>
                        <Typography variant="caption" component="p" sx={{ mt: 1 }}>
                          <strong>Avoid when:</strong> Loading new/untrusted data, data from unfamiliar sources, or when data integrity is critical for your analysis.
                        </Typography>
                      </Box>
                    }
                    arrow
                    placement="right"
                  >
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={skipChecks}
                          onChange={(e) => setSkipChecks(e.target.checked)}
                          size="small"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <BoltIcon fontSize="small" color="warning" />
                          <Typography variant="body2">Skip validation checks</Typography>
                        </Box>
                      }
                    />
                  </Tooltip>

                  {/* Partial Loading */}
                  <Tooltip
                    title={
                      <Box>
                        <Typography variant="body2" fontWeight="bold" gutterBottom>Partial Loading</Typography>
                        <Typography variant="caption" component="p" gutterBottom>
                          Loads only a specific portion of the file (by time range or event count) without reading the entire file into memory.
                        </Typography>
                        <Typography variant="caption" component="p" sx={{ mt: 1 }}>
                          <strong>Use when:</strong> Working with large FITS files (&gt;1GB), exploring data before full analysis, or when you only need a specific time segment.
                        </Typography>
                        <Typography variant="caption" component="p" sx={{ mt: 1 }}>
                          <strong>Avoid when:</strong> Using non-FITS formats (HDF5, CSV), or when you need the complete dataset for analysis.
                        </Typography>
                        <Typography variant="caption" component="p" sx={{ mt: 1, fontStyle: 'italic' }}>
                          Note: Only FITS formats are supported.
                        </Typography>
                      </Box>
                    }
                    arrow
                    placement="right"
                  >
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={useTrueLazyLoading}
                          onChange={(e) => setUseTrueLazyLoading(e.target.checked)}
                          size="small"
                          color="secondary"
                        />
                      }
                      label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <QueryStatsIcon fontSize="small" color="secondary" />
                          <Typography variant="body2">Partial loading</Typography>
                        </Box>
                      }
                    />
                  </Tooltip>

                  {/* True Lazy Loading Options */}
                  {useTrueLazyLoading && (
                    <Box sx={{ mt: 2, p: 2, bgcolor: 'secondary.50', borderRadius: 1, border: '1px solid', borderColor: 'secondary.main' }}>
                      {/* Get Metadata Button */}
                      <Button
                        variant="outlined"
                        color="secondary"
                        size="small"
                        onClick={fetchFileMetadata}
                        disabled={isLoadingMetadata || selectedFiles.length === 0}
                        startIcon={isLoadingMetadata ? <CircularProgress size={16} /> : <QueryStatsIcon />}
                        sx={{ mb: 2 }}
                        fullWidth
                      >
                        {isLoadingMetadata ? 'Loading...' : 'Get File Metadata'}
                      </Button>

                      {/* File Metadata Display */}
                      {fileMetadata && (
                        <Box sx={{ mb: 2, p: 1.5, bgcolor: 'background.paper', borderRadius: 1 }}>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            <strong>Total Events:</strong> {fileMetadata.total_events.toLocaleString()}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            <strong>Duration:</strong> {fileMetadata.duration.toFixed(2)}s
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            <strong>File Size:</strong> {fileMetadata.file_size_mb.toFixed(1)} MB
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            <strong>GTIs:</strong> {fileMetadata.gti_count}
                          </Typography>
                          {fileMetadata.mission && (
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                              <strong>Mission:</strong> {fileMetadata.mission}
                            </Typography>
                          )}
                          <Chip
                            label={`Recommended: ${fileMetadata.recommended_loading.strategy}`}
                            size="small"
                            color="secondary"
                            variant="outlined"
                            sx={{ mt: 1 }}
                          />
                        </Box>
                      )}

                      {/* Mode Selection */}
                      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                        <InputLabel>Loading Mode</InputLabel>
                        <Select
                          value={trueLazyMode}
                          label="Loading Mode"
                          onChange={(e) => setTrueLazyMode(e.target.value as 'time_range' | 'event_count')}
                        >
                          <MenuItem value="time_range">
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <AccessTimeIcon fontSize="small" />
                              Load by Time Range
                            </Box>
                          </MenuItem>
                          <MenuItem value="event_count">
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <NumbersIcon fontSize="small" />
                              Load by Event Count
                            </Box>
                          </MenuItem>
                        </Select>
                      </FormControl>

                      {/* Time Range Mode */}
                      {trueLazyMode === 'time_range' && (
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          <TextField
                            label="Start Time (s)"
                            type="number"
                            value={timeRangeStart}
                            onChange={(e) => setTimeRangeStart(parseFloat(e.target.value) || 0)}
                            size="small"
                            fullWidth
                            inputProps={{ min: 0, step: 1 }}
                          />
                          <TextField
                            label="End Time (s)"
                            type="number"
                            value={timeRangeEnd}
                            onChange={(e) => setTimeRangeEnd(parseFloat(e.target.value) || 100)}
                            size="small"
                            fullWidth
                            inputProps={{ min: 0, step: 1 }}
                          />
                        </Box>
                      )}

                      {/* Event Count Mode */}
                      {trueLazyMode === 'event_count' && (
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          <TextField
                            label="Start Index"
                            type="number"
                            value={eventCountStart}
                            onChange={(e) => setEventCountStart(parseInt(e.target.value) || 0)}
                            size="small"
                            fullWidth
                            inputProps={{ min: 0, step: 1000 }}
                          />
                          <TextField
                            label="Event Count"
                            type="number"
                            value={eventCount}
                            onChange={(e) => setEventCount(parseInt(e.target.value) || 10000)}
                            size="small"
                            fullWidth
                            inputProps={{ min: 1, step: 1000 }}
                          />
                        </Box>
                      )}

                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                        {trueLazyMode === 'time_range'
                          ? `Will load events from ${timeRangeStart}s to ${timeRangeEnd}s (${timeRangeEnd - timeRangeStart}s duration)`
                          : `Will load ${eventCount.toLocaleString()} events starting from index ${eventCountStart.toLocaleString()}`}
                      </Typography>
                    </Box>
                  )}

                  {/* Loading mode indicator */}
                  {useTrueLazyLoading && (
                    <Alert
                      severity="success"
                      sx={{ mt: 2 }}
                      icon={<QueryStatsIcon />}
                    >
                      {trueLazyMode === 'time_range'
                        ? `Partial loading: Only events in [${timeRangeStart}s - ${timeRangeEnd}s] will be loaded.`
                        : `Partial loading: Only ${eventCount.toLocaleString()} events starting at index ${eventCountStart} will be loaded.`}
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
                {isLoading
                  ? (selectedFiles.length > 1 ? `Loading ${selectedFiles.length} files...` : 'Loading...')
                  : (selectedFiles.length > 1
                    ? `Load ${selectedFiles.length} Event Lists`
                    : 'Load Event List')}
              </Button>

              {/* Note: Batch loading progress is now shown in the sidebar job queue */}
            </Box>
          )}

          {/* Tab 1: Load from URL */}
          {dataInputTab === 1 && (
            <Box>
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
                  onChange={(e) => setUrlFormat(e.target.value as EventInputFormat)}
                >
                  <MenuItem value="ogip">OGIP/FITS (recommended)</MenuItem>
                  <MenuItem value="hdf5">HDF5</MenuItem>
                  <MenuItem value="fits">FITS (generic)</MenuItem>
                  <MenuItem value="ascii.ecsv">ASCII ECSV</MenuItem>
                </Select>
              </FormControl>

              {/* Note: Download progress is now shown in the sidebar job queue */}

              {/* Load Button */}
              <Button
                variant="contained"
                onClick={handleLoadFromUrl}
                disabled={isLoadingUrl || !urlInput.trim()}
                fullWidth
                startIcon={isLoadingUrl ? <CircularProgress size={20} /> : <CloudUploadIcon />}
              >
                {isLoadingUrl ? 'Submitting...' : 'Fetch from URL'}
              </Button>
            </Box>
          )}

          {/* Tab 2: Browse HEASARC */}
          {dataInputTab === 2 && (
            <HeasarcBrowserPanel onDataLoaded={fetchEventLists} />
          )}
        </CardContent>
      </Card>

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
                        {eventList.gti_warnings && eventList.gti_warnings.length > 0 && (
                          <Tooltip title={eventList.gti_warnings.join('\n')}>
                            <Chip
                              label={`${eventList.gti_warnings.length} GTI warning${eventList.gti_warnings.length > 1 ? 's' : ''}`}
                              size="small"
                              color="warning"
                              icon={<WarningAmberIcon />}
                            />
                          </Tooltip>
                        )}
                        {/* Validation issues */}
                        {eventList.validation_issues && eventList.validation_issues.length > 0 && (() => {
                          const errors = eventList.validation_issues.filter((v) => v.severity === 'error');
                          const warnings = eventList.validation_issues.filter((v) => v.severity === 'warning');
                          return (
                            <>
                              {errors.length > 0 && (
                                <Tooltip title={errors.map((e) => e.message).join('\n')}>
                                  <Chip
                                    label={`${errors.length} data error${errors.length > 1 ? 's' : ''}`}
                                    size="small"
                                    color="error"
                                    icon={<WarningAmberIcon />}
                                  />
                                </Tooltip>
                              )}
                              {warnings.length > 0 && (
                                <Tooltip title={warnings.map((w) => w.message).join('\n')}>
                                  <Chip
                                    label={`${warnings.length} data warning${warnings.length > 1 ? 's' : ''}`}
                                    size="small"
                                    color="warning"
                                    variant="outlined"
                                  />
                                </Tooltip>
                              )}
                            </>
                          );
                        })()}
                        {/* Notes indicator */}
                        {eventList.notes && (
                          <Tooltip title={eventList.notes}>
                            <Chip label="Notes" size="small" variant="outlined" />
                          </Tooltip>
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
                    <Tooltip title="Export to a native-selected destination">
                      <IconButton
                        edge="end"
                        sx={{ mr: 0.5 }}
                        onClick={() => void handleSaveEventList(eventList.name)}
                        disabled={saveFormatsLoadingName === eventList.name}
                        color="primary"
                      >
                        {saveFormatsLoadingName === eventList.name ? (
                          <CircularProgress size={20} />
                        ) : (
                          <SaveIcon />
                        )}
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
                    <Typography variant="body1">{selectedEventListDetails.duration.toFixed(6)}s</Typography>
                  </Grid>
                  <Grid item xs={6} sm={4}>
                    <Typography variant="caption" color="text.secondary">Mean Count Rate</Typography>
                    <Typography variant="body1">
                      {selectedEventListDetails.mean_count_rate?.toFixed(6) || 'N/A'} cts/s
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
                      <Typography variant="body1">{selectedEventListDetails.min_time_diff.toExponential(6)}s</Typography>
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
                      label={`Energy${selectedEventListDetails.energy_range ? ` (${selectedEventListDetails.energy_range[0].toFixed(4)}-${selectedEventListDetails.energy_range[1].toFixed(4)} keV)` : ''}`}
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
                          Total: {selectedEventListDetails.total_gti_time.toFixed(6)}s
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
                              <TableCell>{gti[0].toFixed(6)}</TableCell>
                              <TableCell>{gti[1].toFixed(6)}</TableCell>
                              <TableCell>{(gti[1] - gti[0]).toFixed(6)}s</TableCell>
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
                variant="scrollable"
                scrollButtons="auto"
              >
                <Tab label="Overview" />
                <Tab label="Time Data" />
                <Tab label="Energy & PI" />
                <Tab label="GTIs" />
                <Tab label="Metadata" />
                <Tab label="Header" />
                <Tab label="Validation" />
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
                          {fullPreviewData.duration.toFixed(6)}s
                        </Typography>
                        <Typography variant="caption" color="text.secondary">Duration</Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                        <Typography variant="h4" color="success.main">
                          {fullPreviewData.mean_count_rate?.toFixed(6) || 'N/A'}
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
                        {fullPreviewData.min_time_diff?.toExponential(6) || 'N/A'}s
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Max Time Diff</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.max_time_diff?.toExponential(6) || 'N/A'}s
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Mean Time Diff</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.mean_time_diff?.toExponential(6) || 'N/A'}s
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Median Time Diff</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.median_time_diff?.toExponential(6) || 'N/A'}s
                      </Typography>
                    </Grid>
                    <Grid item xs={6} sm={4}>
                      <Typography variant="caption" color="text.secondary">Std Dev Time Diff</Typography>
                      <Typography variant="body1" fontFamily="monospace">
                        {fullPreviewData.std_time_diff?.toExponential(6) || 'N/A'}s
                      </Typography>
                    </Grid>
                  </Grid>

                  {/* Per-GTI Rates */}
                  {fullPreviewData.per_gti_rates && fullPreviewData.per_gti_rates.length > 0 && (
                    <>
                      <Divider />
                      <Typography variant="subtitle2" color="primary">
                        Per-GTI Count Rates ({fullPreviewData.per_gti_rates.length} GTI{fullPreviewData.per_gti_rates.length !== 1 ? 's' : ''})
                      </Typography>
                      <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 200 }}>
                        <Table size="small" stickyHeader>
                          <TableHead>
                            <TableRow>
                              <TableCell>#</TableCell>
                              <TableCell>Start (s)</TableCell>
                              <TableCell>Stop (s)</TableCell>
                              <TableCell>Events</TableCell>
                              <TableCell>Duration (s)</TableCell>
                              <TableCell>Rate (cts/s)</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {fullPreviewData.per_gti_rates.map((gti, index) => (
                              <TableRow key={index}>
                                <TableCell>{index + 1}</TableCell>
                                <TableCell sx={{ fontFamily: 'monospace' }}>{gti.start.toFixed(6)}</TableCell>
                                <TableCell sx={{ fontFamily: 'monospace' }}>{gti.stop.toFixed(6)}</TableCell>
                                <TableCell>{gti.events.toLocaleString()}</TableCell>
                                <TableCell sx={{ fontFamily: 'monospace' }}>{gti.duration.toFixed(6)}</TableCell>
                                <TableCell sx={{ fontFamily: 'monospace' }}>{gti.rate.toFixed(6)}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    </>
                  )}

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
                              ? `${fullPreviewData.energy_range[0].toFixed(5)} - ${fullPreviewData.energy_range[1].toFixed(5)} keV`
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
                                label={`${energy.toFixed(5)} keV`}
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
                      Total GTI Time: {fullPreviewData.total_gti_time.toFixed(6)}s
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
                              <TableCell sx={{ fontFamily: 'monospace' }}>{gti[0].toFixed(6)}</TableCell>
                              <TableCell sx={{ fontFamily: 'monospace' }}>{gti[1].toFixed(6)}</TableCell>
                              <TableCell sx={{ fontFamily: 'monospace' }}>{(gti[1] - gti[0]).toFixed(6)}</TableCell>
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

                  {/* User Notes */}
                  {fullPreviewData.notes && (
                    <>
                      <Divider />
                      <Typography variant="subtitle2" color="primary">User Notes</Typography>
                      <Paper variant="outlined" sx={{ p: 2, bgcolor: 'action.hover' }}>
                        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                          {fullPreviewData.notes}
                        </Typography>
                      </Paper>
                    </>
                  )}
                </Box>
              )}

              {/* Header Tab */}
              {previewTabValue === 5 && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {fullPreviewData.header_info && Object.keys(fullPreviewData.header_info).length > 0 ? (
                    <>
                      <Typography variant="subtitle2" color="primary">Key FITS Headers</Typography>
                      <Grid container spacing={2}>
                        {fullPreviewData.header_info.object && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Object</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.object}</Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.obs_id && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">OBS_ID</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.obs_id}</Typography>
                          </Grid>
                        )}
                        {(fullPreviewData.header_info.ra_nom !== undefined || fullPreviewData.header_info.ra_obj !== undefined) && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">RA</Typography>
                            <Typography variant="body1" fontFamily="monospace">
                              {(fullPreviewData.header_info.ra_nom ?? fullPreviewData.header_info.ra_obj)?.toFixed(7) || 'N/A'}°
                            </Typography>
                          </Grid>
                        )}
                        {(fullPreviewData.header_info.dec_nom !== undefined || fullPreviewData.header_info.dec_obj !== undefined) && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Dec</Typography>
                            <Typography variant="body1" fontFamily="monospace">
                              {(fullPreviewData.header_info.dec_nom ?? fullPreviewData.header_info.dec_obj)?.toFixed(7) || 'N/A'}°
                            </Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.exposure !== undefined && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Exposure</Typography>
                            <Typography variant="body1" fontFamily="monospace">
                              {fullPreviewData.header_info.exposure?.toFixed(6) || 'N/A'}s
                            </Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.ontime !== undefined && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Ontime</Typography>
                            <Typography variant="body1" fontFamily="monospace">
                              {fullPreviewData.header_info.ontime?.toFixed(6) || 'N/A'}s
                            </Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.livetime !== undefined && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Livetime</Typography>
                            <Typography variant="body1" fontFamily="monospace">
                              {fullPreviewData.header_info.livetime?.toFixed(6) || 'N/A'}s
                            </Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.date_obs && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">DATE-OBS</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.date_obs}</Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.date_end && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">DATE-END</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.date_end}</Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.telescop && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Telescope</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.telescop}</Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.instrume && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Instrument</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.instrume}</Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.creator && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Creator</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.creator}</Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.observer && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Observer</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.observer}</Typography>
                          </Grid>
                        )}
                        {fullPreviewData.header_info.datamode && (
                          <Grid item xs={6} sm={4}>
                            <Typography variant="caption" color="text.secondary">Data Mode</Typography>
                            <Typography variant="body1">{fullPreviewData.header_info.datamode}</Typography>
                          </Grid>
                        )}
                      </Grid>

                      {/* Raw Header Table */}
                      {fullPreviewData.header_info.raw_header && Object.keys(fullPreviewData.header_info.raw_header).length > 0 && (
                        <>
                          <Divider />
                          <Typography variant="subtitle2" color="primary">
                            Raw FITS Header ({Object.keys(fullPreviewData.header_info.raw_header).length} entries)
                          </Typography>
                          <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 300 }}>
                            <Table size="small" stickyHeader>
                              <TableHead>
                                <TableRow>
                                  <TableCell sx={{ fontWeight: 'bold', width: '30%' }}>Keyword</TableCell>
                                  <TableCell sx={{ fontWeight: 'bold' }}>Value</TableCell>
                                </TableRow>
                              </TableHead>
                              <TableBody>
                                {Object.entries(fullPreviewData.header_info.raw_header).map(([key, value]) => (
                                  <TableRow key={key}>
                                    <TableCell sx={{ fontFamily: 'monospace' }}>{key}</TableCell>
                                    <TableCell sx={{ fontFamily: 'monospace', wordBreak: 'break-word' }}>{value}</TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </TableContainer>
                        </>
                      )}
                    </>
                  ) : (
                    <Alert severity="info">No FITS header information available for this EventList</Alert>
                  )}
                </Box>
              )}

              {/* Validation Tab */}
              {previewTabValue === 6 && (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <Typography variant="subtitle2" color="primary">Data Quality Validation</Typography>
                  {fullPreviewData.validation_issues && fullPreviewData.validation_issues.length > 0 ? (
                    <>
                      {/* Summary */}
                      <Box sx={{ display: 'flex', gap: 1, mb: 1, flexWrap: 'wrap' }}>
                        {(() => {
                          const passed = fullPreviewData.validation_issues.filter((v: ValidationIssue) => v.status === 'pass');
                          const failed = fullPreviewData.validation_issues.filter((v: ValidationIssue) => v.status === 'fail');
                          const skipped = fullPreviewData.validation_issues.filter((v: ValidationIssue) => v.status === 'skip');
                          const errors = fullPreviewData.validation_issues.filter((v: ValidationIssue) => v.severity === 'error');
                          const warnings = fullPreviewData.validation_issues.filter((v: ValidationIssue) => v.severity === 'warning');
                          return (
                            <>
                              <Chip
                                label={`${passed.length} Passed`}
                                color="success"
                                size="small"
                                icon={<CheckCircleIcon />}
                              />
                              {failed.length > 0 && (
                                <Chip
                                  label={`${failed.length} Failed`}
                                  color="error"
                                  size="small"
                                  icon={<ErrorIcon />}
                                />
                              )}
                              {skipped.length > 0 && (
                                <Chip
                                  label={`${skipped.length} Skipped`}
                                  color="default"
                                  size="small"
                                />
                              )}
                              {errors.length > 0 && (
                                <Chip label={`${errors.length} Error${errors.length !== 1 ? 's' : ''}`} color="error" size="small" variant="outlined" />
                              )}
                              {warnings.length > 0 && (
                                <Chip label={`${warnings.length} Warning${warnings.length !== 1 ? 's' : ''}`} color="warning" size="small" variant="outlined" />
                              )}
                            </>
                          );
                        })()}
                      </Box>

                      {/* All Checks List */}
                      <TableContainer component={Paper} variant="outlined">
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell sx={{ width: '8%' }}>Status</TableCell>
                              <TableCell sx={{ width: '22%' }}>Check</TableCell>
                              <TableCell sx={{ width: '45%' }}>Result</TableCell>
                              <TableCell sx={{ width: '15%' }}>Details</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {fullPreviewData.validation_issues.map((issue: ValidationIssue, index: number) => (
                              <TableRow
                                key={index}
                                sx={{
                                  backgroundColor: issue.status === 'pass'
                                    ? 'rgba(34, 197, 94, 0.06)'
                                    : issue.status === 'fail'
                                      ? 'rgba(239, 68, 68, 0.06)'
                                      : 'rgba(148, 163, 184, 0.06)'
                                }}
                              >
                                <TableCell>
                                  {issue.status === 'pass' && (
                                    <Chip label="PASS" size="small" color="success" sx={{ fontWeight: 'bold', minWidth: 60 }} />
                                  )}
                                  {issue.status === 'fail' && (
                                    <Chip
                                      label={issue.severity === 'error' ? 'FAIL' : 'WARN'}
                                      size="small"
                                      color={issue.severity === 'error' ? 'error' : 'warning'}
                                      sx={{ fontWeight: 'bold', minWidth: 60 }}
                                    />
                                  )}
                                  {issue.status === 'skip' && (
                                    <Chip label="SKIP" size="small" color="default" sx={{ fontWeight: 'bold', minWidth: 60 }} />
                                  )}
                                </TableCell>
                                <TableCell>
                                  <Typography variant="body2" fontWeight="medium">
                                    {issue.name || issue.type}
                                  </Typography>
                                  {issue.description && (
                                    <Typography variant="caption" color="text.secondary" display="block">
                                      {issue.description}
                                    </Typography>
                                  )}
                                </TableCell>
                                <TableCell>
                                  <Typography variant="body2">{issue.message}</Typography>
                                </TableCell>
                                <TableCell sx={{ fontFamily: 'monospace' }}>
                                  {issue.status !== 'skip' && issue.total !== undefined && issue.total > 0 && (
                                    <Typography variant="body2">
                                      {issue.count?.toLocaleString() || 0} / {issue.total?.toLocaleString()}
                                    </Typography>
                                  )}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    </>
                  ) : (
                    <Alert severity="info">
                      <Typography variant="body2">
                        No validation data available. Try reloading the event list.
                      </Typography>
                    </Alert>
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

      {/* Save Format Selection Dialog */}
      <Dialog
        open={saveFormatDialogOpen}
        onClose={() => setSaveFormatDialogOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>
          Choose Save Format
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Select a runtime-supported, reopen-verified format for &quot;{saveEventListName}&quot;:
          </Typography>
          {hdf5UnavailableReason && (
            <Alert severity="info" sx={{ mb: 2 }}>
              HDF5 unavailable: {hdf5UnavailableReason}
            </Alert>
          )}
          <FormControl component="fieldset">
            <RadioGroup
              value={selectedSaveFormat}
              onChange={(e) => setSelectedSaveFormat(e.target.value as LegacySaveFormat)}
            >
              {availableSaveFormats.includes('hdf5') && (
                <FormControlLabel
                  value="hdf5"
                  control={<Radio />}
                  label={
                    <Box>
                      <Typography variant="body1" fontWeight="medium">
                        HDF5 (Recommended)
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Versioned Stingray Explorer schema with scientific round-trip verification.
                      </Typography>
                    </Box>
                  }
                />
              )}
              {availableSaveFormats.includes('ecsv') && (
                <FormControlLabel
                  value="ecsv"
                  control={<Radio />}
                  label={
                    <Box>
                      <Typography variant="body1" fontWeight="medium">
                        ASCII ECSV
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Human-readable table with metadata and reopen verification.
                      </Typography>
                    </Box>
                  }
                  sx={{ mt: 1 }}
                />
              )}
            </RadioGroup>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSaveFormatDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleConfirmSave} variant="contained" color="primary">
            Choose Location
          </Button>
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
