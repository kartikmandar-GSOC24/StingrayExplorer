import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const crossCorrelation = vi.fn();
vi.mock('@/api/correlationApi', () => ({
  correlationApi: {
    crossCorrelation: (...a: unknown[]) => crossCorrelation(...a),
  },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import CrossCorrelationPage from './index';

async function selectEventList(label: string, name: string): Promise<void> {
  await userEvent.click(await screen.findByLabelText(label));
  await userEvent.click(await screen.findAllByText(new RegExp(name)).then((els) => els[els.length - 1]));
}

describe('CrossCorrelationPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockResolvedValue({
      success: true,
      data: [
        { name: 'obs1', n_events: 5000, time_range: [0, 100] },
        { name: 'obs2', n_events: 4000, time_range: [0, 100] },
      ],
      message: '',
      error: null,
    });
    crossCorrelation.mockResolvedValue({
      success: true,
      data: {
        time_lags: [-0.5, 0, 0.5],
        corr: [2.0, 10.0, 2.0],
        time_shift: -0.5,
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

  it('computes a cross-correlation with parsed parameters, plots it, and shows the time-shift chip', async () => {
    renderWithProviders(<CrossCorrelationPage />);
    await selectEventList('Event list 1', 'obs1');
    await selectEventList('Event list 2', 'obs2');
    const dtField = screen.getByLabelText(/Time bin/);
    await userEvent.clear(dtField);
    await userEvent.type(dtField, '0.1');
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    await waitFor(() =>
      expect(crossCorrelation).toHaveBeenCalledWith(
        expect.objectContaining({
          event_list_1_name: 'obs1',
          event_list_2_name: 'obs2',
          dt: 0.1,
          mode: 'same',
          norm: 'none',
        })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
    expect(await screen.findByText(/time shift: -0.5000 s/)).toBeInTheDocument();
    expect(
      screen.getByText(/Positive shift means the first list lags the second\./)
    ).toBeInTheDocument();
  });

  it('disables Compute until inputs are valid', async () => {
    renderWithProviders(<CrossCorrelationPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });

  it('omits the time-shift chip and renders warnings when time_shift is null', async () => {
    crossCorrelation.mockResolvedValue({
      success: true,
      data: {
        time_lags: [-0.1, 0, 0.1],
        corr: [null, 10.0, null],
        time_shift: null,
        dt: 0.1,
        n: 3,
        mode: 'same',
        norm: 'variance',
        warnings: ['The correlation contains NaN values.'],
      },
      message: 'done',
      error: null,
    });
    renderWithProviders(<CrossCorrelationPage />);
    await selectEventList('Event list 1', 'obs1');
    await selectEventList('Event list 2', 'obs2');
    const dtField = screen.getByLabelText(/Time bin/);
    await userEvent.clear(dtField);
    await userEvent.type(dtField, '0.1');
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    expect(await screen.findByText(/The correlation contains NaN values\./)).toBeInTheDocument();
    expect(screen.queryByText(/time shift:/)).not.toBeInTheDocument();
  });
});
