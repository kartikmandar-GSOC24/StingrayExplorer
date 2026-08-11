import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DataIngestionPage, {
  detectFormatFromExtension,
  getLastLoadedFiles,
  mergeGrantedSelections,
  saveLastLoadedFiles,
  validateRemoteSourceUrl,
} from './index';

const mocks = vi.hoisted(() => ({
  addNotification: vi.fn(),
  getPort: vi.fn().mockResolvedValue(8765),
  listEventLists: vi.fn(),
  checkFileSize: vi.fn(),
  checkBatchFileSize: vi.fn(),
  listExportableObjects: vi.fn(),
  exportObject: vi.fn(),
}));

vi.mock('@/api/client', () => ({ apiClient: { getPort: mocks.getPort } }));
vi.mock('@/api/dataApi', () => ({
  dataApi: {
    listEventLists: mocks.listEventLists,
    checkFileSize: mocks.checkFileSize,
    checkBatchFileSize: mocks.checkBatchFileSize,
  },
}));
vi.mock('@/api/jobApi', () => ({ jobApi: {} }));
vi.mock('@/api/ioApi', () => ({
  ioApi: {
    listExportableObjects: mocks.listExportableObjects,
    exportObject: mocks.exportObject,
  },
}));
vi.mock('@/store/uiStore', () => ({
  useUIStore: () => ({ addNotification: mocks.addNotification }),
}));
vi.mock('@/store/jobStore', () => ({ useJobStore: () => ({ jobs: {} }) }));
vi.mock('./HeasarcBrowserPanel', () => ({ default: () => null }));

