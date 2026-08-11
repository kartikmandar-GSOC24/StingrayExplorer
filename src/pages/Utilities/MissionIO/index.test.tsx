import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...args: unknown[]) => listEventLists(...args) },
}));

const getCapabilities = vi.fn();
const getMissionInfo = vi.fn();
const identify = vi.fn();
const convertPi = vi.fn();
const interpret = vi.fn();
vi.mock('@/api/missionIoApi', () => ({
  missionIoApi: {
    getCapabilities: (...args: unknown[]) => getCapabilities(...args),
    getMissionInfo: (...args: unknown[]) => getMissionInfo(...args),
    identify: (...args: unknown[]) => identify(...args),
    convertPi: (...args: unknown[]) => convertPi(...args),
    interpret: (...args: unknown[]) => interpret(...args),
  },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="mission-conversion-chart" />,
}));

vi.mock('@/components/utilities/GrantedFileField', () => ({
  default: ({
    label,
    onChange,
  }: {
    label: string;
    onChange: (value: { path: string; grant: string }) => void;
  }) => (
    <button
      type="button"
      aria-label={`Choose ${label}`}
      onClick={() => onChange({ path: '/selected/mission.evt', grant: 'read-grant' })}
    >
      Choose {label}
    </button>
  ),
}));

import MissionIOPage from './index';

const mapping = {
  event_hdu: 'EVENTS',
  gti_hdu: 'GTI',
  time_column: 'TIME',
  energy_or_channel_column: 'PI',
  detector_column: 'DET_ID',
  instrument_keyword: 'INSTRUME',
  mode_keyword: 'DATAMODE',
};

const field = (
  value: string | null,
  sourceType: 'event_list_attribute' | 'fits_header' | 'override' | 'missing',
  source: string | null
) => ({
  value,
  raw_value: value,
  source,
  source_type: sourceType,
  inferred: false,
  override: sourceType === 'override',
});

const capabilitiesData = {
  missions: [
    {
      mission: 'nicer',
      mapping,
      instruments: ['XTI'],
      modes: ['EVENT'],
      rough_pi_to_energy: {
        status: 'unsupported' as const,
        approximate: false,
        dependencies: [],
        message: 'No public rough PI-to-energy conversion is available.',
      },
      specialized_interpretation: { supported: false, scope: null },
    },
    {
      mission: 'xte',
      mapping,
      instruments: ['PCA'],
      modes: ['GoodXenon'],
      rough_pi_to_energy: {
        status: 'conditional' as const,
        approximate: true,
        dependencies: ['mission', 'instrument=PCA', 'epoch_mjd', 'detector_id'],
        message: 'Approximate RXTE PCA conversion requires epoch and PCU.',
      },
      specialized_interpretation: {
        supported: true,
        scope: 'XTE PCA science-event FITS (XTE_SE, TEVTB2 and PHA)',
      },
    },
  ],
  mission_count: 2,
  raw_database_entry_count: 3,
  database_source: 'runtime stingray.mission_support.read_mission_info',
  support_note: 'Mappings do not imply conversion or interpreter support.',
  precise_calibration: { method: 'RMF-based PI-to-energy conversion', location: 'General I/O' },
  provenance: { operation: 'mission_io.list_capabilities', read_only: true },
  warnings: [],
};

const identificationData = {
  source: { type: 'loaded_event_list', name: 'obs1' },
  mission: {
    ...field('NICER', 'fits_header' as const, 'EventList.header:MISSION'),
    database_supported: true,
  },
  instrument: field('XTI', 'event_list_attribute', 'EventList.instr'),
  mode: field(null, 'missing', null),
  mapping,
  timing_metadata: {
    mjdref: {
      value: 56658.00077759259,
      decimal: '56658.000777592592592593',
      source: 'EventList.header:MJDREFI + EventList.header:MJDREFF',
      components: {
        integer: { value: '56658', source: 'EventList.header:MJDREFI' },
        fraction: {
          value: '0.000777592592592593',
          source: 'EventList.header:MJDREFF',
        },
      },
    },
    tstart: { value: 12.5, source: 'EventList.header:TSTART' },
  },
  provenance: { operation: 'mission_io.identify_source', read_only: true },
  warnings: ['Observing-mode metadata is missing.'],
};

