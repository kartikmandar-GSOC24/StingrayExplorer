import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';
import type {
  GaussianResult,
  StatisticDetectionResult,
  StatisticEvaluationResult,
  TrialCorrectionResult,
} from '@/api/statisticsApi';

const apiMocks = vi.hoisted(() => ({
  gaussian: vi.fn(),
  trials: vi.fn(),
  evaluatePds: vi.fn(),
  detectPds: vi.fn(),
  evaluateZ2: vi.fn(),
  detectZ2: vi.fn(),
  evaluateFold: vi.fn(),
  detectFold: vi.fn(),
  evaluatePdm: vi.fn(),
  detectPdm: vi.fn(),
}));

vi.mock('@/api/statisticsApi', () => ({ statisticsApi: apiMocks }));

import StatisticalFunctionsPage from './index';

const provenance = {
  operation: 'statistics.test',
  input_source: 'user-supplied scalar inputs',
  parameters: {},
  stingray_version: '2.2.10',
  public_api_calls: ['stingray.stats.test'],
};

function success<T>(data: T) {
  return { success: true, data, message: 'done', error: null };
}

const gaussianResult: GaussianResult = {
  calculation: 'gaussian_significance',
  input_mode: 'probability',
  input_probability: 0.0027,
  input_log_probability: -5.9145,
  effective_one_sided_probability: 0.0027,
  effective_one_sided_log_probability: -5.9145,
  sigma: 2.78215,
  sidedness: 'one-sided',
  tail: 'upper',
  direction: 'probability_to_gaussian_sigma',
  units: {
    input_probability: 'dimensionless probability',
    input_log_probability: 'natural logarithm of a dimensionless probability',
    sigma: 'standard deviations from the Gaussian mean',
  },
  warnings: [],
  provenance,
};

const trialResult: TrialCorrectionResult = {
  calculation: 'trial_correction',
  direction: 'single-to-multi',
  input_probability: 0.001,
  output_probability: 0.0952,
  n_trials: 100,
  independence_assumption: 'Trials are assumed to be statistically independent.',
  units: {
    input_probability: 'dimensionless probability',
    output_probability: 'dimensionless probability',
  },
  warnings: [],
  provenance,
};

function evaluationResult(
  family: StatisticEvaluationResult['family'],
  observedStatistic: number,
  overrides: Partial<StatisticEvaluationResult> = {}
): StatisticEvaluationResult {
  return {
    family,
    calculation: 'probability',
    observed_statistic: observedStatistic,
    probability: 0.01,
    log_probability: -4.605170186,
    probability_scope: 'overall_post_trial',
    n_trials: 1,
    tail: family === 'phase_dispersion' ? 'lower' : 'upper',
    more_significant_when: family === 'phase_dispersion' ? 'smaller' : 'larger',
    direction: 'observed_statistic_to_false_alarm_probability',
    units: {
      observed_statistic: 'dimensionless statistic',
      probability: 'dimensionless probability',
      log_probability: 'natural logarithm of a dimensionless probability',
    },
    warnings: [],
    provenance,
    ...overrides,
  };
}

function detectionResult(
  family: StatisticDetectionResult['family'],
  overrides: Partial<StatisticDetectionResult> = {}
): StatisticDetectionResult {
  const lower = family === 'phase_dispersion';
  return {
    family,
    calculation: 'detection_level',
    false_alarm_probability: 0.01,
    false_alarm_probability_scope: 'overall_post_trial',
    detection_level: lower ? 0.15 : 20,
    n_trials: 1,
    tail: lower ? 'lower' : 'upper',
    decision_rule: lower
      ? 'observed_statistic <= detection_level'
      : 'observed_statistic >= detection_level',
    direction: 'false_alarm_probability_to_detection_level',
    units: {
      false_alarm_probability: 'dimensionless probability',
      detection_level: 'dimensionless statistic',
    },
    warnings: [],
    provenance,
    ...overrides,
  };
}

