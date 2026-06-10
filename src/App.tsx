import React, { useState, useEffect, createContext, useContext, useMemo } from 'react';
import { RouterProvider, createHashRouter } from 'react-router-dom';
import { ThemeProvider as MuiThemeProvider, createTheme, Theme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// MUI Palette augmentation for stingrayGreen
declare module '@mui/material/styles' {
  interface Palette {
    stingrayGreen: Palette['primary'];
  }
  interface PaletteOptions {
    stingrayGreen?: PaletteOptions['primary'];
  }
}

// Layout
import MainLayout from '@/components/layout/MainLayout';

// Pages
import HomePage from '@/pages/Home';
import DataIngestionPage from '@/pages/DataIngestion';
import NotFoundPage from '@/pages/NotFound';

// QuickLook Pages
import EventListPage from '@/pages/QuickLook/EventList';
import LightCurvePage from '@/pages/QuickLook/LightCurve';
import PowerSpectrumPage from '@/pages/QuickLook/PowerSpectrum';
import AvgPowerSpectrumPage from '@/pages/QuickLook/AvgPowerSpectrum';
import CrossSpectrumPage from '@/pages/QuickLook/CrossSpectrum';
import AvgCrossSpectrumPage from '@/pages/QuickLook/AvgCrossSpectrum';
import DynamicalPowerSpectrumPage from '@/pages/QuickLook/DynamicalPowerSpectrum';
import CoherencePage from '@/pages/QuickLook/Coherence';
import TimeLagsPage from '@/pages/QuickLook/TimeLags';
import CrossCorrelationPage from '@/pages/QuickLook/CrossCorrelation';
import AutoCorrelationPage from '@/pages/QuickLook/AutoCorrelation';
import DeadTimeCorrectionsPage from '@/pages/QuickLook/DeadTimeCorrections';
import BispectrumPage from '@/pages/QuickLook/Bispectrum';
import CovarianceSpectrumPage from '@/pages/QuickLook/CovarianceSpectrum';
import AvgCovarianceSpectrumPage from '@/pages/QuickLook/AvgCovarianceSpectrum';
import VariableEnergySpectrumPage from '@/pages/QuickLook/VariableEnergySpectrum';
import RmsEnergySpectrumPage from '@/pages/QuickLook/RmsEnergySpectrum';
import LagEnergySpectrumPage from '@/pages/QuickLook/LagEnergySpectrum';
import ExcessVarianceSpectrumPage from '@/pages/QuickLook/ExcessVarianceSpectrum';

// Utilities Pages
import StatisticalFunctionsPage from '@/pages/Utilities/StatisticalFunctions';
import GTIPage from '@/pages/Utilities/GTI';
import IOPage from '@/pages/Utilities/IO';
import MissionIOPage from '@/pages/Utilities/MissionIO';
import MiscPage from '@/pages/Utilities/Misc';

// Modeling Pages
import ModelBuilderPage from '@/pages/Modeling/ModelBuilder';
import MLEFittingPage from '@/pages/Modeling/MLEFitting';
import MCMCFittingPage from '@/pages/Modeling/MCMCFitting';

// Pulsar Pages
import PeriodSearchPage from '@/pages/Pulsar/PeriodSearch';
import PhaseFoldingPage from '@/pages/Pulsar/PhaseFolding';
import PhaseogramPage from '@/pages/Pulsar/Phaseogram';

// Simulator Page
import SimulatorPage from '@/pages/Simulator';

// Hooks
import { useJobStream } from '@/hooks/useJobStream';

// Theme Context
interface ThemeContextType {
  darkMode: boolean;
  toggleDarkMode: () => void;
}

export const ThemeContext = createContext<ThemeContextType>({
  darkMode: false,
  toggleDarkMode: () => {},
});

export const useThemeContext = (): ThemeContextType => useContext(ThemeContext);

// Backend Context
interface BackendContextType {
  port: number | null;
  isReady: boolean;
  error: string | null;
}

export const BackendContext = createContext<BackendContextType>({
  port: null,
  isReady: false,
  error: null,
});

export const useBackendContext = (): BackendContextType => useContext(BackendContext);

// Create React Query client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 1,
    },
  },
});

