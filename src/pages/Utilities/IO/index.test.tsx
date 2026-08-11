import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';
import type {
  ExportableObjectsResult,
  FileInspectionResult,
  RmfInspectionResult,
} from '@/api/ioApi';

const inspectFile = vi.fn();
const inspectRmf = vi.fn();
const convertPi = vi.fn();
const convertEventList = vi.fn();
const listExportableObjects = vi.fn();
const exportObject = vi.fn();
const listEventLists = vi.fn();

vi.mock('@/api/ioApi', () => ({
  ioApi: {
    inspectFile: (...args: unknown[]) => inspectFile(...args),
    inspectRmf: (...args: unknown[]) => inspectRmf(...args),
    convertPi: (...args: unknown[]) => convertPi(...args),
    convertEventList: (...args: unknown[]) => convertEventList(...args),
    listExportableObjects: (...args: unknown[]) => listExportableObjects(...args),
    exportObject: (...args: unknown[]) => exportObject(...args),
  },
}));

vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...args: unknown[]) => listEventLists(...args) },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="io-chart" />,
}));

import IOPage from './index';

const CAPABILITIES: ExportableObjectsResult['capability_matrix'] = {
  event_list: {
    csv: { supported: true, notes: 'Tabular only' },
    ecsv: { supported: true, notes: 'Metadata' },
    json: { supported: true, notes: 'Envelope' },
    fits: { supported: true, notes: 'Generic FITS with GTI' },
  },
  lightcurve: {
    csv: { supported: true, notes: 'Tabular only' },
    ecsv: { supported: true, notes: 'Metadata' },
    json: { supported: true, notes: 'Envelope' },
    fits: { supported: true, notes: 'Generic FITS' },
  },
  analysis_result: {
    csv: { supported: true, notes: 'Tabular only' },
    ecsv: { supported: true, notes: 'Metadata' },
    json: { supported: true, notes: 'Envelope' },
    fits: { supported: true, notes: 'Generic FITS' },
  },
};

function catalog(
  objects: ExportableObjectsResult['objects'] = []
): ExportableObjectsResult {
  return {
    objects,
    capability_matrix: CAPABILITIES,
    format_allowlist: ['csv', 'ecsv', 'json', 'fits'],
    excluded_formats: {
      pickle: 'Unsafe deserialization format',
      hdf5: 'Round trip not verified',
    },
    row_cap: 2_000_000,
    provenance: { operation: 'list_exportable_objects' },
  };
}

function success<T>(data: T, message = 'Done') {
  return { success: true, data, message, error: null };
}

const INSPECTION: FileInspectionResult = {
  path: '/science/events.fits',
  filename: 'events.fits',
  extension: '.fits',
  size_bytes: 4096,
  supported: true,
  detected_type: 'fits',
  hdus: [
    {
      index: 1,
      name: 'EVENTS',
      type: 'binary_table',
      row_count: 2,
      dimensions: [16, 2],
      columns: [
        { name: 'TIME', format: 'D', unit: 's' },
        { name: 'PI', format: 'J', unit: null },
      ],
      timing: {
        status: 'available',
        note: 'Exact split keyword reference',
        mjdref: {
          decimal: '58000.12345678901234568',
          stingray_value: '58000.12345678901235',
          source_keywords: { MJDREFI: '58000', MJDREFF: '0.12345678901234568' },
        },
        keywords: {
          MJDREFI: 58000,
          MJDREFF: 0.12345678901234568,
          TIMESYS: 'TT',
          TIMEUNIT: 's',
          TIMEZERO: 0,
          TSTART: 12.5,
          TSTOP: 42.5,
          CLOCKAPP: true,
        },
        high_precision_keywords: {
          TSTART: {
            decimal: '12.500000000000000001',
            stingray_value: '12.5',
            source_keywords: {
              TSTARTI: '12',
              TSTARTF: '0.500000000000000001',
            },
          },
        },
      },
    },
  ],
  warnings: [],
  provenance: { operation: 'inspect_file' },
};

