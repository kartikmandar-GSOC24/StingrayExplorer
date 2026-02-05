import React, { useState, useEffect, createContext, useContext, useMemo } from 'react';
import { RouterProvider, createHashRouter } from 'react-router-dom';
import { ThemeProvider as MuiThemeProvider, createTheme, Theme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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

// Light theme
const createLightTheme = (): Theme =>
  createTheme({
    palette: {
      mode: 'light',
      primary: {
        main: '#5ead61', // Stingray green
        light: '#8edf91',
        dark: '#2e7d32',
      },
      secondary: {
        main: '#1976d2',
        light: '#42a5f5',
        dark: '#1565c0',
      },
      background: {
        default: '#f5f5f5',
        paper: '#ffffff',
      },
    },
    typography: {
      fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            transition: 'background-color 0.3s ease',
          },
        },
      },
    },
  });

// Dark theme
const createDarkTheme = (): Theme =>
  createTheme({
    palette: {
      mode: 'dark',
      primary: {
        main: '#81c784', // Lighter green for dark mode
        light: '#b2fab4',
        dark: '#519657',
      },
      secondary: {
        main: '#64b5f6',
        light: '#90caf9',
        dark: '#1976d2',
      },
      background: {
        default: '#121212',
        paper: '#1e1e1e',
      },
    },
    typography: {
      fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            transition: 'background-color 0.3s ease',
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
    return saved ? JSON.parse(saved) : false;
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