// ─── Shared typography ────────────────────────────────────────────────────────
const fontDisplay = '"JetBrains Mono", "Fira Code", "Source Code Pro", monospace';
const fontBody = '"IBM Plex Sans", "Source Sans 3", -apple-system, sans-serif';

const sharedTypography = {
  fontFamily: fontBody,
  h1: { fontFamily: fontDisplay, fontWeight: 700, letterSpacing: '-0.02em' },
  h2: { fontFamily: fontDisplay, fontWeight: 700, letterSpacing: '-0.01em' },
  h3: { fontFamily: fontDisplay, fontWeight: 600, letterSpacing: '-0.01em' },
  h4: { fontFamily: fontDisplay, fontWeight: 600, letterSpacing: '0' },
  h5: { fontFamily: fontDisplay, fontWeight: 500, letterSpacing: '0' },
  h6: { fontFamily: fontDisplay, fontWeight: 500, letterSpacing: '0.01em' },
  subtitle1: { fontFamily: fontBody, fontWeight: 500 },
  subtitle2: { fontFamily: fontBody, fontWeight: 500 },
  body1: { fontFamily: fontBody, fontWeight: 400, lineHeight: 1.6 },
  body2: { fontFamily: fontBody, fontWeight: 400, lineHeight: 1.5 },
  button: { fontFamily: fontBody, fontWeight: 600, letterSpacing: '0.02em', textTransform: 'none' as const },
  caption: { fontFamily: fontBody, fontWeight: 400 },
  overline: { fontFamily: fontDisplay, fontWeight: 500, letterSpacing: '0.1em', textTransform: 'uppercase' as const },
};

const sharedShape = { borderRadius: 8 };

