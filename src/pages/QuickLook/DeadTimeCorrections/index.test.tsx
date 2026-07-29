import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const pdsCorrection = vi.fn();
const fadCorrection = vi.fn();
vi.mock('@/api/deadtimeApi', () => ({
  deadtimeApi: {
    pdsCorrection: (...a: unknown[]) => pdsCorrection(...a),
    fadCorrection: (...a: unknown[]) => fadCorrection(...a),
  },
}));
vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import DeadTimeCorrectionsPage from './index';

async function selectEventList(label: string, option: RegExp): Promise<void> {
  await userEvent.click(await screen.findByLabelText(label));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

describe('DeadTimeCorrectionsPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockReset();
    pdsCorrection.mockReset();
    fadCorrection.mockReset();
    listEventLists.mockResolvedValue({
      success: true,
      data: [
        { name: 'obs1', n_events: 5000, time_range: [0, 100] },
        { name: 'obs2', n_events: 4800, time_range: [0, 100] },
      ],
      message: '',
      error: null,
    });
    pdsCorrection.mockResolvedValue({
      success: true,
      data: {
        freq: [1, 2, 3],
        power_uncorrected: [1.66, null, 1.71],
        power_corrected: [2.0, 1.99, 2.01],
        rate: 171.5,
        n_events: 17150,
        exposure: 100,
        n_segments: 5,
        dt: 0.001,
        segment_size: 20,
        dead_time: 0.0025,
        background_rate: 0,
        limit_k: 200,
        norm: 'leahy',
        warnings: ['only 5 segments were averaged'],
      },
      message: 'corrected',
      error: null,
    });
    fadCorrection.mockResolvedValue({
      success: true,
      data: {
        freq: [1, 2, 3],
        pds1: [2.0, 1.9, null],
        pds2: [2.1, 2.0, 1.95],
        ptot: [4.1, 3.9, 3.9],
        cs: [0.5, 0.4, 0.3],
        cs_real: [0.5, -0.4, null],
        n_segments: 12,
        dt: 0.001,
        segment_size: 8,
        norm: 'frac',
        smoothing_length: 24,
        is_compliant: false,
        fad_delta: 0.42,
        warnings: ['FAD is not compliant: 42% deviation'],
      },
      message: 'fad done',
      error: null,
    });
  });

  it('converts incident to detected rates client-side and flags unphysical occupancy', async () => {
    renderWithProviders(<DeadTimeCorrectionsPage />);
    // Defaults: 300 c/s incident with a 2.5 ms dead time -> 300 / 1.75
    expect(await screen.findByText('Detected: 171.43 c/s')).toBeInTheDocument();
    expect(screen.getByText('Incident: 300.00 c/s')).toBeInTheDocument();
    expect(screen.getByText('Dead-time loss: 42.9%')).toBeInTheDocument();

    // Same numbers read as a detected rate invert the other way: 300 / 0.25
    await userEvent.click(screen.getByRole('radio', { name: 'Detected' }));
    expect(await screen.findByText('Incident: 1200.00 c/s')).toBeInTheDocument();

    // 500 c/s x 2.5 ms >= 1 leaves the detector permanently busy
    const rateField = screen.getByLabelText('Known rate (c/s)');
    await userEvent.clear(rateField);
    await userEvent.type(rateField, '500');
    expect(
      await screen.findByText('unphysical: detected rate x dead time must be < 1')
    ).toBeInTheDocument();
    expect(screen.getByText('Incident: — c/s')).toBeInTheDocument();
  });

  it('runs the model correction with the backend field names', async () => {
    renderWithProviders(<DeadTimeCorrectionsPage />);
    await selectEventList('Event list', /obs1/);
    await userEvent.click(screen.getByRole('button', { name: /Compute correction/ }));

    await waitFor(() =>
      expect(pdsCorrection).toHaveBeenCalledWith(
        expect.objectContaining({
          event_list_name: 'obs1',
          dt: 0.001,
          segment_size: 20,
          dead_time: 0.0025,
          background_rate: 0,
          limit_k: 200,
        })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
    expect(screen.getByText('detected rate: 171.50 c/s')).toBeInTheDocument();
    expect(screen.getByText('5 segments')).toBeInTheDocument();
    expect(screen.getByText('only 5 segments were averaged')).toBeInTheDocument();
    expect(
      screen.getByText(/Normalization fixed to Leahy \(required by the Zhang\+95 correction\)/)
    ).toBeInTheDocument();
  });

  it('runs the FAD correction with the backend field names', async () => {
    renderWithProviders(<DeadTimeCorrectionsPage />);
    await selectEventList('Detector 1 event list', /obs1/);
    await selectEventList('Detector 2 event list', /obs2/);
    await userEvent.click(screen.getByRole('button', { name: /Compute FAD/ }));

    await waitFor(() =>
      expect(fadCorrection).toHaveBeenCalledWith(
        expect.objectContaining({
          event_list_1_name: 'obs1',
          event_list_2_name: 'obs2',
          dt: 0.001,
          segment_size: 8,
          norm: 'frac',
          smoothing_length: null,
        })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
    expect(screen.getByText('12 segments')).toBeInTheDocument();
    expect(screen.getByText('FAD Δ: 0.420')).toBeInTheDocument();
    // is_compliant === false must surface the warnings prominently
    expect(screen.getByText(/FAD self-check failed/)).toBeInTheDocument();
    expect(screen.getByText('FAD is not compliant: 42% deviation')).toBeInTheDocument();
  });

  it('disables each Compute button until that panel has valid inputs', async () => {
    renderWithProviders(<DeadTimeCorrectionsPage />);
    const correctionButton = await screen.findByRole('button', { name: /Compute correction/ });
    const fadButton = screen.getByRole('button', { name: /Compute FAD/ });
    expect(correctionButton).toBeDisabled();
    expect(fadButton).toBeDisabled();

    await selectEventList('Event list', /obs1/);
    expect(correctionButton).toBeEnabled();
    expect(fadButton).toBeDisabled();

    await userEvent.clear(screen.getByLabelText('PDS dt (s)'));
    expect(correctionButton).toBeDisabled();

    await selectEventList('Detector 1 event list', /obs1/);
    expect(fadButton).toBeDisabled();
    await selectEventList('Detector 2 event list', /obs2/);
    expect(fadButton).toBeEnabled();

    await userEvent.type(screen.getByLabelText('Smoothing sigma (bins)'), 'x');
    expect(fadButton).toBeDisabled();
    expect(pdsCorrection).not.toHaveBeenCalled();
    expect(fadCorrection).not.toHaveBeenCalled();
  });

  it('disables Compute FAD when both detector selectors hold the same event list', async () => {
    renderWithProviders(<DeadTimeCorrectionsPage />);
    const fadButton = screen.getByRole('button', { name: /Compute FAD/ });

    await selectEventList('Detector 1 event list', /obs1/);
    await selectEventList('Detector 2 event list', /obs2/);
    expect(fadButton).toBeEnabled();
    expect(
      screen.queryByText(/FAD needs two independent detectors/)
    ).not.toBeInTheDocument();

    // Selecting the same list for both detectors must disable the button again
    // and explain why, instead of silently allowing a meaningless FAD run.
    await selectEventList('Detector 2 event list', /obs1/);
    expect(fadButton).toBeDisabled();
    expect(screen.getByText(/FAD needs two independent detectors/)).toBeInTheDocument();

    await selectEventList('Detector 2 event list', /obs2/);
    expect(fadButton).toBeEnabled();
    expect(
      screen.queryByText(/FAD needs two independent detectors/)
    ).not.toBeInTheDocument();

    await userEvent.click(fadButton);
    await waitFor(() => expect(fadCorrection).toHaveBeenCalled());
  });
});
