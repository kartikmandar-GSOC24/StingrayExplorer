import React, { useState, useEffect, useContext } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Box,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
  IconButton,
} from '@mui/material';
import HomeIcon from '@mui/icons-material/Home';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import AnalyticsIcon from '@mui/icons-material/Analytics';
import BuildIcon from '@mui/icons-material/Build';
import ModelTrainingIcon from '@mui/icons-material/ModelTraining';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import ScienceIcon from '@mui/icons-material/Science';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import CloseIcon from '@mui/icons-material/Close';
import { ThemeContext } from '../../App';
import JobStatusPanel from './JobStatusPanel';

// Sidebar widths
const MAIN_DRAWER_WIDTH = 240;
const SUB_DRAWER_WIDTH = 240;

interface SidebarProps {
  open: boolean;
  onSubmenuStateChange: (isOpen: boolean) => void;
}

interface SubmenuItem {
  text: string;
  path: string;
}

interface MenuItem {
  text: string;
  icon: React.ReactNode;
  path: string;
  hasSubmenu?: boolean;
  submenuItems?: SubmenuItem[];
}

/**
 * Sidebar navigation component with VAST-style categorized submenu
 */
const Sidebar: React.FC<SidebarProps> = ({ open, onSubmenuStateChange }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { darkMode } = useContext(ThemeContext);
  const [activeSubmenu, setActiveSubmenu] = useState<string | null>(null);
  const [showSubmenu, setShowSubmenu] = useState<boolean>(true);

  // Notify parent of submenu state changes
  useEffect(() => {
    onSubmenuStateChange(!!activeSubmenu && showSubmenu);
  }, [activeSubmenu, showSubmenu, onSubmenuStateChange]);

  // Navigation items configuration
  const menuItems: MenuItem[] = [
    {
      text: 'Home',
      icon: <HomeIcon />,
      path: '/',
    },
    {
      text: 'Data Ingestion',
      icon: <UploadFileIcon />,
      path: '/data-ingestion',
    },
    {
      text: 'QuickLook Analysis',
      icon: <AnalyticsIcon />,
      path: '/quicklook',
      hasSubmenu: true,
      submenuItems: [
        { text: 'Event List', path: '/quicklook/event-list' },
        { text: 'Light Curve', path: '/quicklook/light-curve' },
        { text: 'Power Spectrum', path: '/quicklook/power-spectrum' },
        { text: 'Avg Power Spectrum', path: '/quicklook/avg-power-spectrum' },
        { text: 'Cross Spectrum', path: '/quicklook/cross-spectrum' },
        { text: 'Avg Cross Spectrum', path: '/quicklook/avg-cross-spectrum' },
        { text: 'Dynamical Power Spectrum', path: '/quicklook/dynamical-power-spectrum' },
        { text: 'Coherence', path: '/quicklook/coherence' },
        { text: 'Time Lags', path: '/quicklook/time-lags' },
        { text: 'Cross Correlation', path: '/quicklook/cross-correlation' },
        { text: 'Auto Correlation', path: '/quicklook/auto-correlation' },
        { text: 'Dead Time Corrections', path: '/quicklook/dead-time-corrections' },
        { text: 'Bispectrum', path: '/quicklook/bispectrum' },
        { text: 'Covariance Spectrum', path: '/quicklook/covariance-spectrum' },
        { text: 'Avg Covariance Spectrum', path: '/quicklook/avg-covariance-spectrum' },
        { text: 'Variable Energy Spectrum', path: '/quicklook/variable-energy-spectrum' },
        { text: 'RMS Energy Spectrum', path: '/quicklook/rms-energy-spectrum' },
        { text: 'Lag Energy Spectrum', path: '/quicklook/lag-energy-spectrum' },
        { text: 'Excess Variance Spectrum', path: '/quicklook/excess-variance-spectrum' },
      ],
    },
    {
      text: 'Utilities',
      icon: <BuildIcon />,
      path: '/utilities',
      hasSubmenu: true,
      submenuItems: [
        { text: 'Statistical Functions', path: '/utilities/statistical-functions' },
        { text: 'GTI Functionality', path: '/utilities/gti' },
        { text: 'I/O Functionality', path: '/utilities/io' },
        { text: 'Mission Specific I/O', path: '/utilities/mission-io' },
        { text: 'Misc', path: '/utilities/misc' },
      ],
    },
    {
      text: 'Modeling',
      icon: <ModelTrainingIcon />,
      path: '/modeling',
      hasSubmenu: true,
      submenuItems: [
        { text: 'Model Builder', path: '/modeling/builder' },
        { text: 'MLE Fitting', path: '/modeling/mle' },
        { text: 'MCMC Fitting', path: '/modeling/mcmc' },
      ],
    },
    {
      text: 'Pulsar',
      icon: <AccessTimeIcon />,
      path: '/pulsar',
      hasSubmenu: true,
      submenuItems: [
        { text: 'Period Search', path: '/pulsar/search' },
        { text: 'Phase Folding', path: '/pulsar/folding' },
        { text: 'Phaseogram', path: '/pulsar/phaseogram' },
      ],
    },
    {
      text: 'Simulator',
      icon: <ScienceIcon />,
      path: '/simulator',
    },
  ];

  const getActiveMenuItem = (): MenuItem | undefined => {
    return menuItems.find((item) => item.text === activeSubmenu);
  };

  const handleMenuClick = (item: MenuItem): void => {
    if (item.hasSubmenu) {
      setActiveSubmenu(item.text);
      setShowSubmenu(true);
    } else {
      setActiveSubmenu(null);
      setShowSubmenu(false);
      navigate(item.path);
    }
  };

  // Categorization for QuickLook submenu
  const quicklookCategories: Record<string, string[]> = {
    'Time Domain': ['Event List', 'Light Curve'],
    'Frequency Domain': [
      'Power Spectrum',
      'Avg Power Spectrum',
      'Cross Spectrum',
      'Avg Cross Spectrum',
      'Dynamical Power Spectrum',
      'Coherence',
      'Time Lags',
    ],
    'Correlation Analysis': ['Cross Correlation', 'Auto Correlation'],
    'Advanced Analysis': [
      'Dead Time Corrections',
      'Bispectrum',
      'Covariance Spectrum',
      'Avg Covariance Spectrum',
    ],
    'Energy Dependent Analysis': [
      'Variable Energy Spectrum',
      'RMS Energy Spectrum',
      'Lag Energy Spectrum',
      'Excess Variance Spectrum',
    ],
  };

  // Active item styling
  const getItemSx = (isActive: boolean) => ({
    pl: 2,
    position: 'relative' as const,
    '&::before': isActive
      ? {
          content: '""',
          position: 'absolute',
          left: 0,
          top: '20%',
          bottom: '20%',
          width: '3px',
          borderRadius: '0 2px 2px 0',
          backgroundColor: 'primary.main',
          boxShadow: darkMode
            ? '0 0 8px rgba(0, 212, 170, 0.4), 0 0 16px rgba(0, 212, 170, 0.15)'
            : '0 0 6px rgba(13, 155, 122, 0.3)',
        }
      : {},
    backgroundColor: isActive
      ? darkMode
        ? 'rgba(0, 212, 170, 0.08)'
        : 'rgba(13, 155, 122, 0.08)'
      : 'transparent',
    '&:hover': {
      backgroundColor: darkMode
        ? 'rgba(0, 212, 170, 0.06)'
        : 'rgba(13, 155, 122, 0.06)',
    },
  });

  const renderMainMenu = (): React.ReactNode => (
    <List sx={{ py: 1 }}>
      {menuItems.map((item) => {
        const isActive = !item.hasSubmenu && location.pathname === item.path;
        return (
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              onClick={() => handleMenuClick(item)}
              selected={isActive}
              sx={getItemSx(isActive)}
            >
              <ListItemIcon
                sx={{
                  color: isActive ? 'primary.main' : 'text.secondary',
                  minWidth: 40,
                  transition: 'color 0.2s ease',
                  filter: isActive && darkMode ? 'drop-shadow(0 0 4px rgba(0, 212, 170, 0.3))' : 'none',
                }}
              >
                {item.icon}
              </ListItemIcon>
              <ListItemText
                primary={item.text}
                primaryTypographyProps={{
                  fontSize: '0.875rem',
                  fontWeight: isActive ? 600 : 400,
                }}
              />
              {item.hasSubmenu && (
                <ChevronRightIcon sx={{ color: 'text.secondary', fontSize: 18 }} />
              )}
            </ListItemButton>
          </ListItem>
        );
      })}
    </List>
  );

  const renderSubmenu = (): React.ReactNode => {
    const activeItem = getActiveMenuItem();
    if (!activeItem?.submenuItems) return null;

    // Determine if we should use categories (only for QuickLook)
    const useCategories = activeItem.text === 'QuickLook Analysis';
    const categories = useCategories ? quicklookCategories : null;

    return (
      <>
        {/* Submenu header */}
        <Box
          sx={{
            p: 2,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid',
            borderColor: 'divider',
            position: 'relative',
            '&::after': {
              content: '""',
              position: 'absolute',
              bottom: 0,
              left: 0,
              right: 0,
              height: '1px',
              background: darkMode
                ? 'linear-gradient(to right, rgba(0, 212, 170, 0.3), transparent)'
                : 'linear-gradient(to right, rgba(13, 155, 122, 0.3), transparent)',
            },
          }}
        >
          <Typography
            variant="subtitle2"
            sx={{
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 600,
              letterSpacing: '0.02em',
              fontSize: '0.8rem',
            }}
          >
            {activeItem.text}
          </Typography>
          <IconButton size="small" onClick={() => setShowSubmenu(false)} sx={{ ml: 1 }}>
            <CloseIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Box>

        {/* Categorized or flat list */}
        {categories ? (
          // Categorized rendering for QuickLook
          Object.entries(categories).map(([category, items]) => (
            <React.Fragment key={category}>
              <Typography
                variant="overline"
                sx={{
                  display: 'block',
                  px: 2,
                  pt: 1.5,
                  pb: 0.5,
                  fontFamily: '"JetBrains Mono", monospace',
                  fontWeight: 500,
                  fontSize: '0.65rem',
                  letterSpacing: '0.08em',
                  color: 'text.secondary',
                  borderTop: '1px solid',
                  borderColor: darkMode
                    ? 'rgba(148, 163, 184, 0.06)'
                    : 'rgba(30, 41, 59, 0.06)',
                }}
              >
                {category}
              </Typography>
              <List dense disablePadding>
                {activeItem.submenuItems
                  ?.filter((subItem) => items.includes(subItem.text))
                  .map((subItem) => {
                    const isActive = location.pathname === subItem.path;
                    return (
                      <ListItem key={subItem.text} disablePadding>
                        <ListItemButton
                          onClick={() => navigate(subItem.path)}
                          selected={isActive}
                          sx={getItemSx(isActive)}
                        >
                          <ListItemText
                            primary={subItem.text}
                            primaryTypographyProps={{
                              fontSize: '0.8rem',
                              fontWeight: isActive ? 600 : 400,
                            }}
                          />
                        </ListItemButton>
                      </ListItem>
                    );
                  })}
              </List>
            </React.Fragment>
          ))
        ) : (
          // Flat list for other menus
          <List dense sx={{ py: 0.5 }}>
            {activeItem.submenuItems?.map((subItem) => {
              const isActive = location.pathname === subItem.path;
              return (
                <ListItem key={subItem.text} disablePadding>
                  <ListItemButton
                    onClick={() => navigate(subItem.path)}
                    selected={isActive}
                    sx={getItemSx(isActive)}
                  >
                    <ListItemText
                      primary={subItem.text}
                      primaryTypographyProps={{
                        fontSize: '0.85rem',
                        fontWeight: isActive ? 600 : 400,
                      }}
                    />
                  </ListItemButton>
                </ListItem>
              );
            })}
          </List>
        )}
      </>
    );
  };

  // Scrollbar styles
  const scrollbarStyles = {
    overflow: 'auto',
    height: '100%',
    '&::-webkit-scrollbar': {
      width: '4px',
      backgroundColor: 'transparent',
    },
    '&::-webkit-scrollbar-thumb': {
      backgroundColor: darkMode ? 'rgba(0, 212, 170, 0.2)' : 'rgba(13, 155, 122, 0.15)',
      borderRadius: '4px',
      '&:hover': {
        backgroundColor: darkMode ? 'rgba(0, 212, 170, 0.35)' : 'rgba(13, 155, 122, 0.3)',
      },
    },
    '&::-webkit-scrollbar-track': {
      backgroundColor: 'transparent',
    },
  };

  // Sidebar background — slightly darker than paper for depth
  const sidebarBg = darkMode ? '#0d1220' : '#f8f9fb';

  return (
    <>
      {/* Main Sidebar */}
      <Box
        sx={{
          position: 'fixed',
          top: '64px',
          left: 0,
          height: 'calc(100vh - 64px)',
          overflow: 'hidden',
          transition: 'width 225ms cubic-bezier(0.22, 0.61, 0.36, 1)',
          display: 'flex',
          flexDirection: 'column',
          borderRight: '1px solid',
          borderColor: 'divider',
          width: open ? MAIN_DRAWER_WIDTH : 0,
          backgroundColor: sidebarBg,
          zIndex: (theme) => theme.zIndex.drawer,
        }}
      >
        {/* Menu items - scrollable */}
        <Box
          sx={{
            ...scrollbarStyles,
            flex: 1,
            opacity: open ? 1 : 0,
            transition: 'opacity 150ms',
            minWidth: MAIN_DRAWER_WIDTH,
          }}
        >
          {renderMainMenu()}
        </Box>

        {/* Job Status Panel - fixed at bottom */}
        <JobStatusPanel sidebarOpen={open} />
      </Box>

      {/* Submenu Sidebar */}
      <Box
        sx={{
          position: 'fixed',
          top: '64px',
          left: open ? MAIN_DRAWER_WIDTH : 0,
          height: 'calc(100vh - 64px)',
          overflow: 'hidden',
          transition: 'all 225ms cubic-bezier(0.22, 0.61, 0.36, 1)',
          display: 'flex',
          flexDirection: 'column',
          borderRight: '1px solid',
          borderColor: 'divider',
          width: open && !!activeSubmenu && showSubmenu ? SUB_DRAWER_WIDTH : 0,
          backgroundColor: darkMode ? '#101726' : '#ffffff',
          zIndex: (theme) => theme.zIndex.drawer,
        }}
      >
        <Box
          sx={{
            ...scrollbarStyles,
            opacity: open && !!activeSubmenu && showSubmenu ? 1 : 0,
            transition: 'opacity 150ms',
            minWidth: SUB_DRAWER_WIDTH,
          }}
        >
          {renderSubmenu()}
        </Box>
      </Box>
    </>
  );
};

export default Sidebar;