async function replaceValue(element: HTMLElement, value: string): Promise<void> {
  await userEvent.clear(element);
  if (value !== '') await userEvent.type(element, value);
}

async function chooseSelect(label: string, option: string, scope: HTMLElement): Promise<void> {
  await userEvent.click(within(scope).getByLabelText(label));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

describe('StatisticalFunctionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    apiMocks.gaussian.mockResolvedValue(success(gaussianResult));
    apiMocks.trials.mockResolvedValue(success(trialResult));
    apiMocks.evaluatePds.mockResolvedValue(success(evaluationResult('pds', 20)));
    apiMocks.detectPds.mockResolvedValue(success(detectionResult('pds')));
    apiMocks.evaluateZ2.mockResolvedValue(success(evaluationResult('z2_n', 20)));
    apiMocks.detectZ2.mockResolvedValue(success(detectionResult('z2_n')));
    apiMocks.evaluateFold.mockResolvedValue(success(evaluationResult('epoch_folding', 20)));
    apiMocks.detectFold.mockResolvedValue(success(detectionResult('epoch_folding')));
    apiMocks.evaluatePdm.mockResolvedValue(success(evaluationResult('phase_dispersion', 0.2)));
    apiMocks.detectPdm.mockResolvedValue(success(detectionResult('phase_dispersion')));
  });

  it('renders five linked workbench tabs and is marked ready', () => {
    renderWithProviders(<StatisticalFunctionsPage />);

    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Probability & trials',
      'Power spectrum',
      'Z-squared',
      'Epoch folding',
      'Phase dispersion',
    ]);
    expect(tabs[0]).toHaveAttribute('aria-controls', 'statistics-panel-0');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'statistics-tab-0');
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
  });

  it('binds every typed API method to its exact explicit route and default payload', async () => {
    const { statisticsApi: actualApi } = await vi.importActual<
      typeof import('@/api/statisticsApi')
    >('@/api/statisticsApi');
    const { apiClient } = await vi.importActual<typeof import('@/api/client')>('@/api/client');
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      success: false,
      data: null,
      message: 'stub',
      error: null,
    });

    await actualApi.gaussian({ probability: 0.1, sidedness: 'one-sided' });
    await actualApi.trials({ direction: 'single-to-multi', probability: 0.1, n_trials: 3 });
    await actualApi.evaluatePds({ power: 10 });
    await actualApi.detectPds({ false_alarm_probability: 0.01 });
    await actualApi.evaluateZ2({ z2: 12 });
    await actualApi.detectZ2({ false_alarm_probability: 0.02 });
    await actualApi.evaluateFold({ statistic: 13, n_phase_bins: 16 });
    await actualApi.detectFold({ false_alarm_probability: 0.03, n_phase_bins: 16 });
    await actualApi.evaluatePdm({ statistic: 0.2, n_samples: 100, n_phase_bins: 10 });
    await actualApi.detectPdm({ false_alarm_probability: 0.04, n_samples: 100, n_phase_bins: 10 });

    expect(post.mock.calls).toEqual([
      ['/api/utilities/statistics/gaussian', { probability: 0.1, sidedness: 'one-sided' }],
      [
        '/api/utilities/statistics/trials',
        { direction: 'single-to-multi', probability: 0.1, n_trials: 3 },
      ],
      [
        '/api/utilities/statistics/pds/evaluate',
        { power: 10, n_trials: 1, n_summed_spectra: 1, n_rebin: 1 },
      ],
      [
        '/api/utilities/statistics/pds/detection',
        { false_alarm_probability: 0.01, n_trials: 1, n_summed_spectra: 1, n_rebin: 1 },
      ],
      [
        '/api/utilities/statistics/z2/evaluate',
        { z2: 12, harmonics: 2, n_trials: 1, n_summed_spectra: 1 },
      ],
      [
        '/api/utilities/statistics/z2/detection',
        { false_alarm_probability: 0.02, harmonics: 2, n_trials: 1, n_summed_spectra: 1 },
      ],
      [
        '/api/utilities/statistics/fold/evaluate',
        { statistic: 13, n_phase_bins: 16, n_trials: 1 },
      ],
      [
        '/api/utilities/statistics/fold/detection',
        { false_alarm_probability: 0.03, n_phase_bins: 16, n_trials: 1 },
      ],
      [
        '/api/utilities/statistics/pdm/evaluate',
        { statistic: 0.2, n_samples: 100, n_phase_bins: 10, n_trials: 1 },
      ],
      [
        '/api/utilities/statistics/pdm/detection',
        { false_alarm_probability: 0.04, n_samples: 100, n_phase_bins: 10, n_trials: 1 },
      ],
    ]);
  });

  it('sends exactly one probability input with explicit two-sided semantics', async () => {
    renderWithProviders(<StatisticalFunctionsPage />);
    const panel = screen.getByRole('tabpanel');

    await replaceValue(within(panel).getByLabelText('Tail probability p'), '0.05');
    await chooseSelect('Tail convention', 'Two-sided total probability', panel);
    await userEvent.click(within(panel).getByRole('button', { name: 'Convert to Gaussian sigma' }));

    await waitFor(() =>
      expect(apiMocks.gaussian).toHaveBeenCalledWith({ probability: 0.05, sidedness: 'two-sided' })
    );
    expect(apiMocks.gaussian.mock.calls[0][0]).not.toHaveProperty('log_probability');
  });

  it('sends natural-log probability directly for underflow-safe Gaussian conversion', async () => {
    const logResult: GaussianResult = {
      ...gaussianResult,
      input_mode: 'log_probability',
      input_probability: null,
      input_log_probability: -1000,
      effective_one_sided_probability: 0,
      effective_one_sided_log_probability: -1000,
      sigma: 44.6157,
      warnings: [
        'The linear probability underflowed to 0.0 in floating-point; the finite natural-log probability preserves the significance.',
      ],
    };
    apiMocks.gaussian.mockResolvedValueOnce(success(logResult));
    renderWithProviders(<StatisticalFunctionsPage />);
    const panel = screen.getByRole('tabpanel');

    await chooseSelect('Probability input mode', 'Natural log ln(p)', panel);
    await replaceValue(within(panel).getByLabelText('Natural log probability ln(p)'), '-1000');
    await userEvent.click(within(panel).getByRole('button', { name: 'Convert to Gaussian sigma' }));

    await waitFor(() =>
      expect(apiMocks.gaussian).toHaveBeenCalledWith({
        log_probability: -1000,
        sidedness: 'one-sided',
      })
    );
    expect(apiMocks.gaussian.mock.calls[0][0]).not.toHaveProperty('probability');
    expect((await within(panel).findAllByText('-1000')).length).toBe(2);
    expect(within(panel).getByText(/linear probability underflowed/i)).toBeInTheDocument();
  });

  it('supports both exact independent-trial correction directions and boundary validation', async () => {
    renderWithProviders(<StatisticalFunctionsPage />);
    const panel = screen.getByRole('tabpanel');
    await userEvent.click(within(panel).getByRole('button', { name: 'Trial correction' }));

    await replaceValue(within(panel).getByLabelText('Single-trial probability'), '0');
    await replaceValue(within(panel).getByLabelText('Independent trials'), '12');
    const submit = within(panel).getByRole('button', { name: 'Correct probability' });
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    await waitFor(() =>
      expect(apiMocks.trials).toHaveBeenCalledWith({
        direction: 'single-to-multi',
        probability: 0,
        n_trials: 12,
      })
    );

    await chooseSelect(
      'Correction direction',
      'Overall multi-trial → single trial',
      panel
    );
    await replaceValue(within(panel).getByLabelText('Overall multi-trial probability'), '1');
    expect(within(panel).getByText(/must be less than 1/i)).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Correct probability' })).toBeDisabled();
  });

  it('sends exact PDS evaluate and detection payloads and preserves each operation result', async () => {
    apiMocks.evaluatePds.mockResolvedValueOnce(
      success(
        evaluationResult('pds', 24, {
          probability: 0,
          log_probability: -800,
          n_trials: 8,
          n_summed_spectra: 3,
          n_rebin: 2,
          warnings: ['Linear probability underflowed; use the natural-log probability.'],
        })
      )
    );
    apiMocks.detectPds.mockResolvedValueOnce(
      success(
        detectionResult('pds', {
          false_alarm_probability: 0.02,
          detection_level: 18.25,
          n_trials: 8,
          n_summed_spectra: 3,
          n_rebin: 2,
        })
      )
    );
    renderWithProviders(<StatisticalFunctionsPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Power spectrum' }));
    let panel = screen.getByRole('tabpanel');

    await replaceValue(within(panel).getByLabelText('Observed Leahy power'), '24');
    await replaceValue(within(panel).getByLabelText('Independent trials'), '8');
    await replaceValue(within(panel).getByLabelText('Averaged spectra'), '3');
    await replaceValue(within(panel).getByLabelText('Rebin factor'), '2');
    await userEvent.click(
      within(panel).getByRole('button', { name: 'Evaluate false-alarm probability' })
    );
    await waitFor(() =>
      expect(apiMocks.evaluatePds).toHaveBeenCalledWith({
        power: 24,
        n_trials: 8,
        n_summed_spectra: 3,
        n_rebin: 2,
      })
    );
    expect(await within(panel).findByText('-800')).toBeInTheDocument();
    expect(within(panel).getByText(/Linear probability underflowed/)).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Find detection level' }));
    await replaceValue(within(panel).getByLabelText('Overall false-alarm probability'), '0.02');
    await userEvent.click(within(panel).getByRole('button', { name: 'Calculate detection level' }));
    await waitFor(() =>
      expect(apiMocks.detectPds).toHaveBeenCalledWith({
        false_alarm_probability: 0.02,
        n_trials: 8,
        n_summed_spectra: 3,
        n_rebin: 2,
      })
    );
    expect(await within(panel).findByText('18.25')).toBeInTheDocument();
    expect(within(panel).getByText('observed_statistic >= detection_level')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Evaluate observation' }));
    panel = screen.getByRole('tabpanel');
    expect(within(panel).getByText('-800')).toBeInTheDocument();
  });

  it('disables duplicate submission while a request is running', async () => {
    let resolveRequest: ((value: ReturnType<typeof success<GaussianResult>>) => void) | undefined;
    apiMocks.gaussian.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );
    renderWithProviders(<StatisticalFunctionsPage />);
    const panel = screen.getByRole('tabpanel');

    await userEvent.click(within(panel).getByRole('button', { name: 'Convert to Gaussian sigma' }));
    const runningButton = within(panel).getByRole('button', { name: 'Calculating…' });
    expect(runningButton).toBeDisabled();
    expect(apiMocks.gaussian).toHaveBeenCalledTimes(1);

    resolveRequest?.(success(gaussianResult));
    expect(await within(panel).findByText('2.78215')).toBeInTheDocument();
  });

  it('shows an error while preserving the previous successful result', async () => {
    apiMocks.gaussian
      .mockResolvedValueOnce(success(gaussianResult))
      .mockResolvedValueOnce({
        success: false,
        data: null,
        message: 'Probability conversion failed',
        error: null,
      });
    renderWithProviders(<StatisticalFunctionsPage />);
    const panel = screen.getByRole('tabpanel');
    const submit = within(panel).getByRole('button', { name: 'Convert to Gaussian sigma' });

    await userEvent.click(submit);
    expect(await within(panel).findByText('2.78215')).toBeInTheDocument();
    await userEvent.click(submit);

    expect(await within(panel).findByText(/Probability conversion failed/)).toBeInTheDocument();
    expect(within(panel).getByText(/previous successful result remains/i)).toBeInTheDocument();
    expect(within(panel).getByText('2.78215')).toBeInTheDocument();
  });

  it('validates statistic domains and PDM sample/bin ordering before submission', async () => {
    renderWithProviders(<StatisticalFunctionsPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Phase dispersion' }));
    const panel = screen.getByRole('tabpanel');

    await replaceValue(within(panel).getByLabelText('Observed inverse PDM peak statistic'), '1.1');
    expect(within(panel).getByText(/PDM statistic must be at most 1/)).toBeInTheDocument();
    expect(
      within(panel).getByRole('button', { name: 'Evaluate false-alarm probability' })
    ).toBeDisabled();

    await replaceValue(within(panel).getByLabelText('Observed inverse PDM peak statistic'), '0.2');
    await replaceValue(within(panel).getByLabelText('Time-series samples'), '10');
    await replaceValue(within(panel).getByLabelText('Phase bins'), '10');
    expect(within(panel).getAllByText(/samples must be greater than phase bins/i).length).toBeGreaterThan(0);
    expect(
      within(panel).getByRole('button', { name: 'Evaluate false-alarm probability' })
    ).toBeDisabled();
    expect(apiMocks.evaluatePdm).not.toHaveBeenCalled();
  });

  it('uses exact Z², fold, and PDM payloads and surfaces the PDM lower-tail rule', async () => {
    renderWithProviders(<StatisticalFunctionsPage />);

    await userEvent.click(screen.getByRole('tab', { name: 'Z-squared' }));
    let panel = screen.getByRole('tabpanel');
    await replaceValue(within(panel).getByLabelText('Observed Z-squared statistic'), '30');
    await replaceValue(within(panel).getByLabelText('Harmonics'), '4');
    await replaceValue(within(panel).getByLabelText('Independent trials'), '5');
    await replaceValue(within(panel).getByLabelText('Averaged periodograms'), '2');
    await userEvent.click(within(panel).getByRole('button', { name: 'Evaluate false-alarm probability' }));
    await waitFor(() =>
      expect(apiMocks.evaluateZ2).toHaveBeenCalledWith({
        z2: 30,
        harmonics: 4,
        n_trials: 5,
        n_summed_spectra: 2,
      })
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Epoch folding' }));
    panel = screen.getByRole('tabpanel');
    await userEvent.click(within(panel).getByRole('button', { name: 'Find detection level' }));
    await replaceValue(within(panel).getByLabelText('Overall false-alarm probability'), '0.03');
    await replaceValue(within(panel).getByLabelText('Phase bins'), '32');
    await replaceValue(within(panel).getByLabelText('Independent trials'), '6');
    await userEvent.click(within(panel).getByRole('button', { name: 'Calculate detection level' }));
    await waitFor(() =>
      expect(apiMocks.detectFold).toHaveBeenCalledWith({
        false_alarm_probability: 0.03,
        n_phase_bins: 32,
        n_trials: 6,
      })
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Phase dispersion' }));
    panel = screen.getByRole('tabpanel');
    await userEvent.click(within(panel).getByRole('button', { name: 'Find detection level' }));
    await replaceValue(within(panel).getByLabelText('Overall false-alarm probability'), '0.02');
    await replaceValue(within(panel).getByLabelText('Time-series samples'), '120');
    await replaceValue(within(panel).getByLabelText('Phase bins'), '12');
    await replaceValue(within(panel).getByLabelText('Independent trials'), '9');
    await userEvent.click(within(panel).getByRole('button', { name: 'Calculate detection level' }));
    await waitFor(() =>
      expect(apiMocks.detectPdm).toHaveBeenCalledWith({
        false_alarm_probability: 0.02,
        n_samples: 120,
        n_phase_bins: 12,
        n_trials: 9,
      })
    );
    expect(await within(panel).findByText('observed_statistic <= detection_level')).toBeInTheDocument();
    expect(within(panel).getAllByText('lower tail').length).toBeGreaterThan(0);
  });
});
