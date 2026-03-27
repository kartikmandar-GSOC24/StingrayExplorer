import React from 'react';
import { Box, Typography, Button } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import HomeIcon from '@mui/icons-material/Home';

const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        textAlign: 'center',
      }}
      className="stagger-reveal"
    >
      <Typography
        variant="h1"
        color="primary"
        sx={{
          fontFamily: '"JetBrains Mono", monospace',
          fontWeight: 700,
          mb: 2,
          textShadow: (theme) =>
            theme.palette.mode === 'dark'
              ? '0 0 40px rgba(0, 212, 170, 0.2)'
              : 'none',
        }}
      >
        404
      </Typography>
      <Typography variant="h5" color="text.secondary" sx={{ mb: 4 }}>
        Page not found
      </Typography>
      <Button
        variant="contained"
        startIcon={<HomeIcon />}
        onClick={() => navigate('/')}
      >
        Go to Home
      </Button>
    </Box>
  );
};

export default NotFoundPage;