// ─── Dark theme (primary / default) ──────────────────────────────────────────
const createDarkTheme = (): Theme =>
  createTheme({
    palette: {
      mode: 'dark',
      primary: { main: '#00d4aa', light: '#33e0be', dark: '#00a885', contrastText: '#0a0e1a' },
      secondary: { main: '#3b82f6', light: '#60a5fa', dark: '#2563eb', contrastText: '#ffffff' },
      stingrayGreen: { main: '#5ead61', light: '#8edf91', dark: '#3d7a40', contrastText: '#ffffff' },
      background: { default: '#0a0e1a', paper: '#121829' },
      text: { primary: '#e2e8f0', secondary: '#94a3b8', disabled: '#475569' },
      divider: 'rgba(148, 163, 184, 0.12)',
      success: { main: '#22c55e', light: '#4ade80', dark: '#16a34a' },
      warning: { main: '#f59e0b', light: '#fbbf24', dark: '#d97706' },
      error: { main: '#ef4444', light: '#f87171', dark: '#dc2626' },
      info: { main: '#3b82f6', light: '#60a5fa', dark: '#2563eb' },
    },
    typography: sharedTypography,
    shape: sharedShape,
    transitions: {
      easing: { easeInOut: 'cubic-bezier(0.22, 0.61, 0.36, 1)' },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            transition: 'background-color 0.3s cubic-bezier(0.22, 0.61, 0.36, 1)',
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            transition: 'background-color 0.2s ease, box-shadow 0.2s ease',
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            background: 'rgba(18, 24, 41, 0.6)',
            backdropFilter: 'blur(12px) saturate(150%)',
            WebkitBackdropFilter: 'blur(12px) saturate(150%)',
            border: '1px solid rgba(148, 163, 184, 0.12)',
            transition: 'border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s cubic-bezier(0.22, 0.61, 0.36, 1)',
            '&:hover': {
              borderColor: 'rgba(0, 212, 170, 0.3)',
              boxShadow: '0 0 20px rgba(0, 212, 170, 0.1), 0 8px 32px rgba(0, 0, 0, 0.3)',
            },
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            transition: 'all 0.2s ease',
          },
          contained: {
            boxShadow: '0 2px 8px rgba(0, 212, 170, 0.15)',
            '&:hover': {
              boxShadow: '0 4px 20px rgba(0, 212, 170, 0.25), 0 0 40px rgba(0, 212, 170, 0.1)',
            },
          },
          outlined: {
            borderColor: 'rgba(148, 163, 184, 0.2)',
            '&:hover': {
              borderColor: '#00d4aa',
              boxShadow: '0 0 12px rgba(0, 212, 170, 0.15)',
            },
          },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: {
            transition: 'all 0.2s ease',
            '&:hover': {
              backgroundColor: 'rgba(0, 212, 170, 0.08)',
              boxShadow: '0 0 12px rgba(0, 212, 170, 0.12)',
            },
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            fontFamily: fontBody,
            fontWeight: 500,
          },
          outlined: {
            borderColor: 'rgba(148, 163, 184, 0.2)',
          },
          filled: {
            backgroundColor: 'rgba(0, 212, 170, 0.12)',
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              transition: 'box-shadow 0.2s ease',
              '&.Mui-focused': {
                boxShadow: '0 0 0 3px rgba(0, 212, 170, 0.12)',
              },
            },
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundImage: 'none',
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            background: 'rgba(18, 24, 41, 0.85)',
            backdropFilter: 'blur(16px) saturate(150%)',
            WebkitBackdropFilter: 'blur(16px) saturate(150%)',
            border: '1px solid rgba(148, 163, 184, 0.12)',
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            fontFamily: fontBody,
            fontSize: '0.75rem',
            backgroundColor: 'rgba(18, 24, 41, 0.9)',
            backdropFilter: 'blur(8px)',
            border: '1px solid rgba(148, 163, 184, 0.12)',
          },
        },
      },
      MuiAlert: {
        styleOverrides: {
          root: {
            backdropFilter: 'blur(8px)',
            border: '1px solid',
          },
          standardSuccess: {
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            borderColor: 'rgba(34, 197, 94, 0.2)',
          },
          standardWarning: {
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            borderColor: 'rgba(245, 158, 11, 0.2)',
          },
          standardError: {
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            borderColor: 'rgba(239, 68, 68, 0.2)',
          },
          standardInfo: {
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderColor: 'rgba(59, 130, 246, 0.2)',
          },
        },
      },
      MuiDivider: {
        styleOverrides: {
          root: {
            borderColor: 'rgba(148, 163, 184, 0.08)',
          },
        },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 6,
            margin: '1px 6px',
            transition: 'all 0.2s ease',
            '&:hover': {
              backgroundColor: 'rgba(0, 212, 170, 0.06)',
            },
            '&.Mui-selected': {
              backgroundColor: 'rgba(0, 212, 170, 0.1)',
              '&:hover': {
                backgroundColor: 'rgba(0, 212, 170, 0.14)',
              },
            },
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            fontFamily: fontBody,
            fontWeight: 500,
            textTransform: 'none',
          },
        },
      },
      MuiTableHead: {
        styleOverrides: {
          root: {
            '& .MuiTableCell-head': {
              fontFamily: fontDisplay,
              fontWeight: 500,
              fontSize: '0.75rem',
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              backgroundColor: 'rgba(0, 212, 170, 0.04)',
              borderBottom: '1px solid rgba(148, 163, 184, 0.12)',
            },
          },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: {
            borderBottom: '1px solid rgba(148, 163, 184, 0.06)',
          },
        },
      },
      MuiLinearProgress: {
        styleOverrides: {
          root: {
            borderRadius: 4,
            backgroundColor: 'rgba(0, 212, 170, 0.08)',
          },
        },
      },
      MuiMenu: {
        styleOverrides: {
          paper: {
            background: 'rgba(18, 24, 41, 0.9)',
            backdropFilter: 'blur(12px) saturate(150%)',
            WebkitBackdropFilter: 'blur(12px) saturate(150%)',
            border: '1px solid rgba(148, 163, 184, 0.12)',
          },
        },
      },
      MuiPopover: {
        styleOverrides: {
          paper: {
            background: 'rgba(18, 24, 41, 0.9)',
            backdropFilter: 'blur(12px) saturate(150%)',
            WebkitBackdropFilter: 'blur(12px) saturate(150%)',
            border: '1px solid rgba(148, 163, 184, 0.12)',
          },
        },
      },
    },
  });

