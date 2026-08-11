import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const covarianceSpectrum = vi.fn();
vi.mock('@/api/varenergyApi', () => ({
  varenergyApi: {
    covarianceSpectrum: (...a: unknown[]) => covarianceSpectrum(...a),
  },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import CovarianceSpectrumPage from './index';

describe('CovarianceSpectrumPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    covarianceSpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [0.5, 1.5, 3, 5.5, 9],
        spectrum: [140.2, 152.8, 159.1, 148.4, 141.9],
        spectrum_error: [4.1, 3.9, 4.2, 4.0, 4.3],
        freq_range: [0.1, 1],
        ref_band: null,
        norm: 'abs',
        segment_size: 64,
        n_segments_hint: 1,
        warnings: [],
      },
      message: 'done',
      error: null,
    });
  });

  it('computes a covariance spectrum with parsed default parameters and plots it', async () => {
    renderWithProviders(<CovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    await waitFor(() =>
      expect(covarianceSpectrum).toHaveBeenCalledWith(
        expect.objectContaining({
          event_list_name: 'obs1',
          bin_time: 0.1,
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
    // No segment_size field on this endpoint's request.
    expect(covarianceSpectrum).not.toHaveBeenCalledWith(
      expect.objectContaining({ segment_size: expect.anything() })
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
    expect(screen.getByText(/1 segment · 64 s \(full GTI\)/)).toBeInTheDocument();
  });

  it('sends the reference band when both fields are filled in', async () => {
    renderWithProviders(<CovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.type(screen.getByLabelText('Ref band min (keV)'), '2');
    await userEvent.type(screen.getByLabelText('Ref band max (keV)'), '6');
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    await waitFor(() =>
      expect(covarianceSpectrum).toHaveBeenCalledWith(
        expect.objectContaining({ ref_min: 2, ref_max: 6 })
      )
    );
  });

  it('disables Compute until inputs are valid', async () => {
    renderWithProviders(<CovarianceSpectrumPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });

  it('disables Compute when the reference band is only half-filled', async () => {
    renderWithProviders(<CovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.type(screen.getByLabelText('Ref band min (keV)'), '2');
    expect(screen.getByRole('button', { name: /Compute/ })).toBeDisabled();
  });

  it('renders an advisory (not an error) when the result is all-null with warnings', async () => {
    covarianceSpectrum.mockResolvedValue({
      success: true,
      data: {
        energy: [0.5, 1.5, 3, 5.5, 9],
        spectrum: [null, null, null, null, null],
        spectrum_error: [null, null, null, null, null],
        freq_range: [0.1, 1],
        ref_band: null,
        norm: 'abs',
        segment_size: 64,
        n_segments_hint: 1,
        warnings: [
          'the covariance spectrum could not be computed for any energy band (stingray returns NaN when the reference band shows no variability above the Poisson noise floor).',
        ],
      },
      message: 'done',
      error: null,
    });
    renderWithProviders(<CovarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));
    expect(
      await screen.findByText(/the covariance spectrum could not be computed for any energy band/)
    ).toBeInTheDocument();
    expect(await screen.findByText(/No finite covariance values/)).toBeInTheDocument();
  });
});