const missionInfoData = {
  mission: 'xte',
  requested_mission: 'xte',
  mission_name_inferred: false,
  instrument: 'PCA',
  mode: null,
  mapping,
  available_instruments: ['PCA'],
  available_modes: ['GoodXenon'],
  capabilities: {
    rough_pi_to_energy: {
      status: 'conditional' as const,
      approximate: true,
      dependencies: ['instrument=PCA', 'epoch_mjd', 'detector_id'],
    },
    specialized_interpretation: {
      supported: true,
      scope: 'XTE PCA science-event FITS (XTE_SE, TEVTB2 and PHA)',
    },
  },
  precise_calibration: { method: 'RMF-based PI-to-energy conversion', location: 'General I/O' },
  provenance: { operation: 'mission_io.get_mission_info', read_only: true },
  warnings: [],
};

const conversionData = (
  saved: string | null = null,
  requestedEpoch: number | null = null
) => ({
  label: 'APPROXIMATE rough PI-to-energy conversion',
  conversion_type: 'rough_approximate' as const,
  approximate: true as const,
  energy_unit: 'keV' as const,
  mission: field('nicer', 'override', 'request.mission_override'),
  instrument: field(null, 'missing', null),
  mode: field(null, 'missing', null),
  dependencies: {
    mission: { required: true, value: 'nicer' },
    epoch_mjd: {
      required: false,
      used: false,
      value: null,
      requested_value: requestedEpoch,
      source: null,
    },
  },
  count: 3,
  rows: [
    { index: 0, pi: 1, energy_kev: 0.01 },
    { index: 1, pi: 2, energy_kev: 0.02 },
    { index: 2, pi: 3, energy_kev: 0.03 },
  ],
  preview_count: 3,
  preview_truncated: false,
  saved_event_list: saved,
  precise_calibration: { method: 'RMF-based PI-to-energy conversion', location: 'General I/O' },
  provenance: { operation: 'mission_io.approximate_pi_to_energy', approximate: true },
  warnings: ['APPROXIMATE conversion: use RMF calibration for precise energies.'],
});

