import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/testUtils';

const listObservationFiles = vi.fn();
const downloadToDiskSSE = vi.fn();
const addNotification = vi.fn();

vi.mock('@/api/archiveApi', () => ({
  archiveApi: {
    listObservationFiles: (...args: unknown[]) => listObservationFiles(...args),
    downloadToDiskSSE: (...args: unknown[]) => downloadToDiskSSE(...args),
  },
}));

vi.mock('@/store/uiStore', () => ({
  useUIStore: () => ({ addNotification }),
}));

import FileBrowserDialog from './FileBrowserDialog';

const OBS_DATA = { ra: 83.63, dec: 22.01 };
const FILE_TREE = {
  success: true,
  data: {
    base_url: 'https://heasarc.gsfc.nasa.gov/FTP/nicer/data/obs/',
    mission: 'NICER',
    obsid: '1234',
    total_files: 1,
    files: [
      {
        path: 'event.evt',
        name: 'event.evt',
        is_directory: false,
        file_type: 'event',
        size_bytes: 12,
        size_display: '12 B',
        full_url: 'https://heasarc.gsfc.nasa.gov/FTP/nicer/data/obs/event.evt',
      },
    ],
  },
  message: 'Found one file',
  error: null,
};

function renderDialog(onDownloadComplete = vi.fn()) {
  renderWithProviders(
    <FileBrowserDialog
      open
      onClose={vi.fn()}
      mission="NICER"
      obsid="1234"
      obsTime="60000"
      targetName="Crab"
      obsData={OBS_DATA}
      onDownloadComplete={onDownloadComplete}
    />
  );
  return onDownloadComplete;
}

describe('FileBrowserDialog secure archive download', () => {
  const saveGrantedFile = vi.fn();
  const rawSaveFile = vi.fn();
  const rawShowItemInFolder = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    listObservationFiles.mockResolvedValue(FILE_TREE);
    saveGrantedFile.mockResolvedValue({
      path: '/verified/download.evt',
      grant: 'write-grant-secret',
    });
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: {
        saveGrantedFile,
        saveFile: rawSaveFile,
        showItemInFolder: rawShowItemInFolder,
      },
    });
  });

  it('uses only a native write grant and renders no destination path or grant', async () => {
    downloadToDiskSSE.mockImplementation(async function* () {
      yield {
        type: 'progress',
        bytes_downloaded: 12,
        total_bytes: 12,
        percent: 100,
      };
      yield {
        type: 'complete',
        file_name: 'download.evt',
        size_bytes: 12,
        sha256: 'a'.repeat(64),
        warnings: [],
      };
      yield { type: 'error', error: 'must not replace confirmed completion' };
    });
    const onDownloadComplete = renderDialog();

    expect(await screen.findByText('event.evt')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Download' }));

    await waitFor(() => {
      expect(downloadToDiskSSE).toHaveBeenCalledTimes(1);
    });
    expect(saveGrantedFile).toHaveBeenCalledWith({
      title: 'Save Downloaded File',
      defaultPath: 'event.evt',
      filters: [
        { name: 'FITS Files', extensions: ['fits', 'fits.gz', 'evt', 'evt.gz'] },
        { name: 'All Files', extensions: ['*'] },
      ],
    });
    expect(downloadToDiskSSE).toHaveBeenCalledWith(
      expect.objectContaining({
        url: FILE_TREE.data.files[0].full_url,
        destination_path: '/verified/download.evt',
        destination_grant: 'write-grant-secret',
        signal: expect.any(AbortSignal),
      })
    );
    expect(await screen.findByText('Downloaded download.evt (12 B)')).toBeInTheDocument();
    expect(screen.queryByText('/verified/download.evt')).not.toBeInTheDocument();
    expect(screen.queryByText('write-grant-secret')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show in Folder' })).not.toBeInTheDocument();
    expect(rawSaveFile).not.toHaveBeenCalled();
    expect(rawShowItemInFolder).not.toHaveBeenCalled();
    expect(onDownloadComplete).toHaveBeenCalledWith();
    expect(screen.queryByText('must not replace confirmed completion')).not.toBeInTheDocument();
  });

  it('reports native grant issuance failure without starting a download', async () => {
    saveGrantedFile.mockRejectedValue(
      new Error('sensitive backend failure at /private/destination')
    );
    renderDialog();

    expect(await screen.findByText('event.evt')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Download' }));

    await waitFor(() => {
      expect(addNotification).toHaveBeenCalledWith({
        type: 'error',
        title: 'Secure Save Failed',
        message: 'Could not authorize the selected destination. Please try again.',
      });
    });
    expect(downloadToDiskSSE).not.toHaveBeenCalled();
    expect(screen.queryByText('/private/destination')).not.toBeInTheDocument();
  });

  it('passes an AbortSignal and reports cancellation without publishing success', async () => {
    let observedSignal: AbortSignal | undefined;
    downloadToDiskSSE.mockImplementation(async function* (params: {
      signal: AbortSignal;
    }) {
      observedSignal = params.signal;
      yield {
        type: 'progress',
        bytes_downloaded: 4,
        total_bytes: 12,
        percent: 33.3,
      };
      await new Promise<void>((_resolve, reject) => {
        params.signal.addEventListener(
          'abort',
          () => reject(new DOMException('aborted', 'AbortError')),
          { once: true }
        );
      });
    });
    const onDownloadComplete = renderDialog();

    expect(await screen.findByText('event.evt')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Download' }));
    expect(await screen.findByRole('button', { name: 'Cancel Download' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel Download' }));

    expect(observedSignal?.aborted).toBe(true);
    expect(await screen.findByText('Download cancelled')).toBeInTheDocument();
    expect(onDownloadComplete).not.toHaveBeenCalled();
    expect(addNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download Failed', message: 'Download cancelled' })
    );
    expect(rawSaveFile).not.toHaveBeenCalled();
    expect(rawShowItemInFolder).not.toHaveBeenCalled();
  });
});