// ─── Light theme (refined Observatory Light) ─────────────────────────────────
const createLightTheme = (): Theme =>
  createTheme({
    palette: {
      mode: 'light',
      primary: { main: '#0d9b7a', light: '#00d4aa', dark: '#087a60', contrastText: '#ffffff' },
      secondary: { main: '#2563eb', light: '#3b82f6', dark: '#1d4ed8', contrastText: '#ffffff' },
      stingrayGreen: { main: '#4a9a4d', light: '#5ead61', dark: '#2e7d32', contrastText: '#ffffff' },
      background: { default: '#f0f2f5', paper: '#ffffff' },
      text: { primary: '#1e293b', secondary: '#64748b', disabled: '#94a3b8' },
      divider: 'rgba(30, 41, 59, 0.12)',
      success: { main: '#16a34a', light: '#22c55e', dark: '#15803d' },
      warning: { main: '#d97706', light: '#f59e0b', dark: '#b45309' },
      error: { main: '#dc2626', light: '#ef4444', dark: '#b91c1c' },
      info: { main: '#2563eb', light: '#3b82f6', dark: '#1d4ed8' },
    },
    typography: sharedTypography,
    shape: sharedShape,
    transitions: {
      easing: { easeInOut: 'cubic-bezier(0.22, 0.61, 0.36, 1)' },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            transition: 'background-color 0.3s cubic-bezier(0.22, 0.61, 0.36, 1)',
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            transition: 'background-color 0.2s ease, box-shadow 0.2s ease',
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            background: 'rgba(255, 255, 255, 0.7)',
            backdropFilter: 'blur(12px) saturate(150%)',
            WebkitBackdropFilter: 'blur(12px) saturate(150%)',
            border: '1px solid rgba(30, 41, 59, 0.08)',
            transition: 'border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s cubic-bezier(0.22, 0.61, 0.36, 1)',
            '&:hover': {
              borderColor: 'rgba(13, 155, 122, 0.3)',
              boxShadow: '0 4px 24px rgba(13, 155, 122, 0.08), 0 8px 32px rgba(0, 0, 0, 0.06)',
            },
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            transition: 'all 0.2s ease',
          },
          contained: {
            boxShadow: '0 2px 8px rgba(13, 155, 122, 0.15)',
            '&:hover': {
              boxShadow: '0 4px 20px rgba(13, 155, 122, 0.2)',
            },
          },
          outlined: {
            borderColor: 'rgba(30, 41, 59, 0.2)',
            '&:hover': {
              borderColor: '#0d9b7a',
              boxShadow: '0 0 12px rgba(13, 155, 122, 0.1)',
            },
          },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: {
            transition: 'all 0.2s ease',
            '&:hover': {
              backgroundColor: 'rgba(13, 155, 122, 0.08)',
            },
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            fontFamily: fontBody,
            fontWeight: 500,
          },
          outlined: {
            borderColor: 'rgba(30, 41, 59, 0.2)',
          },
          filled: {
            backgroundColor: 'rgba(13, 155, 122, 0.1)',
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              transition: 'box-shadow 0.2s ease',
              '&.Mui-focused': {
                boxShadow: '0 0 0 3px rgba(13, 155, 122, 0.1)',
              },
            },
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundImage: 'none',
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            background: 'rgba(255, 255, 255, 0.9)',
            backdropFilter: 'blur(16px) saturate(150%)',
            WebkitBackdropFilter: 'blur(16px) saturate(150%)',
            border: '1px solid rgba(30, 41, 59, 0.08)',
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            fontFamily: fontBody,
            fontSize: '0.75rem',
            backgroundColor: 'rgba(30, 41, 59, 0.9)',
            border: '1px solid rgba(30, 41, 59, 0.12)',
          },
        },
      },
      MuiAlert: {
        styleOverrides: {
          root: {
            border: '1px solid',
          },
          standardSuccess: {
            backgroundColor: 'rgba(22, 163, 74, 0.08)',
            borderColor: 'rgba(22, 163, 74, 0.2)',
          },
          standardWarning: {
            backgroundColor: 'rgba(217, 119, 6, 0.08)',
            borderColor: 'rgba(217, 119, 6, 0.2)',
          },
          standardError: {
            backgroundColor: 'rgba(220, 38, 38, 0.08)',
            borderColor: 'rgba(220, 38, 38, 0.2)',
          },
          standardInfo: {
            backgroundColor: 'rgba(37, 99, 235, 0.08)',
            borderColor: 'rgba(37, 99, 235, 0.2)',
          },
        },
      },
      MuiDivider: {
        styleOverrides: {
          root: {
            borderColor: 'rgba(30, 41, 59, 0.08)',
          },
        },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 6,
            margin: '1px 6px',
            transition: 'all 0.2s ease',
            '&:hover': {
              backgroundColor: 'rgba(13, 155, 122, 0.06)',
            },
            '&.Mui-selected': {
              backgroundColor: 'rgba(13, 155, 122, 0.1)',
              '&:hover': {
                backgroundColor: 'rgba(13, 155, 122, 0.14)',
              },
            },
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            fontFamily: fontBody,
            fontWeight: 500,
            textTransform: 'none',
          },
        },
      },
      MuiTableHead: {
        styleOverrides: {
          root: {
            '& .MuiTableCell-head': {
              fontFamily: fontDisplay,
              fontWeight: 500,
              fontSize: '0.75rem',
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              backgroundColor: 'rgba(13, 155, 122, 0.04)',
              borderBottom: '1px solid rgba(30, 41, 59, 0.12)',
            },
          },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: {
            borderBottom: '1px solid rgba(30, 41, 59, 0.06)',
          },
        },
      },
      MuiLinearProgress: {
        styleOverrides: {
          root: {
            borderRadius: 4,
            backgroundColor: 'rgba(13, 155, 122, 0.08)',
          },
        },
      },
      MuiMenu: {
        styleOverrides: {
          paper: {
            background: 'rgba(255, 255, 255, 0.95)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            border: '1px solid rgba(30, 41, 59, 0.08)',
          },
        },
      },
      MuiPopover: {
        styleOverrides: {
          paper: {
            background: 'rgba(255, 255, 255, 0.95)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            border: '1px solid rgba(30, 41, 59, 0.08)',
          },
        },
      },
    },
  });

