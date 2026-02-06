/**
 * File Browser Dialog for HEASARC observations
 *
 * Shows a tree view of files in an observation directory,
 * allowing users to select and download files to their local disk.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  CircularProgress,
  Alert,
  Checkbox,
  IconButton,
  Collapse,
  LinearProgress,
  Chip,
} from '@mui/material';
import FolderIcon from '@mui/icons-material/Folder';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import StarIcon from '@mui/icons-material/Star';
import SettingsIcon from '@mui/icons-material/Settings';
import AttachFileIcon from '@mui/icons-material/AttachFile';
import DescriptionIcon from '@mui/icons-material/Description';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import SaveAltIcon from '@mui/icons-material/SaveAlt';
import {
  archiveApi,
  FileEntry,
  FileType,
  DownloadToDiskEvent,
} from '@/api/archiveApi';
import { useUIStore } from '@/store/uiStore';

interface ObsData {
  ra?: number | null;
  dec?: number | null;
  prnb?: string;
}

interface FileBrowserDialogProps {
  open: boolean;
  onClose: () => void;
  mission: string;
  obsid: string;
  obsTime: string;
  targetName: string;
  obsData?: ObsData;
  onDownloadComplete?: (filePath: string) => void;
}

interface DownloadState {
  status: 'idle' | 'downloading' | 'complete' | 'error';
  message: string;
  percent: number;
  filePath?: string;
  error?: string;
}

// File type to icon mapping
const getFileIcon = (fileType: FileType): React.ReactNode => {
  switch (fileType) {
    case 'event':
      return <StarIcon fontSize="small" sx={{ color: 'warning.main' }} />;
    case 'calibration':
      return <SettingsIcon fontSize="small" sx={{ color: 'info.main' }} />;
    case 'auxiliary':
      return <AttachFileIcon fontSize="small" sx={{ color: 'text.secondary' }} />;
    case 'log':
      return <DescriptionIcon fontSize="small" sx={{ color: 'text.disabled' }} />;
    default:
      return <InsertDriveFileIcon fontSize="small" sx={{ color: 'text.secondary' }} />;
  }
};

interface FileTreeItemProps {
  entry: FileEntry;
  depth: number;
  selectedFiles: Set<string>;
  onToggleSelect: (entry: FileEntry) => void;
  expandedDirs: Set<string>;
  onToggleExpand: (path: string) => void;
}

const FileTreeItem: React.FC<FileTreeItemProps> = ({
  entry,
  depth,
  selectedFiles,
  onToggleSelect,
  expandedDirs,
  onToggleExpand,
}) => {
  const isExpanded = expandedDirs.has(entry.full_url);
  const isSelected = selectedFiles.has(entry.full_url);

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          py: 0.5,
          pl: depth * 2,
          '&:hover': { bgcolor: 'action.hover' },
          cursor: entry.is_directory ? 'pointer' : 'default',
        }}
        onClick={() => entry.is_directory && onToggleExpand(entry.full_url)}
      >
        {/* Expand/collapse button for directories */}
        {entry.is_directory ? (
          <IconButton size="small" sx={{ p: 0.25 }}>
            {isExpanded ? <ExpandMoreIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
          </IconButton>
        ) : (
          <Box sx={{ width: 24 }} />
        )}

        {/* Checkbox for files only */}
        {!entry.is_directory && (
          <Checkbox
            size="small"
            checked={isSelected}
            onChange={() => onToggleSelect(entry)}
            onClick={(e) => e.stopPropagation()}
            sx={{ p: 0.25 }}
          />
        )}

        {/* Icon */}
        <Box sx={{ mx: 0.5, display: 'flex', alignItems: 'center' }}>
          {entry.is_directory ? (
            isExpanded ? (
              <FolderOpenIcon fontSize="small" sx={{ color: 'primary.main' }} />
            ) : (
              <FolderIcon fontSize="small" sx={{ color: 'primary.main' }} />
            )
          ) : (
            getFileIcon(entry.file_type)
          )}
        </Box>

        {/* File name */}
        <Typography
          variant="body2"
          sx={{
            flex: 1,
            fontFamily: 'monospace',
            fontSize: '0.85rem',
            fontWeight: entry.file_type === 'event' ? 'bold' : 'normal',
          }}
        >
          {entry.name}
        </Typography>

        {/* File type chip for event files */}
        {entry.file_type === 'event' && (
          <Chip
            label="Event"
            size="small"
            color="warning"
            sx={{ mx: 1, height: 20, '& .MuiChip-label': { px: 1, fontSize: '0.7rem' } }}
          />
        )}

        {/* File size */}
        {!entry.is_directory && entry.size_display && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ minWidth: 80, textAlign: 'right' }}
          >
            {entry.size_display}
          </Typography>
        )}
      </Box>

      {/* Children */}
      {entry.is_directory && entry.children && (
        <Collapse in={isExpanded}>
          {entry.children.map((child) => (
            <FileTreeItem
              key={child.full_url}
              entry={child}
              depth={depth + 1}
              selectedFiles={selectedFiles}
              onToggleSelect={onToggleSelect}
              expandedDirs={expandedDirs}
              onToggleExpand={onToggleExpand}
            />
          ))}
        </Collapse>
      )}
    </Box>
  );
};

