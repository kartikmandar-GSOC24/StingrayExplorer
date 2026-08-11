import React, { Suspense, useMemo } from 'react';
import { Box, CircularProgress, useTheme } from '@mui/material';
import type { Config, Data, Layout } from 'plotly.js';

// plotly.js is ~3 MB; load it only when a page actually renders a chart.
const Plot = React.lazy(() => import('react-plotly.js'));

export interface PlotlyChartProps {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number | string;
}

const PLOT_CONFIG: Partial<Config> = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
};

// Plotly's gl traces request their context with failIfMajorPerformanceCaveat,
// so a renderer stuck in software compositing (e.g. after a GPU-process
// failure) refuses them and plotly renders "WebGL is not supported by your
// browser" into the plot div. Probe with the same flag once per session and
// transparently fall back to SVG scatter when gl isn't genuinely available.
let webglSupport: boolean | null = null;

function webglAvailable(): boolean {
  if (webglSupport === null) {
    try {
      const canvas = document.createElement('canvas');
      webglSupport = !!canvas.getContext('webgl', { failIfMajorPerformanceCaveat: true });
    } catch {
      webglSupport = false;
    }
  }
  return webglSupport;
}

const PlotlyChart: React.FC<PlotlyChartProps> = ({ data, layout = {}, height = 440 }) => {
  const displayData = useMemo<Data[]>(() => {
    if (webglAvailable()) return data;
    return data.map((trace) =>
      (trace as { type?: string }).type === 'scattergl'
        ? ({ ...trace, type: 'scatter' } as Data)
        : trace
    );
  }, [data]);

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

  return (
    <Suspense
      fallback={
        <Box sx={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <CircularProgress size={28} />
        </Box>
      }
    >
      <Plot
        data={displayData}
        layout={mergedLayout}
        config={PLOT_CONFIG}
        useResizeHandler
        style={{ width: '100%', height }}
      />
    </Suspense>
  );
};

export default PlotlyChart;
