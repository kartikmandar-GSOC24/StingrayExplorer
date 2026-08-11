import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { archiveApi } from './archiveApi';

function sseResponse(events: string[]) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${event}\n\n`));
      }
      controller.close();
    },
  });
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    body: stream,
  };
}

describe('archiveApi secure download stream', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { getBackendPort: vi.fn().mockResolvedValue(8765) },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('posts the exact destination grant and forwards cancellation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        JSON.stringify({
          type: 'complete',
          file_name: 'download.evt',
          size_bytes: 12,
          sha256: 'a'.repeat(64),
          warnings: [],
          file_path: '/must/not/survive/parsing',
          destination_grant: 'must-not-survive-parsing',
        }),
      ])
    );
    vi.stubGlobal('fetch', fetchMock);
    const abortController = new AbortController();

    const events = [];
    for await (const event of archiveApi.downloadToDiskSSE({
      url: 'https://heasarc.gsfc.nasa.gov/FTP/nicer/download.evt',
      destination_path: '/native/download.evt',
      destination_grant: 'write-grant',
      signal: abortController.signal,
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        type: 'complete',
        file_name: 'download.evt',
        size_bytes: 12,
        sha256: 'a'.repeat(64),
        warnings: [],
      },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/archive/download-to-disk',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortController.signal,
      })
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      url: 'https://heasarc.gsfc.nasa.gov/FTP/nicer/download.evt',
      destination_path: '/native/download.evt',
      destination_grant: 'write-grant',
    });
  });

  it('rejects malformed completion data instead of treating a path as a filename', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse([
          JSON.stringify({
            type: 'complete',
            file_name: '/unverified/private/file.evt',
            size_bytes: 12,
            sha256: 'a'.repeat(64),
            warnings: [],
          }),
        ])
      )
    );

    const consume = async () => {
      for await (const _event of archiveApi.downloadToDiskSSE({
        url: 'https://heasarc.gsfc.nasa.gov/FTP/nicer/download.evt',
        destination_path: '/native/download.evt',
        destination_grant: 'write-grant',
      })) {
        // Exhaust the stream.
      }
    };

    await expect(consume()).rejects.toThrow('Malformed download progress response');
  });
});