const FileBrowserDialog: React.FC<FileBrowserDialogProps> = ({
  open,
  onClose,
  mission,
  obsid,
  obsTime,
  targetName,
  obsData,
  onDownloadComplete,
}) => {
  const { addNotification } = useUIStore();

  // Loading and data state
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [baseUrl, setBaseUrl] = useState<string>('');

  // Selection state
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());

  // Download state
  const [downloadState, setDownloadState] = useState<DownloadState>({
    status: 'idle',
    message: '',
    percent: 0,
  });

  // Load files when dialog opens
  useEffect(() => {
    if (open) {
      loadFiles();
    }
  }, [open, mission, obsid, obsTime, obsData]);

  const loadFiles = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    setSelectedFiles(new Set());
    setExpandedDirs(new Set());
    setDownloadState({ status: 'idle', message: '', percent: 0 });

    try {
      const response = await archiveApi.listObservationFiles({
        mission,
        obsid,
        obs_time: obsTime,
        obs_data: obsData,
        recursive: true,
        max_depth: 3,
      });

      if (response.success && response.data) {
        setFiles(response.data.files);
        setBaseUrl(response.data.base_url);

        // Auto-expand directories with event files and auto-select first event file
        const dirsToExpand = new Set<string>();
        let firstEventFileUrl: string | null = null;

        const findEventFiles = (entries: FileEntry[], parentUrl: string): void => {
          for (const entry of entries) {
            if (entry.is_directory && entry.children) {
              const hasEventFile = entry.children.some(
                (c) => c.file_type === 'event' || c.is_directory
              );
              if (hasEventFile) {
                dirsToExpand.add(entry.full_url);
              }
              findEventFiles(entry.children, entry.full_url);
            } else if (entry.file_type === 'event' && !firstEventFileUrl) {
              firstEventFileUrl = entry.full_url;
              dirsToExpand.add(parentUrl);
            }
          }
        };

        findEventFiles(response.data.files, response.data.base_url);
        setExpandedDirs(dirsToExpand);

        if (firstEventFileUrl) {
          setSelectedFiles(new Set([firstEventFileUrl]));
        }
      } else {
        setError(response.message || 'Failed to list files');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to list files');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleSelect = useCallback((entry: FileEntry): void => {
    setSelectedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(entry.full_url)) {
        next.delete(entry.full_url);
      } else {
        next.add(entry.full_url);
      }
      return next;
    });
  }, []);

  const handleToggleExpand = useCallback((path: string): void => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  // Get selected file info
  const getSelectedFileInfo = (): { url: string; name: string; size: number } | null => {
    const findFile = (entries: FileEntry[]): FileEntry | null => {
      for (const entry of entries) {
        if (selectedFiles.has(entry.full_url) && !entry.is_directory) {
          return entry;
        }
        if (entry.is_directory && entry.children) {
          const found = findFile(entry.children);
          if (found) return found;
        }
      }
      return null;
    };

    const file = findFile(files);
    if (file) {
      return {
        url: file.full_url,
        name: file.name,
        size: file.size_bytes || 0,
      };
    }
    return null;
  };

  // Calculate selected files info for display
  const getSelectedFilesInfo = (): { count: number; totalSize: number; hasEventFile: boolean } => {
    let count = 0;
    let totalSize = 0;
    let hasEventFile = false;

    const checkFiles = (entries: FileEntry[]): void => {
      for (const entry of entries) {
        if (entry.is_directory && entry.children) {
          checkFiles(entry.children);
        } else if (selectedFiles.has(entry.full_url)) {
          count++;
          if (entry.size_bytes) totalSize += entry.size_bytes;
          if (entry.file_type === 'event') hasEventFile = true;
        }
      }
    };

    checkFiles(files);
    return { count, totalSize, hasEventFile };
  };

  const selectedInfo = getSelectedFilesInfo();

  const formatTotalSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  };

  // Handle download to local disk via backend (bypasses CORS)
  const handleDownload = async (): Promise<void> => {
    const fileInfo = getSelectedFileInfo();
    if (!fileInfo) {
      addNotification({
        type: 'warning',
        title: 'No File Selected',
        message: 'Please select a file to download',
      });
      return;
    }

    // Ask user where to save the file
    const savePath = await window.electronAPI.saveFile({
      title: 'Save Downloaded File',
      defaultPath: fileInfo.name,
      filters: [
        { name: 'FITS Files', extensions: ['fits', 'fits.gz', 'evt', 'evt.gz'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    });

    if (!savePath) {
      return; // User cancelled
    }

    setDownloadState({
      status: 'downloading',
      message: 'Starting download...',
      percent: 0,
    });

    try {
      // Download via backend to bypass CORS restrictions
      // The backend downloads from HEASARC and saves directly to disk
      for await (const event of archiveApi.downloadToDiskSSE({
        url: fileInfo.url,
        save_path: savePath,
      })) {
        if (event.type === 'progress') {
          const { bytes_downloaded, total_bytes, percent } = event;
          if (total_bytes > 0) {
            setDownloadState({
              status: 'downloading',
              message: `Downloading: ${percent.toFixed(1)}% (${formatTotalSize(bytes_downloaded)} / ${formatTotalSize(total_bytes)})`,
              percent,
            });
          } else {
            setDownloadState({
              status: 'downloading',
              message: `Downloading: ${formatTotalSize(bytes_downloaded)}`,
              percent: 0,
            });
          }
        } else if (event.type === 'complete') {
          setDownloadState({
            status: 'complete',
            message: `Downloaded to: ${event.file_path}`,
            percent: 100,
            filePath: event.file_path,
          });

          addNotification({
            type: 'success',
            title: 'Download Complete',
            message: `File saved to ${event.file_path}. Use "Load from Local" to load it.`,
          });

          onDownloadComplete?.(event.file_path);
        } else if (event.type === 'error') {
          throw new Error(event.error);
        }
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Download failed';
      setDownloadState({
        status: 'error',
        message: errorMsg,
        percent: 0,
        error: errorMsg,
      });
      addNotification({
        type: 'error',
        title: 'Download Failed',
        message: errorMsg,
      });
    }
  };

  // Open file location in system file manager
  const handleShowInFolder = (): void => {
    if (downloadState.filePath) {
      window.electronAPI.showItemInFolder(downloadState.filePath);
    }
  };

  const isDownloading = downloadState.status === 'downloading';

  return (
    <Dialog
      open={open}
      onClose={isDownloading ? undefined : onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{ sx: { minHeight: 500 } }}
    >
      <DialogTitle>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <FolderOpenIcon color="primary" />
          <Box>
            <Typography variant="h6">
              Browse Files: {mission} Observation {obsid}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Target: {targetName}
            </Typography>
          </Box>
        </Box>
      </DialogTitle>

      <DialogContent dividers>
        {loading ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 4 }}>
            <CircularProgress />
            <Typography variant="body2" sx={{ mt: 2 }}>
              Loading file list...
            </Typography>
          </Box>
        ) : error ? (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        ) : (
          <>
            {/* Base URL display */}
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', mb: 1, fontFamily: 'monospace' }}
            >
              {baseUrl}
            </Typography>

            {/* File tree */}
            <Box
              sx={{
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                maxHeight: 300,
                overflow: 'auto',
                bgcolor: 'background.default',
              }}
            >
              {files.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                  No files found in this observation directory.
                </Typography>
              ) : (
                files.map((entry) => (
                  <FileTreeItem
                    key={entry.full_url}
                    entry={entry}
                    depth={0}
                    selectedFiles={selectedFiles}
                    onToggleSelect={handleToggleSelect}
                    expandedDirs={expandedDirs}
                    onToggleExpand={handleToggleExpand}
                  />
                ))
              )}
            </Box>

            {/* Selection info */}
            <Box sx={{ mt: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
              <Typography variant="body2">
                Selected: {selectedInfo.count} file{selectedInfo.count !== 1 ? 's' : ''}
                {selectedInfo.totalSize > 0 && ` (${formatTotalSize(selectedInfo.totalSize)})`}
              </Typography>
              {selectedInfo.hasEventFile && (
                <Chip
                  icon={<StarIcon />}
                  label="Event file"
                  size="small"
                  color="warning"
                />
              )}
            </Box>

            {/* Download progress/status */}
            {downloadState.status !== 'idle' && (
              <Box sx={{ mt: 2 }}>
                {downloadState.status === 'error' ? (
                  <Alert severity="error">{downloadState.message}</Alert>
                ) : downloadState.status === 'complete' ? (
                  <Alert
                    severity="success"
                    action={
                      <Button color="inherit" size="small" onClick={handleShowInFolder}>
                        Show in Folder
                      </Button>
                    }
                  >
                    {downloadState.message}
                  </Alert>
                ) : (
                  <>
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                      <CircularProgress size={16} sx={{ mr: 1 }} />
                      <Typography variant="body2">{downloadState.message}</Typography>
                    </Box>
                    <LinearProgress
                      variant={downloadState.percent > 0 ? 'determinate' : 'indeterminate'}
                      value={downloadState.percent}
                      sx={{ height: 8, borderRadius: 1 }}
                    />
                  </>
                )}
              </Box>
            )}

            {/* Hint */}
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
              Select a file and click "Download" to save it locally.
              Then use the "Load from Local" tab to load it into the application.
            </Typography>
          </>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button onClick={onClose} disabled={isDownloading}>
          {downloadState.status === 'complete' ? 'Close' : 'Cancel'}
        </Button>
        <Button
          variant="contained"
          startIcon={isDownloading ? <CircularProgress size={18} /> : <SaveAltIcon />}
          onClick={handleDownload}
          disabled={loading || selectedInfo.count !== 1 || isDownloading}
        >
          {isDownloading ? 'Downloading...' : 'Download'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default FileBrowserDialog;
