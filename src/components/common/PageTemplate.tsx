import React from 'react';
import { Box, Typography, Paper, Chip, Alert } from '@mui/material';
import ConstructionIcon from '@mui/icons-material/Construction';

interface PageTemplateProps {
  title: string;
  description?: string;
  category?: string;
  status?: 'ready' | 'coming-soon' | 'in-development';
  children?: React.ReactNode;
}

/**
 * Reusable page template component
 */
const PageTemplate: React.FC<PageTemplateProps> = ({
  title,
  description,
  category,
  status = 'coming-soon',
  children,
}) => {
  return (
    <Box className="stagger-reveal">
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        {category && (
          <Chip
            label={category}
            size="small"
            color="primary"
            variant="outlined"
            sx={{
              mb: 1,
              fontFamily: '"JetBrains Mono", monospace',
              fontSize: '0.7rem',
              letterSpacing: '0.04em',
            }}
          />
        )}
        <Typography
          variant="h4"
          gutterBottom
          sx={{
            fontFamily: '"JetBrains Mono", monospace',
            textShadow: (theme) =>
              theme.palette.mode === 'dark'
                ? '0 0 30px rgba(0, 212, 170, 0.08)'
                : 'none',
          }}
        >
          {title}
        </Typography>
        {description && (
          <Typography variant="body1" color="text.secondary">
            {description}
          </Typography>
        )}
      </Box>

      {/* Status indicator for pages under development */}
      {status !== 'ready' && (
        <Alert
          severity={status === 'in-development' ? 'warning' : 'info'}
          icon={<ConstructionIcon />}
          sx={{ mb: 3 }}
        >
          {status === 'in-development'
            ? 'This feature is currently under development.'
            : 'This feature is coming soon in a future release.'}
        </Alert>
      )}

      {/* Page content */}
      {children || (
        <Paper
          variant="outlined"
          sx={{
            p: 4,
            textAlign: 'center',
            backgroundColor: (theme) =>
              theme.palette.mode === 'dark'
                ? 'rgba(18, 24, 41, 0.4)'
                : 'rgba(255, 255, 255, 0.6)',
            backdropFilter: 'blur(8px)',
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          <ConstructionIcon
            sx={{
              fontSize: 64,
              color: 'text.disabled',
              mb: 2,
              animation: 'statusPulse 3s ease-in-out infinite',
            }}
          />
          <Typography
            variant="h6"
            color="text.secondary"
            sx={{ fontFamily: '"JetBrains Mono", monospace' }}
          >
            {title}
          </Typography>
          <Typography variant="body2" color="text.disabled">
            This analysis module will be implemented soon.
          </Typography>
        </Paper>
      )}
    </Box>
  );
};

export default PageTemplate;
