import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('react-plotly.js', () => ({
  default: ({ data, layout }: { data: unknown[]; layout: Record<string, unknown> }) => (
    <div
      data-testid="plotly-mock"
      data-traces={data.length}
      data-xtype={(layout.xaxis as { type?: string })?.type ?? 'linear'}
    />
  ),
}));

import PlotlyChart from './PlotlyChart';

describe('PlotlyChart', () => {
  it('renders traces and merges page layout over theme defaults', async () => {
    render(
      <PlotlyChart
        data={[{ x: [1, 2], y: [3, 4], type: 'scatter' }]}
        layout={{ xaxis: { type: 'log' } }}
      />
    );
    await waitFor(() => expect(screen.getByTestId('plotly-mock')).toBeInTheDocument());
    expect(screen.getByTestId('plotly-mock').dataset.traces).toBe('1');
    expect(screen.getByTestId('plotly-mock').dataset.xtype).toBe('log');
  });
});