// Router configuration
const router = createHashRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'data-ingestion', element: <DataIngestionPage /> },

      // QuickLook routes
      { path: 'quicklook/event-list', element: <EventListPage /> },
      { path: 'quicklook/light-curve', element: <LightCurvePage /> },
      { path: 'quicklook/power-spectrum', element: <PowerSpectrumPage /> },
      { path: 'quicklook/avg-power-spectrum', element: <AvgPowerSpectrumPage /> },
      { path: 'quicklook/cross-spectrum', element: <CrossSpectrumPage /> },
      { path: 'quicklook/avg-cross-spectrum', element: <AvgCrossSpectrumPage /> },
      { path: 'quicklook/dynamical-power-spectrum', element: <DynamicalPowerSpectrumPage /> },
      { path: 'quicklook/coherence', element: <CoherencePage /> },
      { path: 'quicklook/time-lags', element: <TimeLagsPage /> },
      { path: 'quicklook/cross-correlation', element: <CrossCorrelationPage /> },
      { path: 'quicklook/auto-correlation', element: <AutoCorrelationPage /> },
      { path: 'quicklook/dead-time-corrections', element: <DeadTimeCorrectionsPage /> },
      { path: 'quicklook/bispectrum', element: <BispectrumPage /> },
      { path: 'quicklook/covariance-spectrum', element: <CovarianceSpectrumPage /> },
      { path: 'quicklook/avg-covariance-spectrum', element: <AvgCovarianceSpectrumPage /> },
      { path: 'quicklook/variable-energy-spectrum', element: <VariableEnergySpectrumPage /> },
      { path: 'quicklook/rms-energy-spectrum', element: <RmsEnergySpectrumPage /> },
      { path: 'quicklook/lag-energy-spectrum', element: <LagEnergySpectrumPage /> },
      { path: 'quicklook/excess-variance-spectrum', element: <ExcessVarianceSpectrumPage /> },

      // Utilities routes
      { path: 'utilities/statistical-functions', element: <StatisticalFunctionsPage /> },
      { path: 'utilities/gti', element: <GTIPage /> },
      { path: 'utilities/io', element: <IOPage /> },
      { path: 'utilities/mission-io', element: <MissionIOPage /> },
      { path: 'utilities/misc', element: <MiscPage /> },

      // Modeling routes
      { path: 'modeling/builder', element: <ModelBuilderPage /> },
      { path: 'modeling/mle', element: <MLEFittingPage /> },
      { path: 'modeling/mcmc', element: <MCMCFittingPage /> },

      // Pulsar routes
      { path: 'pulsar/search', element: <PeriodSearchPage /> },
      { path: 'pulsar/folding', element: <PhaseFoldingPage /> },
      { path: 'pulsar/phaseogram', element: <PhaseogramPage /> },

      // Simulator
      { path: 'simulator', element: <SimulatorPage /> },

      // 404
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]);

