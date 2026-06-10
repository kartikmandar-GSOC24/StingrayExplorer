import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('react-plotly.js', () => ({
  default: ({ data, layout }: { data: unknown[]; layout: Record<string, unknown> }) => (
    <div
      data-testid="plotly-mock"
      data-traces={data.length}
      data-xtype={(layout.xaxis as { type?: string })?.type ?? 'linear'}
      data-ytype={(layout.yaxis as { type?: string })?.type ?? 'linear'}
      data-xgrid={(layout.xaxis as { gridcolor?: string })?.gridcolor ?? ''}
    />
  ),
}));

import PlotlyChart from './PlotlyChart';

describe('PlotlyChart', () => {
  it('renders traces and merges page layout over theme defaults', async () => {
    render(
      <PlotlyChart
        data={[{ x: [1, 2], y: [3, 4], type: 'scatter' }]}
        layout={{ xaxis: { type: 'log' }, yaxis: { type: 'log' } }}
      />
    );
    await waitFor(() => expect(screen.getByTestId('plotly-mock')).toBeInTheDocument());
    expect(screen.getByTestId('plotly-mock').dataset.traces).toBe('1');
    expect(screen.getByTestId('plotly-mock').dataset.xtype).toBe('log');
    expect(screen.getByTestId('plotly-mock').dataset.ytype).toBe('log');
    expect(screen.getByTestId('plotly-mock').dataset.xgrid).not.toBe('');
  });
});
