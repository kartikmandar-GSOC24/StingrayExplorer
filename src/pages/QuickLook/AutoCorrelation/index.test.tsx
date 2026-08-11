import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const autoCorrelation = vi.fn();
vi.mock('@/api/correlationApi', () => ({
  correlationApi: {
    autoCorrelation: (...a: unknown[]) => autoCorrelation(...a),
  },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import AutoCorrelationPage from './index';

describe('AutoCorrelationPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    autoCorrelation.mockResolvedValue({
      success: true,
      data: {
        time_lags: [-0.1, 0, 0.1],
        corr: [2.0, 10.0, 2.0],
        time_shift: 0,
        dt: 0.1,
        n: 3,
        mode: 'same',
        norm: 'none',
        warnings: [],
      },
      message: 'done',
      error: null,
    });
  });

  it('computes an auto-correlation with parsed parameters and plots it', async () => {
    renderWithProviders(<AutoCorrelationPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    const dtField = screen.getByLabelText(/Time bin/);
    await userEvent.clear(dtField);
    await userEvent.type(dtField, '0.05');
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    await waitFor(() =>
      expect(autoCorrelation).toHaveBeenCalledWith(
        expect.objectContaining({ event_list_name: 'obs1', dt: 0.05, mode: 'same', norm: 'none' })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
  });

  it('disables Compute until inputs are valid', async () => {
    renderWithProviders(<AutoCorrelationPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });

  it('renders warnings from the result when present', async () => {
    autoCorrelation.mockResolvedValue({
      success: true,
      data: {
        time_lags: [-0.1, 0, 0.1],
        corr: [null, 10.0, null],
        time_shift: 0,
        dt: 0.1,
        n: 3,
        mode: 'same',
        norm: 'variance',
        warnings: ['The correlation contains NaN values.'],
      },
      message: 'done',
      error: null,
    });
    renderWithProviders(<AutoCorrelationPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    const dtField = screen.getByLabelText(/Time bin/);
    await userEvent.clear(dtField);
    await userEvent.type(dtField, '0.05');
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    expect(await screen.findByText(/The correlation contains NaN values\./)).toBeInTheDocument();
  });
});
