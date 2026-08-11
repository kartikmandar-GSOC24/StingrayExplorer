import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const excessVariance = vi.fn();
vi.mock('@/api/varenergyApi', () => ({
  varenergyApi: { excessVariance: (...a: unknown[]) => excessVariance(...a) },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import ExcessVarianceSpectrumPage from './index';

describe('ExcessVarianceSpectrumPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockReset();
    excessVariance.mockReset();
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
  });

  it('computes the excess variance spectrum with parsed default parameters and plots it', async () => {
    excessVariance.mockResolvedValue({
      success: true,
      data: {
        energy: [0.5, 1.5, 2.5, 5, 8],
        spectrum: [0.4, 0.42, 0.38, 0.35, 0.3],
        spectrum_error: [0.02, 0.02, 0.03, 0.03, 0.04],
        normalization: 'fvar',
        warnings: [],
      },
      message: 'ok',
      error: null,
    });

    renderWithProviders(<ExcessVarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));

    await screen.findByTestId('chart');
    expect(excessVariance).toHaveBeenCalledWith(
      expect.objectContaining({
        event_list_name: 'obs1',
        bin_time: 0.1,
        energy_min: 0.5,
        energy_max: 10,
        n_bands: 5,
        log_bands: false,
        normalization: 'fvar',
      })
    );
    expect(screen.getByText('normalization: fvar')).toBeInTheDocument();
    expect(screen.getByText('n bands: 5')).toBeInTheDocument();
  });

  it('disables Compute until inputs are valid', async () => {
    renderWithProviders(<ExcessVarianceSpectrumPage />);
    const button = await screen.findByRole('button', { name: /Compute/ });
    expect(button).toBeDisabled();
  });

  it('surfaces the all-null advisory from warnings prominently when nothing computes', async () => {
    excessVariance.mockResolvedValue({
      success: true,
      data: {
        energy: [0.5, 1.5, 2.5, 5, 8],
        spectrum: [null, null, null, null, null],
        spectrum_error: [null, null, null, null, null],
        normalization: 'fvar',
        warnings: [
          'the excess variance spectrum could not be computed for any energy band (stingray returns NaN when the reference band shows no variability above the Poisson noise floor). Try a longer segment_size, a coarser bin_time, fewer energy bands, or a source with real variability.',
        ],
      },
      message: 'ok',
      error: null,
    });

    renderWithProviders(<ExcessVarianceSpectrumPage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    await userEvent.click(screen.getByRole('button', { name: /Compute/ }));

    expect(
      await screen.findByText(/could not be computed for any energy band/)
    ).toBeInTheDocument();
  });
});
