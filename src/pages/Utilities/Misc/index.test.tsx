import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';
import { apiClient } from '@/api/client';

const capabilities = vi.fn();
const linearRebin = vi.fn();
const logarithmicRebin = vi.fn();
const estimateBaseline = vi.fn();
const generateWindow = vi.fn();
const optimalBinTime = vi.fn();
const nearestPowerOfTwo = vi.fn();
const adjustSegmentSize = vi.fn();
const poissonErrors = vi.fn();
const standardError = vi.fn();
const equalCountEnergyRanges = vi.fn();

vi.mock('@/api/miscApi', () => ({
  miscApi: {
    capabilities: (...args: unknown[]) => capabilities(...args),
    linearRebin: (...args: unknown[]) => linearRebin(...args),
    logarithmicRebin: (...args: unknown[]) => logarithmicRebin(...args),
    estimateBaseline: (...args: unknown[]) => estimateBaseline(...args),
    generateWindow: (...args: unknown[]) => generateWindow(...args),
    optimalBinTime: (...args: unknown[]) => optimalBinTime(...args),
    nearestPowerOfTwo: (...args: unknown[]) => nearestPowerOfTwo(...args),
    adjustSegmentSize: (...args: unknown[]) => adjustSegmentSize(...args),
    poissonErrors: (...args: unknown[]) => poissonErrors(...args),
    standardError: (...args: unknown[]) => standardError(...args),
    equalCountEnergyRanges: (...args: unknown[]) => equalCountEnergyRanges(...args),
  },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: ({ data }: { data: unknown[] }) => (
    <div data-testid="chart" data-traces={data.length}>plot</div>
  ),
}));

vi.mock('@/components/analysis/EventListSelector', () => ({
  default: ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <label>
      {label}
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose</option>
        <option value="energy-events">energy-events</option>
      </select>
    </label>
  ),
}));

import MiscPage from './index';

const provenance = {
  operation: 'test_operation',
  input_source: { kind: 'pasted_values' },
  parameters: {},
  stingray_version: '2.2.10',
};

const capabilityData = {
  window_types: ['uniform', 'hamming', 'blackmann'],
  rebin: {
    modes: ['linear', 'logarithmic'],
    linear_methods: ['sum', 'mean'],
    logarithmic_method: 'mean',
    linear_uncertainty_workaround_required: true,
    linear_uncertainty_workaround_reference: 'StingraySoftware/stingray#953',
    linear_uncertainty_support: 'uniform spacing and integer ratio only',
  },
  baseline_defaults: {
    lambda: 1e11,
    asymmetry: 0.001,
    iterations: 10,
    offset_correction: false,
  },
  runtime_advisories: {
    nearest_power_of_two: 'Fail closed when installed Stingray is not mathematically nearest.',
  },
  limits: {
    max_array_values: 100_000,
    max_exact_output_values: 100_000,
    max_matrix_cells: 200_000,
    max_baseline_iterations: 100,
    max_fft_samples: 16_777_216,
    max_poisson_count: 200_000,
    max_energy_ranges: 1_000,
  },
  warnings: [],
  provenance,
};

const rebinData = {
  mode: 'linear',
  method: 'sum',
  units: { x: 'same as input x', y: 'same as input y', y_error: 'same as input y', samples_per_bin: 'input samples' },
  original: { x: [0.5, 1.5, 2.5, 3.5], y: [2, 4, 6, 8], y_error: [1, 1, 1, 1] },
  rebinned: { x: [1, 3], y: [6, 14], y_error: [Math.SQRT2, Math.SQRT2], samples_per_bin: [2, 2] },
  error_semantics: 'independent one-standard-deviation uncertainties propagated in quadrature',
  plot_preview: {
    original: { values: { x: [0.5, 1.5, 2.5, 3.5], y: [2, 4, 6, 8], y_error: [1, 1, 1, 1] }, stride: 1, source_points: 4 },
    rebinned: { values: { x: [1, 3], y: [6, 14], y_error: [Math.SQRT2, Math.SQRT2] }, stride: 1, source_points: 2 },
  },
  warnings: ['Squared standard uncertainties were supplied for Stingray 2.2.10.'],
  provenance,
};

