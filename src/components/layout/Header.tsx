import React, { useContext, useEffect, useState } from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Box,
  Tooltip,
  Chip,
  InputBase,
  Paper,
  Fade,
  ClickAwayListener,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import MenuOpenIcon from '@mui/icons-material/MenuOpen';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import RefreshIcon from '@mui/icons-material/Refresh';
import SettingsIcon from '@mui/icons-material/Settings';
import SearchIcon from '@mui/icons-material/Search';
import CloseIcon from '@mui/icons-material/Close';
import CircleIcon from '@mui/icons-material/Circle';
import ViewSidebarIcon from '@mui/icons-material/ViewSidebar';
import { ThemeContext, useBackendContext } from '../../App';
import { useUIStore } from '@/store/uiStore';

interface HeaderProps {
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
  onToggleRightToolbar: () => void;
  rightToolbarOpen: boolean;
}

/**
 * Application header with navigation controls and status indicators
 */
const Header: React.FC<HeaderProps> = ({
  onToggleSidebar,
  sidebarOpen,
  onToggleRightToolbar,
  rightToolbarOpen,
}) => {
  const { darkMode, toggleDarkMode } = useContext(ThemeContext);
  const { isReady, error } = useBackendContext();
  const { searchOpen, searchQuery, setSearchOpen, setSearchQuery } = useUIStore();

  const [localSearchQuery, setLocalSearchQuery] = useState('');

  // With titleBarStyle: 'hiddenInset' macOS draws the traffic lights over the
  // web content, so the toolbar must reserve space for them on darwin only.
  const [isMac, setIsMac] = useState(false);
  useEffect(() => {
    let mounted = true;
    void window.electronAPI?.getPlatform().then((platform) => {
      if (mounted) setIsMac(platform === 'darwin');
    });
    return () => {
      mounted = false;
    };
  }, []);

  const handleRestartBackend = async (): Promise<void> => {
    if (window.electronAPI) {
      await window.electronAPI.restartPython();
    }
  };

  const handleSearchOpen = (): void => {
    setSearchOpen(true);
    setLocalSearchQuery(searchQuery);
  };

  const handleSearchClose = (): void => {
    setSearchOpen(false);
    setLocalSearchQuery('');
  };

  const handleSearchSubmit = (e: React.FormEvent): void => {
    e.preventDefault();
    setSearchQuery(localSearchQuery);
    // TODO: Implement actual search functionality
    console.log('Search query:', localSearchQuery);
  };

  return (
    <AppBar
      position="fixed"
      elevation={0}
      sx={{
        zIndex: (theme) => theme.zIndex.drawer + 1,
        backgroundColor: (theme) =>
          theme.palette.mode === 'dark'
            ? 'rgba(10, 14, 26, 0.8)'
            : 'rgba(255, 255, 255, 0.8)',
        backdropFilter: 'blur(12px) saturate(150%)',
        WebkitBackdropFilter: 'blur(12px) saturate(150%)',
        borderBottom: '1px solid',
        borderColor: 'divider',
        '&::after': {
          content: '""',
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: '1px',
          background: (theme) =>
            theme.palette.mode === 'dark'
              ? 'linear-gradient(to right, #00d4aa, #3b82f6, transparent)'
              : 'linear-gradient(to right, #0d9b7a, #2563eb, transparent)',
          opacity: 0.4,
        },
      }}
    >
      {/* The whole bar is a window drag region; interactive children opt out. */}
      <Toolbar className="titlebar-drag-region">
        {/* Spacer clearing the macOS traffic lights (drawn over the content by
            titleBarStyle hiddenInset; position pinned in electron/main.ts to
            x:16, ~52px wide -> ends ~68px). A real element, not Toolbar
            padding: sx padding loses the cascade against MuiToolbar-gutters'
            media rule. 96px + 24px gutter - 12px edge offset = controls at 108. */}
        {isMac && <Box aria-hidden sx={{ width: 96, flexShrink: 0 }} />}
        {/* Left sidebar toggle */}
        <IconButton
          edge="start"
          color="inherit"
          aria-label="toggle sidebar"
          onClick={onToggleSidebar}
          className="titlebar-no-drag"
          sx={{ mr: 2, color: 'text.primary' }}
        >
          {sidebarOpen ? <MenuOpenIcon /> : <MenuIcon />}
        </IconButton>

        {/* Logo and title */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <img
            src="/assets/images/stingray_explorer.png"
            alt="Stingray Explorer"
            style={{ width: 32, height: 32 }}
          />
          <Typography
            variant="h6"
            noWrap
            component="div"
            sx={{
              color: 'text.primary',
              fontWeight: 600,
              fontFamily: '"JetBrains Mono", monospace',
              letterSpacing: '-0.5px',
              textShadow: (theme) =>
                theme.palette.mode === 'dark'
                  ? '0 0 20px rgba(0, 212, 170, 0.15)'
                  : 'none',
            }}
          >
            Stingray Explorer
          </Typography>
        </Box>

        {/* Subtitle */}
        <Typography
          variant="caption"
          sx={{
            ml: 2,
            color: 'text.secondary',
            fontStyle: 'italic',
            display: { xs: 'none', md: 'block' },
          }}
        >
          Next-Generation Spectral Timing Made Easy
        </Typography>

        {/* Spacer */}
        <Box sx={{ flexGrow: 1 }} />

        {/* Search bar */}
        {searchOpen ? (
          <ClickAwayListener onClickAway={handleSearchClose}>
            <Fade in={searchOpen}>
              <Paper
                component="form"
                onSubmit={handleSearchSubmit}
                className="titlebar-no-drag"
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  width: 300,
                  height: 36,
                  px: 1.5,
                  mr: 2,
                  backgroundColor: (theme) =>
                    theme.palette.mode === 'dark'
                      ? 'rgba(18, 24, 41, 0.6)'
                      : 'rgba(240, 242, 245, 0.8)',
                  backdropFilter: 'blur(8px)',
                  border: '1px solid',
                  borderColor: 'divider',
                  transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
                  '&:focus-within': {
                    borderColor: 'primary.main',
                    boxShadow: (theme) =>
                      `0 0 0 3px ${theme.palette.mode === 'dark' ? 'rgba(0, 212, 170, 0.12)' : 'rgba(13, 155, 122, 0.1)'}`,
                  },
                }}
                elevation={0}
              >
                <SearchIcon sx={{ color: 'text.secondary', mr: 1, fontSize: 18 }} />
                <InputBase
                  placeholder="Search pages, features..."
                  value={localSearchQuery}
                  onChange={(e) => setLocalSearchQuery(e.target.value)}
                  autoFocus
                  sx={{ flex: 1, fontSize: '0.8rem', fontFamily: '"IBM Plex Sans", sans-serif' }}
                />
                <IconButton size="small" onClick={handleSearchClose} sx={{ p: 0.5 }}>
                  <CloseIcon sx={{ fontSize: 16 }} />
                </IconButton>
              </Paper>
            </Fade>
          </ClickAwayListener>
        ) : (
          <Tooltip title="Search (Ctrl+K)">
            <IconButton
              color="inherit"
              onClick={handleSearchOpen}
              className="titlebar-no-drag"
              sx={{ color: 'text.secondary', mr: 1 }}
            >
              <SearchIcon />
            </IconButton>
          </Tooltip>
        )}

        {/* Backend status indicator */}
        <Tooltip title={isReady ? 'Python backend running' : error || 'Backend not ready'}>
          <Chip
            icon={
              <CircleIcon
                sx={{
                  fontSize: 10,
                  color: isReady ? '#22c55e' : error ? '#ef4444' : '#f59e0b',
                  animation: isReady ? 'glowPulse 3s ease-in-out infinite' : 'none',
                  filter: isReady ? 'drop-shadow(0 0 4px rgba(34, 197, 94, 0.5))' : 'none',
                }}
              />
            }
            label={isReady ? 'Backend Ready' : error ? 'Error' : 'Starting...'}
            size="small"
            variant="outlined"
            color={isReady ? 'success' : error ? 'error' : 'warning'}
            sx={{
              mr: 2,
              fontFamily: '"IBM Plex Sans", sans-serif',
              fontSize: '0.7rem',
              fontWeight: 500,
              backgroundColor: (theme) =>
                theme.palette.mode === 'dark'
                  ? 'rgba(18, 24, 41, 0.5)'
                  : 'rgba(240, 242, 245, 0.5)',
              backdropFilter: 'blur(4px)',
            }}
          />
        </Tooltip>

        {/* Action buttons */}
        <Box className="titlebar-no-drag" sx={{ display: 'flex', gap: 0.5 }}>
          {/* Restart backend */}
          <Tooltip title="Restart Python backend">
            <IconButton
              color="inherit"
              onClick={handleRestartBackend}
              sx={{ color: 'text.secondary' }}
            >
              <RefreshIcon />
            </IconButton>
          </Tooltip>

          {/* Dark mode toggle */}
          <Tooltip title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}>
            <IconButton
              color="inherit"
              onClick={toggleDarkMode}
              sx={{ color: 'text.secondary' }}
            >
              {darkMode ? <Brightness7Icon /> : <Brightness4Icon />}
            </IconButton>
          </Tooltip>

          {/* Settings */}
          <Tooltip title="Settings">
            <IconButton color="inherit" sx={{ color: 'text.secondary' }}>
              <SettingsIcon />
            </IconButton>
          </Tooltip>
        </Box>

        {/* Right toolbar toggle - rightmost */}
        <Tooltip title={rightToolbarOpen ? 'Hide toolbar' : 'Show toolbar'}>
          <IconButton
            edge="end"
            color="inherit"
            aria-label="toggle right toolbar"
            onClick={onToggleRightToolbar}
            className="titlebar-no-drag"
            sx={{
              ml: 2,
              color: rightToolbarOpen ? 'primary.main' : 'text.primary',
            }}
          >
            <ViewSidebarIcon sx={{ transform: 'scaleX(-1)' }} />
          </IconButton>
        </Tooltip>
      </Toolbar>
    </AppBar>
  );
};

export default Header;