const UNITLESS_RMF_INSPECTION: RmfInspectionResult = {
  path: '/calibration/unitless.rmf',
  filename: 'unitless.rmf',
  size_bytes: 2048,
  channel_count: 2,
  channel_min: 0,
  channel_max: 1,
  energy_min: 0.1,
  energy_max: 0.4,
  energy_unit: null,
  conversion_supported: false,
  contiguous_channels: true,
  preview_rows: [
    { channel: 0, energy_min: 0.1, energy_max: 0.2, energy_midpoint: 0.15 },
  ],
  preview_truncated: true,
  warnings: ['EBOUNDS energy units are missing.'],
  provenance: { operation: 'inspect_rmf' },
};

describe('General I/O Utilities page', () => {
  const originalElectronApi = window.electronAPI;

  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listExportableObjects.mockResolvedValue(success(catalog()));
    listEventLists.mockResolvedValue(
      success([
        { name: 'events', n_events: 3, time_range: [0, 2], has_pi: true },
        { name: 'already_loaded', n_events: 2, time_range: [0, 1], has_pi: true },
      ])
    );
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: originalElectronApi,
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: originalElectronApi,
    });
  });

  it('is ready and presents the verified capability matrix even with no loaded objects', async () => {
    renderWithProviders(<IOPage />);

    expect(screen.getByRole('heading', { name: 'General I/O Functionality' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Data Ingestion' })).toHaveAttribute(
      'href',
      '/data-ingestion'
    );
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Export / conversion' }));

    expect(await screen.findByText('No compatible loaded objects are available to export.')).toBeInTheDocument();
    expect(screen.getByText('Verified format compatibility')).toBeInTheDocument();
    expect(screen.getAllByText(/Supported — Tabular only/).length).toBeGreaterThan(0);
    expect(screen.getByText(/PICKLE: Unsafe deserialization format/)).toBeInTheDocument();
  });

  it('preserves a native file selection on cancellation and sends the exact inspection payload', async () => {
    const openGrantedFile = vi
      .fn()
      .mockResolvedValueOnce([{ path: '/science/events.fits', grant: 'read-grant' }])
      .mockResolvedValueOnce(null);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { ...originalElectronApi, openGrantedFile },
    });
    inspectFile.mockResolvedValue(success(INSPECTION));
    renderWithProviders(<IOPage />);

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(screen.getByLabelText('Scientific file')).toHaveValue('/science/events.fits');
    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(screen.getByLabelText('Scientific file')).toHaveValue('/science/events.fits');

    await userEvent.click(screen.getByRole('button', { name: 'Inspect file' }));
    expect(inspectFile).toHaveBeenCalledWith({
      file_path: '/science/events.fits',
      file_grant: 'read-grant',
    });
    expect(await screen.findByText('58000.12345678901234568')).toBeInTheDocument();
    expect(screen.getByText('58000.12345678901235')).toBeInTheDocument();
    expect(screen.getAllByText(/TSTART=12\.5/).length).toBeGreaterThan(0);
    expect(screen.getByText(/CLOCKAPP=true/)).toBeInTheDocument();
    expect(screen.getByText(/TSTART=12.500000000000000001/)).toBeInTheDocument();
    expect(screen.getAllByText('EVENTS').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('tab', { name: 'RMF utilities' }));
    await userEvent.click(screen.getByRole('tab', { name: 'File inspector' }));
    expect(screen.getByText('58000.12345678901234568')).toBeVisible();
  });

  it('recognizes exact non-MJD timing metadata as available for display', async () => {
    const openGrantedFile = vi.fn().mockResolvedValue([
      { path: '/science/timing-only.fits', grant: 'read-grant' },
    ]);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { ...originalElectronApi, openGrantedFile },
    });
    inspectFile.mockResolvedValue(
      success({
        ...INSPECTION,
        path: '/science/timing-only.fits',
        hdus: INSPECTION.hdus.map((hdu) => ({
          ...hdu,
          timing: {
            ...hdu.timing,
            status: 'missing' as const,
            mjdref: null,
            keywords: { TSTART: 12.5, TSTOP: 42.5, TIMEUNIT: 's' },
          },
        })),
      })
    );
    renderWithProviders(<IOPage />);

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    await userEvent.click(screen.getByRole('button', { name: 'Inspect file' }));

    expect(await screen.findByText(/TSTART=12.500000000000000001/)).toBeInTheDocument();
    expect(
      screen.queryByText(/No unambiguous time-reference metadata was found/)
    ).not.toBeInTheDocument();
  });

  it('clears a completed file inspection when a different file is selected', async () => {
    const openGrantedFile = vi
      .fn()
      .mockResolvedValueOnce([{ path: '/science/events.fits', grant: 'first-grant' }])
      .mockResolvedValueOnce([{ path: '/science/other.fits', grant: 'second-grant' }]);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { ...originalElectronApi, openGrantedFile },
    });
    inspectFile.mockResolvedValue(success(INSPECTION));
    renderWithProviders(<IOPage />);

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    await userEvent.click(screen.getByRole('button', { name: 'Inspect file' }));
    expect(await screen.findByText('58000.12345678901234568')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(screen.getByLabelText('Scientific file')).toHaveValue('/science/other.fits');
    expect(screen.queryByText('58000.12345678901234568')).not.toBeInTheDocument();
    expect(screen.getByText(/Choose a file to inspect/)).toBeInTheDocument();
  });

  it('does not invent keV for a unitless RMF and clears results after RMF changes', async () => {
    const openGrantedFile = vi
      .fn()
      .mockResolvedValueOnce([{ path: '/calibration/unitless.rmf', grant: 'first-grant' }])
      .mockResolvedValueOnce([{ path: '/calibration/other.rmf', grant: 'second-grant' }]);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { ...originalElectronApi, openGrantedFile },
    });
    inspectRmf.mockResolvedValue(success(UNITLESS_RMF_INSPECTION));
    renderWithProviders(<IOPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'RMF utilities' }));

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    await userEvent.click(screen.getByRole('button', { name: 'Inspect RMF' }));

    expect(await screen.findByText('Energy range (unit not declared)')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Energy low' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Energy low (keV)' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(screen.getByLabelText('RMF file')).toHaveValue('/calibration/other.rmf');
    expect(screen.queryByLabelText('RMF inspection result')).not.toBeInTheDocument();
  });

  it('rejects fractional PI locally, then converts valid channels with the exact RMF payload', async () => {
    const openGrantedFile = vi
      .fn()
      .mockResolvedValueOnce([
        { path: '/calibration/response.rmf', grant: 'rmf-grant' },
      ])
      .mockResolvedValueOnce([
        { path: '/calibration/replacement.rmf', grant: 'replacement-grant' },
      ]);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { ...originalElectronApi, openGrantedFile },
    });
    convertPi.mockResolvedValue(
      success({
        rows: [
          { index: 0, pi: 0, energy: 0.15 },
          { index: 1, pi: 2, energy: 0.6 },
        ],
        count: 2,
        energy_unit: 'keV',
        plot: { arrays: [[0, 2], [0.15, 0.6]], stride: 1, source_points: 2 },
        warnings: ['Exact EBOUNDS channel matches were required.'],
        provenance: { operation: 'rmf_pi_to_energy' },
      })
    );
    renderWithProviders(<IOPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'RMF utilities' }));
    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));

    const piField = screen.getByLabelText('PI values');
    await userEvent.type(piField, '0, 1.5');
    expect(screen.getByText('PI value 2 must be a non-negative integer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Convert PI values' })).toBeDisabled();
    expect(convertPi).not.toHaveBeenCalled();

    await userEvent.clear(piField);
    await userEvent.type(piField, '0, 2');
    await userEvent.click(screen.getByRole('button', { name: 'Convert PI values' }));
    expect(convertPi).toHaveBeenCalledWith({
      pi_values: [0, 2],
      rmf_path: '/calibration/response.rmf',
      rmf_grant: 'rmf-grant',
    });
    expect(await screen.findByTestId('io-chart')).toBeInTheDocument();
    expect(screen.getByText('Exact EBOUNDS channel matches were required.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(screen.queryByTestId('io-chart')).not.toBeInTheDocument();
  });

  it('shows loading and errors while preserving the previous successful inspection', async () => {
    const openGrantedFile = vi.fn().mockResolvedValue([
      { path: '/science/events.fits', grant: 'read-grant' },
    ]);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { ...originalElectronApi, openGrantedFile },
    });
    inspectFile.mockResolvedValueOnce(
      success({ ...INSPECTION, warnings: ['Retained inspection advisory.'] })
    );
    renderWithProviders(<IOPage />);
    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    await userEvent.click(screen.getByRole('button', { name: 'Inspect file' }));
    expect(await screen.findByText('58000.12345678901234568')).toBeInTheDocument();

    let resolveFailure: ((value: unknown) => void) | undefined;
    inspectFile.mockImplementationOnce(
      () => new Promise((resolve) => { resolveFailure = resolve; })
    );
    await userEvent.click(screen.getByRole('button', { name: 'Inspect file' }));
    expect(screen.getByRole('button', { name: 'Inspecting…' })).toBeDisabled();
    resolveFailure?.({
      success: false,
      data: null,
      message: 'Malformed FITS',
      error: 'Invalid header',
      warnings: ['Failure-specific FITS advisory.'],
    });

    expect(await screen.findByText('Invalid header')).toBeInTheDocument();
    expect(screen.getByText('Failure-specific FITS advisory.')).toBeInTheDocument();
    expect(screen.getByText('Retained inspection advisory.')).toBeInTheDocument();
    expect(screen.getByText('58000.12345678901234568')).toBeInTheDocument();
  });

  it('binds save-dialog extension to the selected format, preserves cancellation, and exports exactly', async () => {
    listExportableObjects.mockResolvedValue(
      success(
        catalog([
          {
            object_type: 'event_list',
            name: 'events',
            row_count: 3,
            exportable: true,
            formats: ['fits', 'csv'],
            reason: null,
          },
          {
            object_type: 'analysis_result',
            name: 'not_tabular',
            row_count: null,
            exportable: false,
            formats: [],
            reason: 'No one-dimensional columns',
          },
        ])
      )
    );
    const saveGrantedFile = vi
      .fn()
      .mockResolvedValueOnce({ path: '/exports/events.csv', grant: 'write-grant' })
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce(new Error('save dialog process failed'));
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { ...originalElectronApi, saveGrantedFile },
    });
    exportObject.mockResolvedValue(
      success({
        path: '/exports/events.csv',
        bytes: 128,
        format: 'csv',
        row_count: 3,
        object_type: 'event_list',
        object_name: 'events',
        verified: true,
        warnings: ['CSV stores tabular values only.'],
        provenance: { operation: 'export_loaded_object' },
      })
    );
    renderWithProviders(<IOPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Export / conversion' }));
    await screen.findByLabelText('Loaded object');

    await userEvent.click(screen.getByLabelText('Loaded object'));
    expect(screen.getByRole('option', { name: /not_tabular/ })).toHaveAttribute('aria-disabled', 'true');
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByLabelText('Format'));
    await userEvent.click(screen.getByRole('option', { name: 'CSV' }));
    expect(screen.getByText(/CSV scientific-data behavior:/)).toBeInTheDocument();
    expect(screen.getAllByText('Tabular only').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('button', { name: 'Choose destination' }));
    expect(saveGrantedFile).toHaveBeenLastCalledWith({
      title: 'Export events',
      defaultPath: 'events.csv',
      filters: [{ name: 'CSV', extensions: ['csv'] }],
    });
    expect(screen.getByLabelText('Destination')).toHaveValue('/exports/events.csv');

    await userEvent.click(screen.getByRole('button', { name: 'Choose destination' }));
    expect(screen.getByLabelText('Destination')).toHaveValue('/exports/events.csv');
    await userEvent.click(screen.getByRole('button', { name: 'Choose destination' }));
    expect(await screen.findByText(/save dialog process failed/)).toBeInTheDocument();
    expect(screen.getByLabelText('Destination')).toHaveValue('/exports/events.csv');
    await userEvent.click(screen.getByRole('button', { name: 'Export' }));
    expect(exportObject).toHaveBeenCalledWith({
      object_type: 'event_list',
      object_name: 'events',
      format: 'csv',
      destination_path: '/exports/events.csv',
      destination_grant: 'write-grant',
    });
    expect(await screen.findByText('Reopened / verified')).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText('Format'));
    await userEvent.click(screen.getByRole('option', { name: 'FITS' }));
    expect(screen.getByLabelText('Destination')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Export' })).toBeDisabled();
  });

  it('requires a unique derived name and sends an explicit save-as conversion', async () => {
    const initialObjects: ExportableObjectsResult['objects'] = [
      {
        object_type: 'event_list',
        name: 'events',
        row_count: 3,
        exportable: true,
        formats: ['fits', 'csv'],
        reason: null,
      },
      {
        object_type: 'event_list',
        name: 'already_loaded',
        row_count: 2,
        exportable: true,
        formats: ['fits'],
        reason: null,
      },
    ];
    listExportableObjects
      .mockResolvedValueOnce(success(catalog(initialObjects)))
      .mockResolvedValue(
        success(
          catalog([
            ...initialObjects,
            {
              object_type: 'event_list',
              name: 'events_calibrated',
              row_count: 3,
              exportable: true,
              formats: ['fits', 'csv'],
              reason: null,
            },
          ])
        )
      );
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: {
        ...originalElectronApi,
        openGrantedFile: vi.fn().mockResolvedValue([
          { path: '/calibration/response.rmf', grant: 'rmf-grant' },
        ]),
      },
    });
    convertEventList
      .mockResolvedValueOnce(
        success({
          source_name: 'events',
          saved: false,
          saved_name: null,
          event_count: 3,
          energy_unit: 'keV',
          preview_rows: [{ index: 0, pi: 0, energy: 0.15 }],
          preview_truncated: true,
          plot: { arrays: [[0], [0.15]], stride: 3, source_points: 3 },
          pi_preserved: true,
          warnings: [],
          provenance: { operation: 'rmf_event_list_pi_to_energy' },
        })
      )
      .mockResolvedValueOnce(success({
        source_name: 'events',
        saved: true,
        saved_name: 'events_calibrated',
        event_count: 3,
        energy_unit: 'keV',
        preview_rows: [{ index: 0, pi: 0, energy: 0.15 }],
        preview_truncated: true,
        plot: { arrays: [[0], [0.15]], stride: 3, source_points: 3 },
        pi_preserved: true,
        warnings: [],
        provenance: { operation: 'rmf_event_list_pi_to_energy' },
      }));
    renderWithProviders(<IOPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'RMF utilities' }));
    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    await userEvent.click(await screen.findByLabelText('Source EventList'));
    await userEvent.click(screen.getByRole('option', { name: /events \(3 events\)/ }));

    await userEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
    expect(convertEventList).toHaveBeenLastCalledWith({
      event_list_name: 'events',
      rmf_path: '/calibration/response.rmf',
      rmf_grant: 'rmf-grant',
      save_as: null,
    });
    expect(await screen.findByText(/no object was saved and the source was not modified/)).toBeInTheDocument();

    const saveAs = screen.getByLabelText('Save as (new EventList name)');
    await userEvent.type(saveAs, 'events');
    expect(screen.getByText('Destination name must differ from the source EventList')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Convert and save derived EventList' })).toBeDisabled();
    await userEvent.clear(saveAs);
    await userEvent.type(saveAs, 'already_loaded');
    expect(screen.getByText(/already_loaded.*already exists/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Convert and save derived EventList' })).toBeDisabled();
    await userEvent.clear(saveAs);
    await userEvent.type(saveAs, 'events_calibrated');
    await userEvent.click(screen.getByRole('button', { name: 'Convert and save derived EventList' }));

    expect(convertEventList).toHaveBeenLastCalledWith({
      event_list_name: 'events',
      rmf_path: '/calibration/response.rmf',
      rmf_grant: 'rmf-grant',
      save_as: 'events_calibrated',
    });
    expect(await screen.findByText(/Saved events_calibrated with 3 events/)).toBeInTheDocument();
    await waitFor(() => expect(listExportableObjects).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/events_calibrated.*already exists/)).toBeInTheDocument();

    const saveButton = screen.getByRole('button', {
      name: 'Convert and save derived EventList',
    });
    expect(saveButton).toBeDisabled();
    fireEvent.click(saveButton);
    expect(convertEventList).toHaveBeenCalledTimes(2);
  });
});