async function selectEventList(label: string, option: RegExp): Promise<void> {
  await userEvent.click(await screen.findByLabelText(label));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

async function openTab(name: string): Promise<void> {
  await userEvent.click(screen.getByRole('tab', { name }));
}

describe('MissionIOPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockReset();
    getCapabilities.mockReset();
    getMissionInfo.mockReset();
    identify.mockReset();
    convertPi.mockReset();
    interpret.mockReset();

    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 3, time_range: [0, 2], has_pi: true }],
      message: '',
      error: null,
    });
    getCapabilities.mockResolvedValue({
      success: true,
      data: capabilitiesData,
      message: 'capabilities',
      error: null,
    });
    identify.mockResolvedValue({
      success: true,
      data: identificationData,
      message: 'identified',
      error: null,
    });
    getMissionInfo.mockResolvedValue({
      success: true,
      data: missionInfoData,
      message: 'mapping',
      error: null,
    });
    convertPi.mockImplementation((params: { save_as?: string; epoch_mjd?: number }) =>
      Promise.resolve({
        success: true,
        data: conversionData(params.save_as ?? null, params.epoch_mjd ?? null),
        message: 'converted',
        error: null,
      })
    );
    interpret.mockResolvedValue({
      success: false,
      data: null,
      message: "Stingray 2.2.10 has no specialized event interpretation for mission 'nicer'.",
      error: null,
    });
  });

  it('starts ready, exposes the four tools, and keeps identify disabled for an empty source', async () => {
    listEventLists.mockResolvedValueOnce({ success: true, data: [], message: '', error: null });
    renderWithProviders(<MissionIOPage />);

    expect(screen.getByText('Mission-Specific I/O')).toBeInTheDocument();
    expect(screen.queryByText(/under construction/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(4);
    expect(screen.getByRole('button', { name: 'Identify mission' })).toBeDisabled();
    expect(await screen.findByText(/No event lists loaded/)).toBeInTheDocument();
  });

  it('identifies a loaded EventList with an exact payload and renders value sources', async () => {
    renderWithProviders(<MissionIOPage />);
    await selectEventList('EventList to identify', /obs1/);
    await userEvent.click(screen.getByRole('button', { name: 'Identify mission' }));

    await waitFor(() => expect(identify).toHaveBeenCalledWith({ event_list_name: 'obs1' }));
    expect(await screen.findByText('NICER')).toBeInTheDocument();
    expect(screen.getByText('FITS header')).toBeInTheDocument();
    expect(screen.getByText('EventList attribute')).toBeInTheDocument();
    expect(screen.getByText(/Source: EventList.header:MISSION/)).toBeInTheDocument();
    expect(screen.getByText('56658.000777592592592593')).toBeInTheDocument();
    expect(screen.getByText(/MJDREFI=56658/)).toBeInTheDocument();
    expect(screen.getByText(/tstart:/)).toBeInTheDocument();
    expect(screen.getByText('Observing-mode metadata is missing.')).toBeInTheDocument();
    expect(screen.getByText(/mission_io.identify_source/)).toBeInTheDocument();
  });

  it('handles missing mission metadata without dereferencing an absent mapping', async () => {
    identify.mockResolvedValueOnce({
      success: true,
      data: {
        source: { type: 'loaded_event_list', name: 'obs1' },
        mission: field(null, 'missing', null),
        instrument: field(null, 'missing', null),
        mode: field(null, 'missing', null),
        mapping: null,
        warnings: ['Mission metadata is missing.'],
      },
      message: 'identified with missing metadata',
      error: null,
    });
    renderWithProviders(<MissionIOPage />);
    await selectEventList('EventList to identify', /obs1/);
    await userEvent.click(screen.getByRole('button', { name: 'Identify mission' }));

    expect(await screen.findByText('Mission metadata is missing.')).toBeInTheDocument();
    expect(screen.getAllByText('Not identified')).toHaveLength(3);
    expect(
      screen.getByText(/No runtime FITS mapping is available until a supported mission/i)
    ).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Runtime FITS mapping' })).not.toBeInTheDocument();
  });

  it('shows runtime support honestly for unsupported and specialized missions', async () => {
    renderWithProviders(<MissionIOPage />);
    await openTab('Mission database');

    expect(await screen.findByText('2 unique mission mappings')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Runtime mission capability table' })).toBeInTheDocument();
    expect(screen.getByText('No public rough PI-to-energy conversion is available.')).toBeInTheDocument();
    expect(screen.getByText('Not available')).toBeInTheDocument();
    expect(screen.getByText('XTE PCA science-event FITS (XTE_SE, TEVTB2 and PHA)')).toBeInTheDocument();
    expect(screen.getByText(/mission_io.list_capabilities/)).toBeInTheDocument();
  });

  it('renders provenance for a selected runtime mission mapping', async () => {
    renderWithProviders(<MissionIOPage />);
    await openTab('Mission database');
    await screen.findByText('2 unique mission mappings');

    await userEvent.click(screen.getByLabelText('Mission'));
    await userEvent.click(screen.getByRole('option', { name: 'xte' }));
    await userEvent.type(screen.getByLabelText('Instrument (optional)'), 'PCA');
    await userEvent.click(screen.getByRole('button', { name: 'Inspect mission mapping' }));

    await waitFor(() =>
      expect(getMissionInfo).toHaveBeenCalledWith({ mission: 'xte', instrument: 'PCA' })
    );
    expect(await screen.findByText(/mission_io.get_mission_info/)).toBeInTheDocument();
  });

  it('validates pasted PI channels and sends the exact approximate-conversion payload', async () => {
    renderWithProviders(<MissionIOPage />);
    await openTab('Approximate conversion');

    const runButton = screen.getByRole('button', { name: 'Run approximate conversion' });
    expect(runButton).toBeDisabled();
    expect(screen.getByText(/mission override is required for pasted PI channels/i)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('PI values'), '1 2.5 3');
    expect(screen.getByText(/must be a non-negative integer channel/)).toBeInTheDocument();
    expect(runButton).toBeDisabled();

    await userEvent.clear(screen.getByLabelText('PI values'));
    await userEvent.type(screen.getByLabelText('PI values'), '1, 2, 3');
    await userEvent.type(screen.getByLabelText(/Mission override \(required\)/), 'nicer');
    expect(runButton).toBeEnabled();
    await userEvent.click(runButton);

    await waitFor(() =>
      expect(convertPi).toHaveBeenCalledWith({
        pi_values: [1, 2, 3],
        mission_override: 'nicer',
      })
    );
    expect(await screen.findByText('APPROXIMATE rough PI-to-energy conversion')).toBeInTheDocument();
    expect(screen.getByText(/not a substitute for RMF calibration/i)).toBeInTheDocument();
    expect(screen.getByTestId('mission-conversion-chart')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Approximate converted values' })).toBeInTheDocument();
  });

  it('labels a requested non-XTE epoch as unused', async () => {
    renderWithProviders(<MissionIOPage />);
    await openTab('Approximate conversion');
    await userEvent.type(screen.getByLabelText('PI values'), '1, 2, 3');
    await userEvent.type(screen.getByLabelText(/Mission override \(required\)/), 'nicer');
    await userEvent.type(screen.getByLabelText(/Observation epoch/), '60000');
    await userEvent.click(screen.getByRole('button', { name: 'Run approximate conversion' }));

    await waitFor(() =>
      expect(convertPi).toHaveBeenCalledWith({
        pi_values: [1, 2, 3],
        mission_override: 'nicer',
        epoch_mjd: 60000,
      })
    );
    expect(
      await screen.findByText('epoch_mjd: requested 60000; not used')
    ).toBeInTheDocument();
  });

  it('enforces RXTE PCA dependencies, PI range, and detector cardinality before submit', async () => {
    renderWithProviders(<MissionIOPage />);
    await openTab('Approximate conversion');

    const piField = screen.getByLabelText('PI values');
    const missionField = screen.getByLabelText(/Mission override \(required\)/);
    const instrumentField = screen.getByLabelText('Instrument override (if missing)');
    const epochField = screen.getByLabelText(/Observation epoch/);
    const detectorField = screen.getByLabelText(/Detector IDs/);
    const runButton = screen.getByRole('button', { name: 'Run approximate conversion' });

    await userEvent.type(piField, '1, 256, 3');
    await userEvent.type(missionField, 'XTE');
    expect(screen.getByText(/requires instrument override PCA/)).toBeInTheDocument();
    expect(screen.getAllByText(/requires an observation epoch/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/requires detector IDs/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/channel range 0-255/).length).toBeGreaterThan(0);
    expect(runButton).toBeDisabled();

    await userEvent.type(instrumentField, 'HEXTE');
    expect(screen.getByText(/supports only the PCA instrument/)).toBeInTheDocument();
    await userEvent.clear(instrumentField);
    await userEvent.type(instrumentField, 'PCA');
    await userEvent.type(epochField, '0b10');
    expect(
      screen.getAllByText(/Epoch MJD must be a positive finite number/).length
    ).toBeGreaterThan(0);
    expect(runButton).toBeDisabled();
    await userEvent.clear(epochField);
    await userEvent.type(epochField, '50081');
    expect(screen.getAllByText(/50081 < epoch MJD ≤ 55931/).length).toBeGreaterThan(0);
    expect(runButton).toBeDisabled();
    await userEvent.clear(epochField);
    await userEvent.type(epochField, '55931');
    await userEvent.type(detectorField, '0, 1');
    expect(screen.getAllByText(/one detector ID to broadcast or 3 IDs/).length).toBeGreaterThan(0);

    await userEvent.clear(detectorField);
    await userEvent.type(detectorField, '0');
    await userEvent.clear(piField);
    await userEvent.type(piField, '1, 2, 3');
    expect(runButton).toBeEnabled();
    await userEvent.click(runButton);

    await waitFor(() =>
      expect(convertPi).toHaveBeenCalledWith({
        pi_values: [1, 2, 3],
        mission_override: 'XTE',
        instrument_override: 'PCA',
        epoch_mjd: 55931,
        detector_ids: [0],
      })
    );
  });

  it('rejects zero-valued pasted AXAF channels before submit', async () => {
    renderWithProviders(<MissionIOPage />);
    await openTab('Approximate conversion');
    await userEvent.type(screen.getByLabelText('PI values'), '0, 1');
    await userEvent.type(screen.getByLabelText(/Mission override \(required\)/), 'AXAF');

    expect(screen.getByText(/must be at least 1 for AXAF\/Chandra/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run approximate conversion' })).toBeDisabled();
    expect(convertPi).not.toHaveBeenCalled();
  });

  it('uses an explicit validated Save-as name for a detached EventList', async () => {
    listEventLists.mockResolvedValueOnce({
      success: true,
      data: [
        { name: 'obs1', n_events: 3, time_range: [0, 2], has_pi: true },
        { name: 'already-loaded', n_events: 2, time_range: [0, 1], has_pi: true },
      ],
      message: '',
      error: null,
    });
    renderWithProviders(<MissionIOPage />);
    await openTab('Approximate conversion');
    await userEvent.click(screen.getByRole('radio', { name: 'Loaded EventList' }));
    await selectEventList('EventList with PI channels', /obs1/);
    await userEvent.click(screen.getByRole('checkbox', { name: /Save converted data/ }));

    const saveName = screen.getByLabelText('Save as EventList name');
    await userEvent.type(saveName, ' bad');
    expect(screen.getByText(/must not start or end with whitespace/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run approximate conversion' })).toBeDisabled();

    await userEvent.clear(saveName);
    await userEvent.type(saveName, 'already-loaded');
    expect(screen.getByText(/already-loaded.*already exists/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run approximate conversion' })).toBeDisabled();

    await userEvent.clear(saveName);
    await userEvent.type(saveName, 'obs1-energy');
    await userEvent.click(screen.getByRole('button', { name: 'Run approximate conversion' }));

    await waitFor(() =>
      expect(convertPi).toHaveBeenCalledWith({
        event_list_name: 'obs1',
        save_as: 'obs1-energy',
      })
    );
    expect(await screen.findByText('Saved as obs1-energy')).toBeInTheDocument();
  });

  it('shows loading and preserves the last identification after a later failure', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined;
    identify.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        })
    );
    renderWithProviders(<MissionIOPage />);
    await selectEventList('EventList to identify', /obs1/);
    await userEvent.click(screen.getByRole('button', { name: 'Identify mission' }));
    expect(screen.getByRole('button', { name: 'Identifying…' })).toBeDisabled();

    await act(async () => {
      resolveFirst?.({
        success: true,
        data: identificationData,
        message: 'identified',
        error: null,
      });
    });
    expect(await screen.findByText('NICER')).toBeInTheDocument();

    identify.mockResolvedValueOnce({
      success: false,
      data: null,
      message: 'Mission metadata could not be read',
      error: null,
      warnings: ['The selected source remains unmodified.'],
    });
    await userEvent.click(screen.getByRole('button', { name: 'Identify mission' }));
    expect(await screen.findByText('Mission metadata could not be read')).toBeInTheDocument();
    expect(screen.getByText('The selected source remains unmodified.')).toBeInTheDocument();
    expect(screen.getByText('NICER')).toBeInTheDocument();
  });

  it('submits a granted FITS path and reports unsupported specialized interpretation', async () => {
    renderWithProviders(<MissionIOPage />);
    await openTab('Specialized interpretation');
    expect(await screen.findByText(/xte: xte pca science-event fits/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Choose FITS file to interpret' }));
    await userEvent.type(screen.getByLabelText('Mission override (if missing)'), 'nicer');
    await userEvent.click(screen.getByRole('button', { name: 'Interpret selected FITS' }));

    await waitFor(() =>
      expect(interpret).toHaveBeenCalledWith({
        file_path: '/selected/mission.evt',
        file_grant: 'read-grant',
        mission_override: 'nicer',
      })
    );
    expect(
      await screen.findByText(/no specialized event interpretation for mission 'nicer'/i)
    ).toBeInTheDocument();
  });
});