/**
 * Component that initializes the job stream SSE connection.
 * Must be inside BackendContext.Provider to access backend state.
 */
const JobStreamInitializer: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  useJobStream();
  return <>{children}</>;
};

// Main App Component
const App: React.FC = () => {
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    const saved = localStorage.getItem('darkMode');
    return saved !== null ? JSON.parse(saved) : true;
  });

  const [backendState, setBackendState] = useState<BackendContextType>({
    port: null,
    isReady: false,
    error: null,
  });

  // Toggle dark mode
  const toggleDarkMode = (): void => {
    setDarkMode((prev) => {
      const newValue = !prev;
      localStorage.setItem('darkMode', JSON.stringify(newValue));
      return newValue;
    });
  };

  // Theme memoization
  const theme = useMemo(() => (darkMode ? createDarkTheme() : createLightTheme()), [darkMode]);

  // Listen for Python backend events
  useEffect(() => {
    if (typeof window !== 'undefined' && window.electronAPI) {
      const unsubscribeReady = window.electronAPI.onPythonReady((port) => {
        setBackendState({ port, isReady: true, error: null });
      });

      const unsubscribeError = window.electronAPI.onPythonError((error) => {
        setBackendState((prev) => ({ ...prev, error }));
      });

      const unsubscribeStarting = window.electronAPI.onPythonStarting(() => {
        setBackendState({ port: null, isReady: false, error: null });
      });

      // Check if already ready
      window.electronAPI.getBackendPort().then((port) => {
        if (port) {
          window.electronAPI.isPythonRunning().then((isRunning) => {
            if (isRunning) {
              setBackendState({ port, isReady: true, error: null });
            }
          });
        }
      });

      return () => {
        unsubscribeReady();
        unsubscribeError();
        unsubscribeStarting();
      };
    }
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeContext.Provider value={{ darkMode, toggleDarkMode }}>
        <BackendContext.Provider value={backendState}>
          <MuiThemeProvider theme={theme}>
            <CssBaseline />
            <JobStreamInitializer>
              <RouterProvider router={router} />
            </JobStreamInitializer>
          </MuiThemeProvider>
        </BackendContext.Provider>
      </ThemeContext.Provider>
    </QueryClientProvider>
  );
};

export default App;