const baselineData = {
  x: [0, 1, 2],
  original: [2, 4, 8],
  baseline: [1, 2, 3],
  corrected: [1, 2, 5],
  units: { x: 'same as input x', original: 'same as input y', baseline: 'same as input y', corrected: 'same as input y' },
  plot_preview: { values: { x: [0, 1, 2], original: [2, 4, 8], baseline: [1, 2, 3], corrected: [1, 2, 5] }, stride: 1, source_points: 3 },
  warnings: ['Baseline solver advisory.'],
  provenance,
};

function ok<T>(data: T) {
  return { success: true, data, message: 'done', error: null };
}

function activePanel() {
  return screen.getByRole('tabpanel');
}

async function openTab(name: string): Promise<void> {
  await userEvent.click(screen.getByRole('tab', { name }));
}

async function replaceField(label: string | RegExp, value: string): Promise<void> {
  const field = within(activePanel()).getByLabelText(label);
  await userEvent.clear(field);
  await userEvent.type(field, value);
}

describe('MiscPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    capabilities.mockResolvedValue(ok(capabilityData));
    linearRebin.mockResolvedValue(ok(rebinData));
    logarithmicRebin.mockResolvedValue(ok({ ...rebinData, mode: 'logarithmic', method: 'mean', warnings: [] }));
    estimateBaseline.mockResolvedValue(ok(baselineData));
    generateWindow.mockResolvedValue(ok({
      window_type: 'blackmann',
      n_samples: 4,
      sample_index: [0, 1, 2, 3],
      window: [0, 0.5, 0.5, 0],
      units: { sample_index: 'sample', window: 'dimensionless', summary: 'dimensionless unless named in bins' },
      summary: { minimum: 0, maximum: 0.5, sum: 1, mean: 0.25, rms: 0.3535, energy: 0.5, coherent_gain: 0.25, equivalent_noise_bandwidth_bins: 2 },
      plot_preview: { values: { sample_index: [0, 1, 2, 3], window: [0, 0.5, 0.5, 0] }, stride: 1, source_points: 4 },
      warnings: [],
      provenance,
    }));
    optimalBinTime.mockResolvedValue(ok({ requested_bin_time: 2.1, adjusted_bin_time: 2, sample_count: 256, delta: -0.1, fractional_change: -0.0476, changed: true, units: 'same time units', warnings: ['Bin time changed.'], provenance }));
    nearestPowerOfTwo.mockResolvedValue(ok({ requested_value: 6, nearest_power_of_two: 8, delta: 2, fractional_change: 1 / 3, changed: true, units: 'dimensionless', warnings: ['Value changed.'], provenance }));
    adjustSegmentSize.mockResolvedValue(ok({ requested_segment_size: 10.1, adjusted_segment_size: 10, sample_count: 10, delta: -0.1, fractional_change: -0.0099, changed: true, units: 'same time units', warnings: ['Segment changed.'], provenance }));
    poissonErrors.mockResolvedValue(ok({ counts: [0, 4, 9], symmetric_error: [0.92, 2.06, 3.04], confidence_sigma: 1, units: { counts: 'count', symmetric_error: 'count', confidence_sigma: 'standard deviations' }, assumptions: 'Independent Poisson observations.', plot_preview: { values: { counts: [0, 4, 9], symmetric_error: [0.92, 2.06, 3.04] }, stride: 1, source_points: 3 }, warnings: [], provenance }));
    standardError.mockResolvedValue(ok({ mean: [2, 3], calculated_sample_mean: [2, 3], standard_error: [1, 1], sample_count: 2, column_count: 2, mean_source: 'calculated_arithmetic_mean', units: { mean: 'same as input samples', calculated_sample_mean: 'same as input samples', standard_error: 'same as input samples', sample_count: 'samples', column_count: 'columns' }, assumptions: 'Rows are independent samples.', plot_preview: { values: { column_index: [0, 1], mean: [2, 3], standard_error: [1, 1] }, stride: 1, source_points: 2 }, warnings: [], provenance }));
    equalCountEnergyRanges.mockResolvedValue(ok({ bin_edges: [1, 2, 3, 4, 5], counts: [1, 1, 1, 1], n_ranges: 4, selected_count: 4, excluded_count: 0, energy_min: 1, energy_max: 5, energy_unit: 'keV', plot_preview: { values: { rank: [0, 1, 2, 3], energy: [1, 2, 3, 5] }, stride: 1, source_points: 4 }, warnings: [], provenance }));
  });

  it('shows a bounded empty state and disables submission while capabilities load', async () => {
    capabilities.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<MiscPage />);
    expect(screen.getByText(/Loading installed Stingray capabilities/)).toBeInTheDocument();
    expect(within(activePanel()).getByRole('button', { name: 'Rebin data' })).toBeDisabled();
    expect(within(activePanel()).getByText(/Paste aligned x\/y arrays/)).toBeInTheDocument();
  });

  it('submits the exact linear payload, blocks duplicate runs, and renders warnings, tables and plot', async () => {
    let resolveRequest: ((value: ReturnType<typeof ok>) => void) | undefined;
    linearRebin.mockReturnValueOnce(new Promise((resolve) => { resolveRequest = resolve; }));
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    expect(screen.getByText(/Stingray 2\.2\.10 linear-error workaround/)).toBeInTheDocument();
    await replaceField('x values', '0.5 1.5 2.5 3.5');
    await replaceField('y values', '2 4 6 8');
    await replaceField(/1σ uncertainties/, '1 1 1 1');
    await replaceField(/Original dx/, '1');
    const button = within(activePanel()).getByRole('button', { name: 'Rebin data' });
    await userEvent.click(button);
    expect(linearRebin).toHaveBeenCalledWith({ x: [0.5, 1.5, 2.5, 3.5], y: [2, 4, 6, 8], dx_new: 2, y_error: [1, 1, 1, 1], method: 'sum', dx: 1 });
    expect(button).toBeDisabled();
    button.click();
    expect(linearRebin).toHaveBeenCalledTimes(1);
    await act(async () => resolveRequest?.(ok(rebinData)));
    expect(await within(activePanel()).findByText('Squared standard uncertainties were supplied for Stingray 2.2.10.')).toBeInTheDocument();
    expect(within(activePanel()).getByText('Original exact values')).toBeInTheDocument();
    expect(within(activePanel()).getByText('Rebinned exact values')).toBeInTheDocument();
    expect(within(activePanel()).getByTestId('chart')).toHaveAttribute('data-traces', '2');
  });

  it('rejects fractional-overlap linear uncertainty propagation before calling the API', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await replaceField('x values', '0.5 1.5 2.5 3.5');
    await replaceField('y values', '2 4 6 8');
    await replaceField(/1σ uncertainties/, '1 1 1 1');
    await replaceField('New dx', '2.5');
    expect(within(activePanel()).getByText(/requires an integer new dx \/ original dx ratio/)).toBeInTheDocument();
    expect(within(activePanel()).getByRole('button', { name: 'Rebin data' })).toBeDisabled();
    expect(linearRebin).not.toHaveBeenCalled();
  });

  it('rejects a linear target wider than the covered input span', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await replaceField('x values', '0 0.1');
    await replaceField('y values', '1 2');
    await replaceField('New dx', '0.3');
    await replaceField(/Original dx/, '0.1');

    expect(
      within(activePanel()).getByText(/no complete output bin fits/)
    ).toBeInTheDocument();
    expect(within(activePanel()).getByRole('button', { name: 'Rebin data' })).toBeDisabled();
    expect(linearRebin).not.toHaveBeenCalled();
  });

  it('accepts an ULP-quantized uniform grid at a large absolute offset', async () => {
    const x = Array.from({ length: 20 }, (_, index) => 1e12 + index * 0.1);
    const y = Array.from({ length: 20 }, (_, index) => index + 1);
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    fireEvent.change(within(activePanel()).getByLabelText('x values'), {
      target: { value: x.join(' ') },
    });
    fireEvent.change(within(activePanel()).getByLabelText('y values'), {
      target: { value: y.join(' ') },
    });
    fireEvent.change(within(activePanel()).getByLabelText(/1σ uncertainties/), {
      target: { value: Array(20).fill('0.1').join(' ') },
    });
    await replaceField('New dx', '0.2');
    await replaceField(/Original dx/, '0.1');

    const button = within(activePanel()).getByRole('button', { name: 'Rebin data' });
    expect(button).toBeEnabled();
    await userEvent.click(button);

    await waitFor(() =>
      expect(linearRebin).toHaveBeenCalledWith({
        x,
        y,
        dx_new: 0.2,
        y_error: Array(20).fill(0.1),
        method: 'sum',
        dx: 0.1,
      })
    );
  });

  it('switches to logarithmic rebinning and submits its mean-only contract', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    const panel = within(activePanel());
    await userEvent.click(panel.getByLabelText('Rebin mode'));
    await userEvent.click(await screen.findByRole('option', { name: 'Logarithmic' }));
    await replaceField('x values', '1 2 3 4');
    await replaceField('y values', '2 4 6 8');
    await userEvent.click(within(activePanel()).getByRole('button', { name: 'Rebin data' }));
    await waitFor(() => expect(logarithmicRebin).toHaveBeenCalledWith({ x: [1, 2, 3, 4], y: [2, 4, 6, 8], factor: 0.1, y_error: null, dx: null }));
    expect(await within(activePanel()).findByTestId('chart')).toBeInTheDocument();
  });

  it('preserves the last baseline result after a later soft failure', async () => {
    estimateBaseline.mockResolvedValueOnce(ok(baselineData)).mockResolvedValueOnce({ success: false, data: null, message: 'Solver rejected the update', error: null });
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await openTab('Baseline');
    await replaceField('x values', '0 1 2');
    await replaceField('y values', '2 4 8');
    await userEvent.click(within(activePanel()).getByRole('button', { name: 'Estimate baseline' }));
    await waitFor(() => expect(estimateBaseline).toHaveBeenCalledWith({ x: [0, 1, 2], y: [2, 4, 8], lam: 1e11, asymmetry: 0.001, iterations: 10, offset_correction: false }));
    expect(await within(activePanel()).findByText('Baseline solver advisory.')).toBeInTheDocument();
    await replaceField('Lambda (smoothness)', '1000');
    await userEvent.click(within(activePanel()).getByRole('button', { name: 'Estimate baseline' }));
    expect(await within(activePanel()).findByText('Solver rejected the update')).toBeInTheDocument();
    expect(within(activePanel()).getByText('Exact baseline result')).toBeInTheDocument();
    expect(within(activePanel()).getByTestId('chart')).toBeInTheDocument();
  });

  it('derives exact window spellings from capabilities and renders coefficients', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await openTab('Windows');
    const panel = within(activePanel());
    await userEvent.click(panel.getByLabelText('Window type'));
    await userEvent.click(await screen.findByRole('option', { name: 'blackmann' }));
    await replaceField('Sample count N', '4');
    await userEvent.click(panel.getByRole('button', { name: 'Generate window' }));
    await waitFor(() => expect(generateWindow).toHaveBeenCalledWith({ n_samples: 4, window_type: 'blackmann' }));
    expect(await within(activePanel()).findByText('Exact coefficients')).toBeInTheDocument();
    expect(within(activePanel()).getByTestId('chart')).toBeInTheDocument();
  });

  it('runs and switches among all three sampling operations with exact payloads', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await openTab('Sampling');
    let panel = within(activePanel());
    await userEvent.click(panel.getByRole('button', { name: 'Calculate bin time' }));
    await waitFor(() => expect(optimalBinTime).toHaveBeenCalledWith({ fft_length: 512, proposed_bin_time: 2.1 }));
    await userEvent.click(panel.getByLabelText('Sampling operation'));
    await userEvent.click(await screen.findByRole('option', { name: 'Nearest power of two' }));
    panel = within(activePanel());
    expect(panel.getByText(/Fail closed when installed Stingray/)).toBeInTheDocument();
    await userEvent.click(panel.getByRole('button', { name: 'Find nearest power' }));
    await waitFor(() => expect(nearestPowerOfTwo).toHaveBeenCalledWith({ value: 6 }));
    await userEvent.click(panel.getByLabelText('Sampling operation'));
    await userEvent.click(await screen.findByRole('option', { name: 'Integer-sample segment' }));
    panel = within(activePanel());
    await userEvent.click(panel.getByRole('button', { name: 'Adjust segment' }));
    await waitFor(() => expect(adjustSegmentSize).toHaveBeenCalledWith({ segment_size: 10.1, dt: 1, tolerance: 0.01 }));
    expect(await within(activePanel()).findByText('Adjustment result')).toBeInTheDocument();
  });

  it('runs Poisson and standard-error operations with exact matrix parsing', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await openTab('Errors');
    await replaceField('Poisson counts', '0 4 9');
    await userEvent.click(within(activePanel()).getByRole('button', { name: 'Calculate Poisson errors' }));
    await waitFor(() => expect(poissonErrors).toHaveBeenCalledWith({ counts: [0, 4, 9] }));
    expect(await within(activePanel()).findByText('Exact Poisson errors')).toBeInTheDocument();
    await userEvent.click(within(activePanel()).getByLabelText('Error operation'));
    await userEvent.click(await screen.findByRole('option', { name: 'Column-wise standard error' }));
    await replaceField('Sample matrix', '1, 2\n3, 4');
    await userEvent.click(within(activePanel()).getByRole('button', { name: 'Calculate standard error' }));
    await waitFor(() => expect(standardError).toHaveBeenCalledWith({ samples: [[1, 2], [3, 4]], mean: null }));
    expect(await within(activePanel()).findByText('Exact standard errors')).toBeInTheDocument();
  });

  it('matches backend absolute tolerance for a near-zero reference mean', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await openTab('Errors');
    await userEvent.click(within(activePanel()).getByLabelText('Error operation'));
    await userEvent.click(await screen.findByRole('option', { name: 'Column-wise standard error' }));
    await replaceField('Sample matrix', '-1\n1');
    await replaceField('Reference mean (optional)', '0.00000000005');

    expect(
      within(activePanel()).getByText(/must match the arithmetic sample mean/)
    ).toBeInTheDocument();
    expect(
      within(activePanel()).getByRole('button', { name: 'Calculate standard error' })
    ).toBeDisabled();
    expect(standardError).not.toHaveBeenCalled();
  });

  it('keeps pasted and EventList energy sources mutually exclusive', async () => {
    renderWithProviders(<MiscPage />);
    await screen.findByText(/Runtime caps:/);
    await openTab('Energy ranges');
    await replaceField('Energy values', '1 2 3 5');
    await userEvent.click(within(activePanel()).getByRole('button', { name: 'Create energy ranges' }));
    await waitFor(() => expect(equalCountEnergyRanges).toHaveBeenCalledWith({ n_ranges: 4, energies: [1, 2, 3, 5], energy_min: null, energy_max: null, energy_unit: 'keV' }));
    expect(await within(activePanel()).findByText('Exact energy ranges')).toBeInTheDocument();
    await userEvent.click(within(activePanel()).getByLabelText('Energy source'));
    await userEvent.click(await screen.findByRole('option', { name: 'Loaded EventList' }));
    await userEvent.selectOptions(within(activePanel()).getByLabelText('Energy EventList'), 'energy-events');
    await userEvent.click(within(activePanel()).getByRole('button', { name: 'Create energy ranges' }));
    await waitFor(() => expect(equalCountEnergyRanges).toHaveBeenLastCalledWith({ n_ranges: 4, event_list_name: 'energy-events', energy_min: null, energy_max: null, energy_unit: 'keV' }));
    expect(within(activePanel()).getByTestId('chart')).toBeInTheDocument();
  });

  it('surfaces a capabilities error and leaves scientific submissions disabled', async () => {
    capabilities.mockResolvedValue({ success: false, data: null, message: 'Runtime inspection failed', error: null });
    renderWithProviders(<MiscPage />);
    expect(await screen.findByText(/Runtime inspection failed/)).toBeInTheDocument();
    expect(within(activePanel()).getByRole('button', { name: 'Rebin data' })).toBeDisabled();
  });

  it('maps every typed API method to its exact route and renderer payload', async () => {
    const { miscApi: actualApi } = await vi.importActual<typeof import('@/api/miscApi')>(
      '@/api/miscApi'
    );
    const response = { success: true, data: {}, message: 'ok', error: null };
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue(response);
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue(response);

    await actualApi.capabilities();
    await actualApi.linearRebin({ x: [1, 2], y: [3, 4], dx_new: 2, method: 'mean' });
    await actualApi.logarithmicRebin({ x: [1, 2], y: [3, 4], factor: 0.2 });
    await actualApi.estimateBaseline({ x: [0, 1, 2], y: [2, 3, 5], lam: 10, asymmetry: 0.1, iterations: 4, offset_correction: true });
    await actualApi.generateWindow({ n_samples: 8, window_type: 'blackmann' });
    await actualApi.optimalBinTime({ fft_length: 512, proposed_bin_time: 2.1 });
    await actualApi.nearestPowerOfTwo({ value: 6 });
    await actualApi.adjustSegmentSize({ segment_size: 10.1, dt: 1, tolerance: 0.01 });
    await actualApi.poissonErrors({ counts: [0, 4] });
    await actualApi.standardError({ samples: [[1, 2], [3, 4]] });
    await actualApi.equalCountEnergyRanges({ n_ranges: 2, event_list_name: 'energy-events', energy_unit: 'keV' });

    expect(get).toHaveBeenCalledWith('/api/utilities/misc/capabilities');
    expect(post.mock.calls).toEqual([
      ['/api/utilities/misc/rebin/linear', { x: [1, 2], y: [3, 4], dx_new: 2, y_error: null, method: 'mean', dx: null }],
      ['/api/utilities/misc/rebin/logarithmic', { x: [1, 2], y: [3, 4], factor: 0.2, y_error: null, dx: null }],
      ['/api/utilities/misc/baseline', { x: [0, 1, 2], y: [2, 3, 5], lam: 10, asymmetry: 0.1, iterations: 4, offset_correction: true }],
      ['/api/utilities/misc/window', { n_samples: 8, window_type: 'blackmann' }],
      ['/api/utilities/misc/sampling/optimal-bin-time', { fft_length: 512, proposed_bin_time: 2.1 }],
      ['/api/utilities/misc/sampling/nearest-power-of-two', { value: 6 }],
      ['/api/utilities/misc/sampling/segment-size', { segment_size: 10.1, dt: 1, tolerance: 0.01 }],
      ['/api/utilities/misc/errors/poisson', { counts: [0, 4] }],
      ['/api/utilities/misc/errors/standard', { samples: [[1, 2], [3, 4]], mean: null }],
      ['/api/utilities/misc/energy-ranges', { n_ranges: 2, energies: null, event_list_name: 'energy-events', energy_min: null, energy_max: null, energy_unit: 'keV' }],
    ]);
    get.mockRestore();
    post.mockRestore();
  });
});
