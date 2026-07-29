import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const avgCovarianceSpectrum = vi.fn();
vi.mock('@/api/varenergyApi', () => ({
  varenergyApi: {
    avgCovarianceSpectrum: (...a: unknown[]) => avgCovarianceSpectrum(...a),
  },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import AvgCovarianceSpectrumPage from './index';

describe('AvgCovarianceSpectrumPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    avgCovarianceSpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [0.5, 1.5, 3, 5.5, 9],
        spectrum: [140.2, 152.8, 159.1, 148.4, 141.9],
        spectrum_error: [4.1, 3.9, 4.2, 4.0, 4.3],
        freq_range: [0.1, 1],
        ref_band: null,
        norm: 'abs',
        segment_size: 8,
        n_segments_hint: 6,
        warnings: [],
      },
      message: 'done',
      error: null,
    });
  });

  it('computes an averaged covariance spectrum with parsed default parameters and plots it', async () => {
    renderWithProviders(<AvgCovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    await waitFor(() =>
      expect(avgCovarianceSpectrum).toHaveBeenCalledWith(
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
          norm: 'abs',
        })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
    expect(screen.getByText(/segment 8 s/)).toBeInTheDocument();
    expect(screen.getByText(/≈ 6 segments/)).toBeInTheDocument();
  });

  it('sends the reference band when both fields are filled in', async () => {
    renderWithProviders(<AvgCovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.type(screen.getByLabelText('Ref band min (keV)'), '2');
    await userEvent.type(screen.getByLabelText('Ref band max (keV)'), '6');
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    await waitFor(() =>
      expect(avgCovarianceSpectrum).toHaveBeenCalledWith(
        expect.objectContaining({ ref_min: 2, ref_max: 6 })
      )
    );
  });

  it('disables Compute until inputs are valid', async () => {
    renderWithProviders(<AvgCovarianceSpectrumPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });

  it('disables Compute when the reference band is only half-filled', async () => {
    renderWithProviders(<AvgCovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.type(screen.getByLabelText('Ref band min (keV)'), '2');
    expect(screen.getByRole('button', { name: /Compute/ })).toBeDisabled();
  });

  it('renders warnings from the result when present', async () => {
    avgCovarianceSpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [0.5, 1.5, 3, 5.5, 9],
        spectrum: [null, null, null, null, null],
        spectrum_error: [null, null, null, null, null],
        freq_range: [0.1, 1],
        ref_band: null,
        norm: 'abs',
        segment_size: 8,
        n_segments_hint: 6,
        warnings: [
          'the covariance spectrum could not be computed for any energy band (stingray returns NaN when the reference band shows no variability above the Poisson noise floor).',
        ],
      },
      message: 'done',
      error: null,
    });
    renderWithProviders(<AvgCovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    expect(
      await screen.findByText(/the covariance spectrum could not be computed for any energy band/)
    ).toBeInTheDocument();
  });
});
