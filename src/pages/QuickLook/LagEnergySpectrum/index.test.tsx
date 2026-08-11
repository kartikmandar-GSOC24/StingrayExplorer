import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const lagSpectrum = vi.fn();
vi.mock('@/api/varenergyApi', () => ({
  varenergyApi: { lagSpectrum: (...a: unknown[]) => lagSpectrum(...a) },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import LagEnergySpectrumPage from './index';

describe('LagEnergySpectrumPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    lagSpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [1, 2, 3, 4, 5],
        spectrum: [-0.01, -0.005, 0, 0.004, 0.01],
        spectrum_error: [0.002, 0.002, 0.002, 0.003, 0.003],
        freq_range: [0.1, 1],
        ref_band: null,
        n_segments_hint: 8,
        warnings: [],
      },
      message: 'done',
      error: null,
    });
  });

  it('computes the lag spectrum with the parsed default parameters', async () => {
    renderWithProviders(<LagEnergySpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));

    await waitFor(() =>
      expect(lagSpectrum).toHaveBeenCalledWith(
        expect.objectContaining({
          event_list_name: 'obs1',
          bin_time: 0.01,
          segment_size: 8,
          freq_min: 0.1,
          freq_max: 1,
          energy_min: 0.5,
          energy_max: 10,
          n_bands: 5,
          log_bands: false,
          ref_min: null,
          ref_max: null,
        })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
  });

  it('sends the reference band only when both edges are filled', async () => {
    renderWithProviders(<LagEnergySpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.type(screen.getByLabelText('Ref min (keV)'), '2');
    await userEvent.type(screen.getByLabelText('Ref max (keV)'), '4');
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));

    await waitFor(() =>
      expect(lagSpectrum).toHaveBeenCalledWith(
        expect.objectContaining({ ref_min: 2, ref_max: 4 })
      )
    );
  });

  it('disables Compute until an event list is selected', async () => {
    renderWithProviders(<LagEnergySpectrumPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });

  it('disables Compute when only one reference-band edge is filled', async () => {
    renderWithProviders(<LagEnergySpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    const button = screen.getByRole('button', { name: /Compute/ });
    expect(button).not.toBeDisabled();

    await userEvent.type(screen.getByLabelText('Ref min (keV)'), '2');
    expect(button).toBeDisabled();

    await userEvent.type(screen.getByLabelText('Ref max (keV)'), '4');
    expect(button).not.toBeDisabled();
  });

  it('renders warnings from the result when present', async () => {
    lagSpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [1, 2, 3, 4, 5],
        spectrum: [null, -0.005, 0, 0.004, null],
        spectrum_error: [null, 0.002, 0.002, 0.003, null],
        freq_range: [0.1, 1],
        ref_band: [2, 4],
        n_segments_hint: 8,
        warnings: [
          'undefined maths while computing this spectrum (numpy: invalid value encountered in sqrt); any affected energy bands are returned as null',
        ],
      },
      message: 'done',
      error: null,
    });
    renderWithProviders(<LagEnergySpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    expect(await screen.findByText(/undefined maths while computing this spectrum/)).toBeInTheDocument();
  });
});
