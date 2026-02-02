import React, { useState, useCallback } from 'react';
import { Outlet } from 'react-router-dom';
import { Box, Toolbar } from '@mui/material';
import Sidebar from './Sidebar';
import Header from './Header';
import Footer, { FOOTER_HEIGHT } from './Footer';
import RightToolbar, { TOOLBAR_WIDTH } from './RightToolbar';
import LogPanel from '@/components/common/LogPanel';
import NotificationToast from '@/components/common/NotificationToast';
import { useUIStore } from '@/store/uiStore';

// Sidebar widths
const MAIN_DRAWER_WIDTH = 240;
const SUB_DRAWER_WIDTH = 240;

/**
 * Main layout component that wraps all pages
 * Includes sidebar, header, footer, right toolbar, and main content area
 */
const MainLayout: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);
  const [submenuOpen, setSubmenuOpen] = useState<boolean>(false);
  const { rightToolbarCollapsed, toggleRightToolbar } = useUIStore();

  const handleToggleSidebar = useCallback((): void => {
    setSidebarOpen((prev) => !prev);
  }, []);

  const handleSubmenuStateChange = useCallback((isOpen: boolean): void => {
    setSubmenuOpen(isOpen);
  }, []);

  // Calculate main content offset based on sidebar state
  const leftOffset = sidebarOpen
    ? submenuOpen
      ? MAIN_DRAWER_WIDTH + SUB_DRAWER_WIDTH
      : MAIN_DRAWER_WIDTH
    : 0;

  // Calculate right offset based on right toolbar state
  const rightOffset = rightToolbarCollapsed ? 0 : TOOLBAR_WIDTH;

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <Header
        onToggleSidebar={handleToggleSidebar}
        sidebarOpen={sidebarOpen}
        onToggleRightToolbar={toggleRightToolbar}
        rightToolbarOpen={!rightToolbarCollapsed}
      />

      {/* Toolbar spacer to account for fixed header */}
      <Toolbar />

      {/* Main content area with sidebars */}
      <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left Sidebar */}
        <Sidebar open={sidebarOpen} onSubmenuStateChange={handleSubmenuStateChange} />

        {/* Main content */}
        <Box
          component="main"
          sx={{
            flexGrow: 1,
            transition: (theme) =>
              theme.transitions.create(['margin-left', 'margin-right'], {
                easing: theme.transitions.easing.easeInOut,
                duration: theme.transitions.duration.standard,
              }),
            marginLeft: `${leftOffset}px`,
            marginRight: `${rightOffset}px`,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            backgroundColor: 'background.default',
          }}
        >
          {/* Page content */}
          <Box
            sx={{
              flex: 1,
              overflow: 'auto',
              p: 3,
              pb: `${FOOTER_HEIGHT + 40 + 16}px`, // Extra padding for footer + LogPanel header
            }}
          >
            <Outlet />
          </Box>

          {/* Footer - fixed above the LogPanel */}
          <Box
            sx={{
              position: 'fixed',
              bottom: 40, // Height of LogPanel collapsed header
              left: `${leftOffset}px`,
              right: `${rightOffset}px`,
              transition: (theme) =>
                theme.transitions.create(['left', 'right'], {
                  easing: theme.transitions.easing.easeInOut,
                  duration: theme.transitions.duration.standard,
                }),
              zIndex: 1100,
            }}
          >
            <Footer />
          </Box>
        </Box>

        {/* Right Toolbar */}
        <RightToolbar visible={!rightToolbarCollapsed} />
      </Box>

      {/* Log Panel - above footer */}
      <LogPanel />

      {/* Toast notifications - auto-popup for new notifications */}
      <NotificationToast />
    </Box>
  );
};

export default MainLayout;