const exportCapabilityResponse = (...names: string[]) => ({
  success: true,
  data: {
    objects: names.map((name) => ({
      object_type: 'event_list',
      name,
      row_count: 2,
      exportable: true,
      formats: ['ecsv'],
      reason: null,
    })),
    capability_matrix: {
      event_list: {
        ecsv: { supported: true, notes: 'Verified ECSV' },
        hdf5: { supported: false, notes: 'h5py is not installed' },
      },
    },
    format_allowlist: ['ecsv'],
    excluded_formats: { hdf5: 'h5py is not installed' },
  },
  message: '',
  error: null,
});

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe('Data Ingestion granted selections', () => {
  const originalElectronApi = window.electronAPI;
  const storage = new Map<string, string>();
  const localStorageMock = {
    clear: () => storage.clear(),
    getItem: (key: string) => storage.get(key) ?? null,
    key: (index: number) => [...storage.keys()][index] ?? null,
    get length() {
      return storage.size;
    },
    removeItem: (key: string) => {
      storage.delete(key);
    },
    setItem: (key: string, value: string) => {
      storage.set(key, value);
    },
  } satisfies Storage;

  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
    localStorage.clear();
    vi.clearAllMocks();
    mocks.getPort.mockResolvedValue(8765);
    mocks.listEventLists.mockResolvedValue({
      success: true,
      data: [],
      message: '',
      error: null,
    });
    mocks.checkFileSize.mockResolvedValue({
      success: false,
      data: null,
      message: 'not needed in this UI test',
      error: null,
    });
    mocks.checkBatchFileSize.mockResolvedValue({
      success: false,
      data: null,
      message: 'not needed in this UI test',
      error: null,
    });
    mocks.listExportableObjects.mockReset();
    mocks.exportObject.mockResolvedValue({
      success: true,
      data: { verified: true },
      message: 'Exported',
      error: null,
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: originalElectronApi,
    });
  });

  it('persists historical path hints without persisting grants', () => {
    saveLastLoadedFiles(
      [{ path: '/science/events.fits', grant: 'never-persist-this' }],
      { '/science/events.fits': 'events' }
    );

    const serialized = localStorage.getItem('lastLoadedFiles');
    expect(serialized).not.toContain('never-persist-this');
    expect(getLastLoadedFiles()).toEqual(
      expect.objectContaining({
        files: ['/science/events.fits'],
        fileNames: { '/science/events.fits': 'events' },
      })
    );
  });

  it('replaces stale authority only with a freshly selected grant', () => {
    const current = [{ path: '/science/events.fits', grant: 'stale-grant' }];
    expect(mergeGrantedSelections(current, [])).toEqual({ merged: current, added: [] });
    expect(
      mergeGrantedSelections(current, [
        { path: '/science/events.fits', grant: 'fresh-grant' },
        { path: '/science/second.hdf5', grant: 'second-grant' },
      ])
    ).toEqual({
      merged: [
        { path: '/science/events.fits', grant: 'fresh-grant' },
        { path: '/science/second.hdf5', grant: 'second-grant' },
      ],
      added: [{ path: '/science/second.hdf5', grant: 'second-grant' }],
    });
  });

  it('shows history as a hint and requires a fresh native granted selection', async () => {
    localStorage.setItem(
      'lastLoadedFiles',
      JSON.stringify({
        files: ['/historical/events.fits'],
        fileNames: { '/historical/events.fits': 'historical-events' },
        timestamp: Date.now(),
      })
    );
    const openGrantedFile = vi.fn().mockResolvedValue([
      { path: '/fresh/events.fits', grant: 'fresh-grant' },
    ]);
    const fileExists = vi.fn();
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { openGrantedFile, fileExists },
    });

    render(<DataIngestionPage />);

    expect(
      await screen.findByText(/Previous path hints \(fresh native selection required\)/)
    ).toHaveTextContent('/historical/events.fits');
    await userEvent.click(screen.getByRole('button', { name: 'Reselect Last Files' }));

    expect(openGrantedFile).toHaveBeenCalledWith(
      expect.objectContaining({ multiple: true, title: expect.stringContaining('Reselect') })
    );
    expect(openGrantedFile.mock.calls[0][0].filters[0].extensions).toContain('gz');
    expect(fileExists).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(mocks.checkFileSize).toHaveBeenCalledWith({
        file_path: '/fresh/events.fits',
        file_grant: 'fresh-grant',
      })
    );
    expect(await screen.findByText('events.fits')).toBeInTheDocument();
  });

  it('correlates redacted batch-size entries by request order when basenames collide', async () => {
    const openGrantedFile = vi.fn().mockResolvedValue([
      { path: '/first/shared.fits', grant: 'first-grant' },
      { path: '/second/shared.fits', grant: 'second-grant' },
    ]);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { openGrantedFile },
    });
    mocks.checkBatchFileSize.mockResolvedValue({
      success: true,
      data: {
        files: [
          {
            file_name: 'shared.fits',
            size_mb: 11,
            estimated_ram_mb: 22,
            ram_percent: 10,
            risk_level: 'safe',
          },
          {
            file_name: 'shared.fits',
            size_mb: 33,
            estimated_ram_mb: 66,
            ram_percent: 20,
            risk_level: 'safe',
          },
        ],
        total: {
          size_mb: 44,
          estimated_ram_mb: 88,
          ram_percent: 30,
          risk_level: 'safe',
        },
        available_ram_mb: 1024,
        file_count: 2,
        recommend_partial_loading: false,
      },
      message: '',
      error: null,
    });

    render(<DataIngestionPage />);
    await userEvent.click(screen.getByRole('button', { name: 'Browse Files' }));

    await waitFor(() =>
      expect(mocks.checkBatchFileSize).toHaveBeenCalledWith([
        { file_path: '/first/shared.fits', file_grant: 'first-grant' },
        { file_path: '/second/shared.fits', file_grant: 'second-grant' },
      ])
    );
    const nameInputs = await screen.findAllByPlaceholderText('Name');
    const firstRow = nameInputs[0].closest('.MuiListItem-root');
    const secondRow = nameInputs[1].closest('.MuiListItem-root');
    expect(firstRow).not.toBeNull();
    expect(secondRow).not.toBeNull();
    expect(within(firstRow as HTMLElement).getByText('11.0 MB')).toBeInTheDocument();
    expect(within(secondRow as HTMLElement).getByText('33.0 MB')).toBeInTheDocument();
  });

  it('does not recognize pickle as an allowed input format', () => {
    expect(detectFormatFromExtension('/science/events.pkl')).toBe('ogip');
    expect(detectFormatFromExtension('/science/events.ecsv')).toBe('ascii.ecsv');
  });

  it('rejects non-HTTPS remote sources before submission', () => {
    expect(validateRemoteSourceUrl('https://example.test/events.fits')).toBeNull();
    expect(validateRemoteSourceUrl('http://example.test/events.fits')).toBe(
      'Only HTTPS URLs are supported for remote event files.'
    );
    expect(validateRemoteSourceUrl('ftp://example.test/events.fits')).toBe(
      'Only HTTPS URLs are supported for remote event files.'
    );
  });

  it('hides unavailable HDF5 and exports ECSV with an exact native write grant', async () => {
    mocks.listEventLists.mockResolvedValue({
      success: true,
      data: [
        {
          name: 'events',
          n_events: 2,
          time_range: [0, 1],
        },
      ],
      message: '',
      error: null,
    });
    mocks.listExportableObjects.mockResolvedValue({
      success: true,
      data: {
        objects: [
          {
            object_type: 'event_list',
            name: 'events',
            row_count: 2,
            exportable: true,
            formats: ['ecsv'],
            reason: null,
          },
        ],
        capability_matrix: {
          event_list: {
            ecsv: { supported: true, notes: 'Verified ECSV' },
            hdf5: { supported: false, notes: 'h5py is not installed' },
          },
        },
        format_allowlist: ['ecsv'],
        excluded_formats: { hdf5: 'h5py is not installed' },
      },
      message: '',
      error: null,
    });
    const saveGrantedFile = vi.fn().mockResolvedValue({
      path: '/exports/events.ecsv',
      grant: 'write-grant',
    });
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { saveGrantedFile },
    });

    render(<DataIngestionPage />);

    expect(await screen.findByText('events')).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: 'Export to a native-selected destination' })
    );

    expect(await screen.findByText('HDF5 unavailable: h5py is not installed')).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /HDF5 \(Recommended\)/ })).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /ASCII ECSV/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Choose Location' }));

    expect(saveGrantedFile).toHaveBeenCalledWith({
      title: 'Export Event List: events',
      defaultPath: 'events.ecsv',
      filters: [{ name: 'ECSV Files', extensions: ['ecsv'] }],
    });
    expect(mocks.exportObject).toHaveBeenCalledWith({
      object_type: 'event_list',
      object_name: 'events',
      format: 'ecsv',
      destination_path: '/exports/events.ecsv',
      destination_grant: 'write-grant',
    });
  });

  it('ignores an older export discovery response that completes out of order', async () => {
    mocks.listEventLists.mockResolvedValue({
      success: true,
      data: [
        { name: 'first-events', n_events: 2, time_range: [0, 1] },
        { name: 'second-events', n_events: 2, time_range: [0, 1] },
      ],
      message: '',
      error: null,
    });
    const firstRequest = deferred<ReturnType<typeof exportCapabilityResponse>>();
    const secondRequest = deferred<ReturnType<typeof exportCapabilityResponse>>();
    mocks.listExportableObjects
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);

    render(<DataIngestionPage />);

    expect(await screen.findByText('first-events')).toBeInTheDocument();
    const exportButtons = screen.getAllByRole('button', {
      name: 'Export to a native-selected destination',
    });
    await userEvent.click(exportButtons[0]);
    await userEvent.click(exportButtons[1]);
    expect(mocks.listExportableObjects).toHaveBeenCalledTimes(2);

    await act(async () => {
      secondRequest.resolve(exportCapabilityResponse('first-events', 'second-events'));
      await secondRequest.promise;
    });
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/"second-events"/)).toBeInTheDocument();

    await act(async () => {
      firstRequest.resolve(exportCapabilityResponse('first-events', 'second-events'));
      await firstRequest.promise;
    });
    expect(within(dialog).getByText(/"second-events"/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/"first-events"/)).not.toBeInTheDocument();
  });
});
