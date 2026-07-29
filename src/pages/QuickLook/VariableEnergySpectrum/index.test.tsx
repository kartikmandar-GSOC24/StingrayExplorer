import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const variableEnergySpectrum = vi.fn();
vi.mock('@/api/varenergyApi', () => ({
  varenergyApi: {
    variableEnergySpectrum: (...a: unknown[]) => variableEnergySpectrum(...a),
  },
}));
vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import VariableEnergySpectrumPage from './index';

describe('VariableEnergySpectrumPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockReset();
    variableEnergySpectrum.mockReset();
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    variableEnergySpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [1, 2, 3, 4, 5],
        counts: { spectrum: [100, 90, 80, 70, 60], error: [10, 9, 8, 7, 6] },
        rms: { spectrum: [0.1, 0.12, 0.15, 0.13, 0.11], error: [0.01, 0.01, 0.01, 0.01, 0.01] },
        lag: { spectrum: [0, 0.01, -0.01, 0.02, -0.02], error: [0.005, 0.005, 0.005, 0.005, 0.005] },
        freq_range: [0.1, 1],
        ref_band: null,
        norm: 'frac',
        n_segments_hint: 4,
        warnings: [],
      },
      message: 'done',
      error: null,
    });
  });

  it('computes the variable-energy spectrum with parsed parameters and plots three panels', async () => {
    renderWithProviders(<VariableEnergySpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));

    await waitFor(() =>
      expect(variableEnergySpectrum).toHaveBeenCalledWith(
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
        })
      )
    );

    const charts = await screen.findAllByTestId('chart');
    expect(charts).toHaveLength(3);
    expect(screen.getByText('The reference band affects only the lag panel.')).toBeInTheDocument();
  });

  it('disables Compute until an event list is selected', async () => {
    renderWithProviders(<VariableEnergySpectrumPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });
});
