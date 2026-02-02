import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Button,
  Tooltip,
  Divider,
  Menu,
  Slider,
  Stack,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Link,
  Chip,
} from '@mui/material';
import MemoryIcon from '@mui/icons-material/Memory';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import ContactSupportIcon from '@mui/icons-material/ContactSupport';
import GitHubIcon from '@mui/icons-material/GitHub';
import StorageIcon from '@mui/icons-material/Storage';
import SettingsIcon from '@mui/icons-material/Settings';
import { useUIStore } from '@/store/uiStore';
import { useBackendContext } from '@/App';

const FOOTER_HEIGHT = 40;

/**
 * Application footer with system resources, copyright, and links
 */
const Footer: React.FC = () => {
  const [version, setVersion] = useState<string>('');
  const { systemResources, setSystemResources } = useUIStore();
  const { isReady: backendReady, port: backendPort } = useBackendContext();

  // Resource settings state
  const [resourcesAnchor, setResourcesAnchor] = useState<null | HTMLElement>(null);
  const [maxCpuThreads, setMaxCpuThreads] = useState<number>(4);
  const [maxRamGb, setMaxRamGb] = useState<number>(8);

  // Dialog states
  const [acknowledgementsOpen, setAcknowledgementsOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);

  // Get app version
  useEffect(() => {
    const getVersion = async (): Promise<void> => {
      if (window.electronAPI) {
        const appVersion = await window.electronAPI.getAppVersion();
        setVersion(appVersion);
      }
    };
    getVersion();
  }, []);

  // Resource monitoring state
  const [monitoringActive, setMonitoringActive] = useState<boolean>(false);

  // Fetch system resources from backend
  const fetchResources = async (): Promise<void> => {
    if (!backendReady || !backendPort) return;

    try {
      const response = await fetch(`http://127.0.0.1:${backendPort}/api/status`);
      if (response.ok) {
        const data = await response.json();
        if (data.memory_usage) {
          setSystemResources({
            cpuPercent: data.memory_usage.cpu_percent || 0,
            memoryUsedGb: (data.memory_usage.memory_used_mb || 0) / 1024,
            memoryTotalGb: (data.memory_usage.memory_total_mb || 0) / 1024,
            memoryPercent: data.memory_usage.memory_percent || 0,
          });
        }
      }
    } catch {
      // Backend might not be ready
    }
  };

  // Poll resources only when monitoring is active
  useEffect(() => {
    if (!monitoringActive) return;

    // Initial fetch when monitoring starts
    fetchResources();

    // Poll every 10 seconds
    const interval = setInterval(fetchResources, 10000);
    return () => clearInterval(interval);
  }, [monitoringActive, backendReady, backendPort]);

  // Toggle monitoring on/off
  const handleToggleMonitoring = (): void => {
    if (!monitoringActive) {
      // Starting monitoring - fetch immediately
      fetchResources();
    }
    setMonitoringActive((prev) => !prev);
  };

  const handleOpenExternal = async (url: string): Promise<void> => {
    if (window.electronAPI) {
      await window.electronAPI.openExternal(url);
    }
  };

  const formatResourceDisplay = (): string => {
    if (!systemResources) {
      return 'Resources: --';
    }
    const cpuStr = `CPU: ${systemResources.cpuPercent.toFixed(0)}%`;
    const memStr = `RAM: ${systemResources.memoryUsedGb.toFixed(1)}/${systemResources.memoryTotalGb.toFixed(0)}GB`;
    return `${cpuStr} | ${memStr}`;
  };

  return (
    <>
      <Box
        component="footer"
        sx={{
          minHeight: FOOTER_HEIGHT,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 0.5,
          borderTop: '1px solid',
          borderColor: 'divider',
          backgroundColor: 'background.paper',
          flexShrink: 0,
          gap: 1,
          flexWrap: 'nowrap',
          overflow: 'hidden',
        }}
      >
        {/* Left side - System Resources */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
          <Tooltip title={monitoringActive ? 'Click to stop monitoring (updates every 10s)' : 'Click to start resource monitoring'}>
            <Button
              size="small"
              startIcon={
                <MemoryIcon
                  sx={{
                    fontSize: 16,
                    animation: monitoringActive ? 'pulse 2s infinite' : 'none',
                    '@keyframes pulse': {
                      '0%, 100%': { opacity: 1 },
                      '50%': { opacity: 0.5 },
                    },
                  }}
                />
              }
              onClick={handleToggleMonitoring}
              sx={{
                textTransform: 'none',
                fontSize: '0.75rem',
                color: monitoringActive ? 'primary.main' : 'text.secondary',
                '&:hover': { color: monitoringActive ? 'primary.dark' : 'text.primary' },
                whiteSpace: 'nowrap',
                minWidth: 'auto',
              }}
            >
              {monitoringActive ? formatResourceDisplay() : 'Monitor'}
            </Button>
          </Tooltip>

          <Tooltip title="Configure resource limits">
            <IconButton
              size="small"
              onClick={(e) => setResourcesAnchor(e.currentTarget)}
              sx={{ color: 'text.secondary', p: 0.5 }}
            >
              <SettingsIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Tooltip>

          <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

          {/* Backend status */}
          <Tooltip title={backendReady ? `Backend running on port ${backendPort}` : 'Backend not connected'}>
            <Chip
              icon={<StorageIcon sx={{ fontSize: 14 }} />}
              label={backendReady ? 'Connected' : 'Disconnected'}
              size="small"
              color={backendReady ? 'success' : 'error'}
              variant="outlined"
              sx={{ height: 22, fontSize: '0.7rem' }}
            />
          </Tooltip>
        </Box>

        {/* Center - Copyright */}
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{
            flexShrink: 1,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            minWidth: 0,
          }}
        >
          Stingray Explorer {version && `v${version}`} | © {new Date().getFullYear()} Kartik Mandar
        </Typography>

        {/* Right side - Links */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0 }}>
          <Tooltip title="Acknowledgements">
            <IconButton
              size="small"
              onClick={() => setAcknowledgementsOpen(true)}
              sx={{ color: 'text.secondary' }}
            >
              <InfoOutlinedIcon sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>

          <Tooltip title="Contact & Support">
            <IconButton
              size="small"
              onClick={() => setContactOpen(true)}
              sx={{ color: 'text.secondary' }}
            >
              <ContactSupportIcon sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>

          <Tooltip title="GitHub Repository">
            <IconButton
              size="small"
              onClick={() => handleOpenExternal('https://github.com/kartikmandar-GSOC24/StingrayExplorer')}
              sx={{ color: 'text.secondary' }}
            >
              <GitHubIcon sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>
        </Box>

        {/* Resources Menu */}
        <Menu
          anchorEl={resourcesAnchor}
          open={Boolean(resourcesAnchor)}
          onClose={() => setResourcesAnchor(null)}
          anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
          transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
          PaperProps={{ sx: { width: 320, p: 2 } }}
        >
          <Typography variant="subtitle2" gutterBottom>
            Resource Limits
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
            Configure maximum resources for analysis tasks
          </Typography>

          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" gutterBottom>
                Max CPU Threads: {maxCpuThreads}
              </Typography>
              <Slider
                value={maxCpuThreads}
                onChange={(_, value) => setMaxCpuThreads(value as number)}
                step={1}
                marks
                min={1}
                max={16}
                size="small"
                valueLabelDisplay="auto"
              />
            </Box>

            <Box>
              <Typography variant="body2" gutterBottom>
                Max RAM (GB): {maxRamGb}
              </Typography>
              <Slider
                value={maxRamGb}
                onChange={(_, value) => setMaxRamGb(value as number)}
                step={1}
                marks
                min={1}
                max={32}
                size="small"
                valueLabelDisplay="auto"
              />
            </Box>

            {systemResources && (
              <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                <Typography variant="caption" color="text.secondary">
                  Current usage: {systemResources.cpuPercent.toFixed(1)}% CPU,{' '}
                  {systemResources.memoryPercent.toFixed(1)}% RAM
                </Typography>
              </Box>
            )}
          </Stack>
        </Menu>
      </Box>

      {/* Acknowledgements Dialog */}
      <Dialog
        open={acknowledgementsOpen}
        onClose={() => setAcknowledgementsOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Acknowledgements</DialogTitle>
        <DialogContent>
          <Typography variant="body2" paragraph>
            Stingray Explorer is built on top of the{' '}
            <Link
              component="button"
              onClick={() => handleOpenExternal('https://github.com/StingraySoftware/stingray')}
            >
              Stingray
            </Link>{' '}
            Python library for spectral-timing analysis of astronomical data.
          </Typography>

          <Typography variant="subtitle2" gutterBottom sx={{ mt: 2 }}>
            Core Dependencies
          </Typography>
          <Typography variant="body2" component="div">
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://stingray.readthedocs.io/')}>
                  Stingray
                </Link>{' '}
                - Spectral-timing software
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://www.astropy.org/')}>
                  Astropy
                </Link>{' '}
                - Core astronomy library
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://numpy.org/')}>
                  NumPy
                </Link>{' '}
                & SciPy - Scientific computing
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://fastapi.tiangolo.com/')}>
                  FastAPI
                </Link>{' '}
                - Backend framework
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://www.electronjs.org/')}>
                  Electron
                </Link>{' '}
                - Desktop framework
              </li>
              <li>
                <Link component="button" onClick={() => handleOpenExternal('https://react.dev/')}>
                  React
                </Link>{' '}
                & Material UI - Frontend
              </li>
            </ul>
          </Typography>

          <Typography variant="subtitle2" gutterBottom sx={{ mt: 2 }}>
            Special Thanks
          </Typography>
          <Typography variant="body2">
            This project was developed as part of Google Summer of Code 2024 under the OpenAstronomy
            organization. Special thanks to the Stingray team and mentors for their guidance and support.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAcknowledgementsOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Contact Dialog */}
      <Dialog
        open={contactOpen}
        onClose={() => setContactOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Contact & Support</DialogTitle>
        <DialogContent>
          <Typography variant="body2" paragraph>
            Need help or want to report an issue? Here are the best ways to get in touch:
          </Typography>

          <Stack spacing={2} sx={{ mt: 2 }}>
            <Box>
              <Typography variant="subtitle2">Report Issues</Typography>
              <Typography variant="body2" color="text.secondary">
                Found a bug or have a feature request?{' '}
                <Link
                  component="button"
                  onClick={() => handleOpenExternal('https://github.com/kartikmandar-GSOC24/StingrayExplorer/issues')}
                >
                  Open an issue on GitHub
                </Link>
              </Typography>
            </Box>

            <Box>
              <Typography variant="subtitle2">Documentation</Typography>
              <Typography variant="body2" color="text.secondary">
                Check the{' '}
                <Link
                  component="button"
                  onClick={() => handleOpenExternal('https://docs.stingray.science/')}
                >
                  Stingray documentation
                </Link>{' '}
                for detailed usage guides.
              </Typography>
            </Box>

            <Box>
              <Typography variant="subtitle2">Community</Typography>
              <Typography variant="body2" color="text.secondary">
                Join the discussion on the{' '}
                <Link
                  component="button"
                  onClick={() => handleOpenExternal('https://github.com/StingraySoftware/stingray/discussions')}
                >
                  Stingray GitHub Discussions
                </Link>
              </Typography>
            </Box>

            <Box>
              <Typography variant="subtitle2">Developer</Typography>
              <Typography variant="body2" color="text.secondary">
                Kartik Mandar -{' '}
                <Link
                  component="button"
                  onClick={() => handleOpenExternal('https://github.com/kartikmandar')}
                >
                  @kartikmandar
                </Link>
              </Typography>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setContactOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default Footer;
export { FOOTER_HEIGHT };
