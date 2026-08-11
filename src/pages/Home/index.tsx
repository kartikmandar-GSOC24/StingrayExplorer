import React from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  CardActionArea,
  Grid,
  Chip,
  useTheme,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import AnalyticsIcon from '@mui/icons-material/Analytics';
import BuildIcon from '@mui/icons-material/Build';
import ModelTrainingIcon from '@mui/icons-material/ModelTraining';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import ScienceIcon from '@mui/icons-material/Science';
import UploadFileIcon from '@mui/icons-material/UploadFile';

interface QuickAccessCard {
  title: string;
  description: string;
  icon: React.ReactNode;
  path: string;
  color: string;
  glowColor: string;
}

/**
 * Home page with quick access cards and welcome message
 */
const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const quickAccessCards: QuickAccessCard[] = [
    {
      title: 'Load Data',
      description: 'Import FITS, HDF5, or text files for analysis',
      icon: <UploadFileIcon sx={{ fontSize: 36 }} />,
      path: '/data-ingestion',
      color: '#3b82f6',
      glowColor: 'rgba(59, 130, 246, 0.15)',
    },
    {
      title: 'QuickLook Analysis',
      description: 'Power spectra, cross spectra, light curves, and more',
      icon: <AnalyticsIcon sx={{ fontSize: 36 }} />,
      path: '/quicklook/power-spectrum',
      color: '#00d4aa',
      glowColor: 'rgba(0, 212, 170, 0.15)',
    },
    {
      title: 'Pulsar Analysis',
      description: 'Period search, phase folding, and phaseograms',
      icon: <AccessTimeIcon sx={{ fontSize: 36 }} />,
      path: '/pulsar/search',
      color: '#a855f7',
      glowColor: 'rgba(168, 85, 247, 0.15)',
    },
    {
      title: 'Modeling',
      description: 'Model fitting with MLE and MCMC methods',
      icon: <ModelTrainingIcon sx={{ fontSize: 36 }} />,
      path: '/modeling/builder',
      color: '#f59e0b',
      glowColor: 'rgba(245, 158, 11, 0.15)',
    },
    {
      title: 'Simulator',
      description: 'Generate synthetic light curves and event lists',
      icon: <ScienceIcon sx={{ fontSize: 36 }} />,
      path: '/simulator',
      color: '#ef4444',
      glowColor: 'rgba(239, 68, 68, 0.15)',
    },
    {
      title: 'Utilities',
      description: 'GTI handling, statistics, and I/O tools',
      icon: <BuildIcon sx={{ fontSize: 36 }} />,
      path: '/utilities/gti',
      color: '#64748b',
      glowColor: 'rgba(100, 116, 139, 0.15)',
    },
  ];

  return (
    <Box>
      {/* Welcome hero section */}
      <Box
        sx={{
          position: 'relative',
          p: 5,
          mb: 5,
          borderRadius: 3,
          overflow: 'hidden',
          background: isDark
            ? 'linear-gradient(135deg, #0a0e1a 0%, #121829 40%, #1a2236 100%)'
            : 'linear-gradient(135deg, #f0f2f5 0%, #ffffff 40%, #f8f9fb 100%)',
          border: '1px solid',
          borderColor: isDark ? 'rgba(148, 163, 184, 0.1)' : 'rgba(30, 41, 59, 0.06)',
          // Radial accent overlay
          '&::before': {
            content: '""',
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: isDark
              ? 'radial-gradient(ellipse at 85% 15%, rgba(0, 212, 170, 0.08), transparent 55%), radial-gradient(ellipse at 10% 80%, rgba(59, 130, 246, 0.05), transparent 50%)'
              : 'radial-gradient(ellipse at 85% 15%, rgba(13, 155, 122, 0.06), transparent 55%), radial-gradient(ellipse at 10% 80%, rgba(37, 99, 235, 0.04), transparent 50%)',
            pointerEvents: 'none',
          },
          // Starfield dots (dark mode only)
          '&::after': isDark
            ? {
                content: '""',
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                backgroundImage: `
                  radial-gradient(1px 1px at 10% 20%, rgba(255,255,255,0.3), transparent),
                  radial-gradient(1px 1px at 30% 60%, rgba(255,255,255,0.2), transparent),
                  radial-gradient(1.5px 1.5px at 50% 10%, rgba(255,255,255,0.35), transparent),
                  radial-gradient(1px 1px at 70% 40%, rgba(255,255,255,0.2), transparent),
                  radial-gradient(1px 1px at 85% 75%, rgba(255,255,255,0.25), transparent),
                  radial-gradient(1.5px 1.5px at 95% 30%, rgba(255,255,255,0.3), transparent),
                  radial-gradient(1px 1px at 15% 90%, rgba(255,255,255,0.15), transparent),
                  radial-gradient(1px 1px at 60% 85%, rgba(255,255,255,0.2), transparent),
                  radial-gradient(1px 1px at 40% 35%, rgba(255,255,255,0.15), transparent),
                  radial-gradient(1.5px 1.5px at 25% 45%, rgba(0, 212, 170, 0.3), transparent),
                  radial-gradient(1px 1px at 78% 12%, rgba(59, 130, 246, 0.25), transparent)
                `,
                pointerEvents: 'none',
                animation: 'starTwinkle 8s ease-in-out infinite alternate',
              }
            : {},
        }}
      >
        <Box sx={{ position: 'relative', zIndex: 1 }} className="stagger-reveal">
          <Typography
            variant="h3"
            gutterBottom
            sx={{
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 700,
              letterSpacing: '-0.02em',
              color: 'text.primary',
              textShadow: isDark ? '0 0 40px rgba(0, 212, 170, 0.12)' : 'none',
            }}
          >
            Welcome to Stingray Explorer
          </Typography>
          <Typography
            variant="h6"
            sx={{
              color: 'primary.main',
              fontStyle: 'italic',
              mb: 2,
              fontWeight: 400,
            }}
          >
            Next-Generation Spectral Timing Made Easy
          </Typography>
          <Typography
            variant="body1"
            sx={{
              color: 'text.secondary',
              maxWidth: 720,
              lineHeight: 1.7,
            }}
          >
            A comprehensive data analysis and visualization dashboard for X-ray astronomy
            time series data. Built on top of the Stingray library, it provides an intuitive
            graphical interface for analyzing event lists, generating light curves, computing
            various types of spectra, and performing advanced timing analysis.
          </Typography>
          <Box sx={{ mt: 3, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {['Stingray 2.0+', 'X-ray Astronomy', 'Time Series Analysis'].map((label) => (
              <Chip
                key={label}
                label={label}
                size="small"
                sx={{
                  fontFamily: '"JetBrains Mono", monospace',
                  fontSize: '0.7rem',
                  fontWeight: 500,
                  letterSpacing: '0.02em',
                  backgroundColor: isDark
                    ? 'rgba(0, 212, 170, 0.08)'
                    : 'rgba(13, 155, 122, 0.08)',
                  color: 'primary.main',
                  border: '1px solid',
                  borderColor: isDark
                    ? 'rgba(0, 212, 170, 0.2)'
                    : 'rgba(13, 155, 122, 0.2)',
                }}
              />
            ))}
          </Box>
        </Box>
      </Box>

      {/* Quick Access heading */}
      <Box sx={{ mb: 3, position: 'relative' }}>
        <Typography
          variant="h5"
          sx={{
            fontFamily: '"JetBrains Mono", monospace',
            fontWeight: 600,
            letterSpacing: '-0.01em',
          }}
        >
          Quick Access
        </Typography>
        <Box
          sx={{
            mt: 1,
            width: 48,
            height: 2,
            borderRadius: 1,
            background: isDark
              ? 'linear-gradient(to right, #00d4aa, #3b82f6)'
              : 'linear-gradient(to right, #0d9b7a, #2563eb)',
          }}
        />
      </Box>

      {/* Quick Access Cards */}
      <Grid container spacing={3} className="stagger-reveal">
        {quickAccessCards.map((card) => (
          <Grid item xs={12} sm={6} md={4} key={card.title}>
            <Card
              elevation={0}
              sx={{
                height: '100%',
                transition: 'all 0.3s cubic-bezier(0.22, 0.61, 0.36, 1)',
                '&:hover': {
                  transform: 'translateY(-6px)',
                  borderColor: `${card.color} !important`,
                  boxShadow: isDark
                    ? `0 0 24px ${card.glowColor}, 0 12px 40px rgba(0, 0, 0, 0.4)`
                    : `0 4px 24px ${card.glowColor}, 0 8px 32px rgba(0, 0, 0, 0.06)`,
                  '& .card-icon': {
                    filter: isDark ? `drop-shadow(0 0 8px ${card.glowColor})` : 'none',
                    transform: 'scale(1.1)',
                  },
                },
              }}
            >
              <CardActionArea
                onClick={() => navigate(card.path)}
                sx={{ height: '100%', p: 1 }}
              >
                <CardContent>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 2,
                      mb: 2,
                    }}
                  >
                    <Box
                      className="card-icon"
                      sx={{
                        color: card.color,
                        transition: 'filter 0.3s ease, transform 0.3s ease',
                      }}
                    >
                      {card.icon}
                    </Box>
                    <Typography
                      variant="h6"
                      sx={{
                        fontFamily: '"JetBrains Mono", monospace',
                        fontWeight: 500,
                        fontSize: '1rem',
                      }}
                    >
                      {card.title}
                    </Typography>
                  </Box>
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.5 }}>
                    {card.description}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};

export default HomePage;
