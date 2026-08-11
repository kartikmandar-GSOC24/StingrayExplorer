import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const rmsSpectrum = vi.fn();
vi.mock('@/api/varenergyApi', () => ({
  varenergyApi: { rmsSpectrum: (...a: unknown[]) => rmsSpectrum(...a) },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import RmsEnergySpectrumPage from './index';

describe('RmsEnergySpectrumPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    rmsSpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [1, 2, 3, 4, 5],
        spectrum: [0.4, 0.35, 0.3, 0.28, 0.25],
        spectrum_error: [0.02, 0.02, 0.02, 0.03, 0.03],
        freq_range: [0.1, 1],
        norm: 'frac',
        n_segments_hint: 8,
        warnings: [],
      },
      message: 'done',
      error: null,
    });
  });

  it('computes the rms spectrum with the parsed default parameters', async () => {
    renderWithProviders(<RmsEnergySpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));

    await waitFor(() =>
      expect(rmsSpectrum).toHaveBeenCalledWith(
        expect.objectContaining({
          event_list_name: 'obs1',
          bin_time: 0.1,
          segment_size: 8,
          freq_min: 0.1,
          freq_max: 1,
          energy_min: 0.5,
          energy_max: 10,
          n_bands: 5,
          log_bands: false,
          norm: 'frac',
        })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
  });

  it('disables Compute until an event list is selected', async () => {
    renderWithProviders(<RmsEnergySpectrumPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });
});
