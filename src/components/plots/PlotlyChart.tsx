import React, { Suspense } from 'react';
import { Box, CircularProgress, useTheme } from '@mui/material';
import type { Config, Data, Layout } from 'plotly.js';

// plotly.js is ~3 MB; load it only when a page actually renders a chart.
const Plot = React.lazy(() => import('react-plotly.js'));

export interface PlotlyChartProps {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number | string;
}

const PlotlyChart: React.FC<PlotlyChartProps> = ({ data, layout = {}, height = 440 }) => {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  const gridColor = isDark ? 'rgba(148, 163, 184, 0.12)' : 'rgba(100, 116, 139, 0.2)';

  const mergedLayout: Partial<Layout> = {
    autosize: true,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family: '"IBM Plex Sans", sans-serif',
      size: 12,
      color: theme.palette.text.primary,
    },
    margin: { l: 64, r: 24, t: 24, b: 52 },
    showlegend: false,
    ...layout,
    xaxis: { gridcolor: gridColor, zeroline: false, ...layout.xaxis },
    yaxis: { gridcolor: gridColor, zeroline: false, ...layout.yaxis },
  };

  const config: Partial<Config> = {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
  };

  return (
    <Suspense
      fallback={
        <Box sx={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <CircularProgress size={28} />
        </Box>
      }
    >
      <Plot
        data={data}
        layout={mergedLayout}
        config={config}
        useResizeHandler
        style={{ width: '100%', height }}
      />
    </Suspense>
  );
};

export default PlotlyChart;
