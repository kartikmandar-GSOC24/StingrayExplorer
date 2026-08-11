import { describe, expect, it } from 'vitest';
import {
  BACKEND_SESSION_HEADER,
  isTrustedRendererLocation,
  shouldAuthenticateBackendRequest,
  withBackendSessionHeader,
} from '../../electron/backendSessionPolicy';

const trustedRequest = {
  requestUrl: 'http://127.0.0.1:8765/api/status',
  method: 'GET',
  backendPort: 8765,
  requestWebContentsId: 7,
  trustedWebContentsId: 7,
  isMainFrame: true,
  frameUrl: 'http://localhost:5173/data-ingestion',
  rendererEntryUrl: 'http://localhost:5173',
};

describe('Electron backend session policy', () => {
  it('authenticates only exact backend requests from the trusted top-level renderer', () => {
    expect(shouldAuthenticateBackendRequest(trustedRequest)).toBe(true);
    expect(
      shouldAuthenticateBackendRequest({
        ...trustedRequest,
        requestUrl: 'http://127.0.0.1:8766/api/status',
      })
    ).toBe(false);
    expect(
      shouldAuthenticateBackendRequest({
        ...trustedRequest,
        requestUrl: 'http://localhost:8765/api/status',
      })
    ).toBe(false);
    expect(
      shouldAuthenticateBackendRequest({ ...trustedRequest, requestWebContentsId: 8 })
    ).toBe(false);
    expect(
      shouldAuthenticateBackendRequest({ ...trustedRequest, isMainFrame: false })
    ).toBe(false);
    expect(
      shouldAuthenticateBackendRequest({
        ...trustedRequest,
        frameUrl: 'https://attacker.example/',
      })
    ).toBe(false);
    expect(
      shouldAuthenticateBackendRequest({ ...trustedRequest, method: 'OPTIONS' })
    ).toBe(false);
  });

  it('accepts the exact packaged file entry but not adjacent local files', () => {
    expect(
      isTrustedRendererLocation(
        'file:///Applications/Stingray%20Explorer/dist/index.html#/utilities/io',
        'file:///Applications/Stingray%20Explorer/dist/index.html'
      )
    ).toBe(true);
    expect(
      isTrustedRendererLocation(
        'file:///Applications/Stingray%20Explorer/dist/other.html',
        'file:///Applications/Stingray%20Explorer/dist/index.html'
      )
    ).toBe(false);
  });

  it('removes renderer-supplied session headers before main installs its secret', () => {
    const headers = withBackendSessionHeader(
      { Accept: 'application/json', 'x-stingray-session': 'attacker-value' },
      'main-process-secret'
    );

    expect(headers).toEqual({
      Accept: 'application/json',
      [BACKEND_SESSION_HEADER]: 'main-process-secret',
    });
    expect(withBackendSessionHeader(headers)).toEqual({ Accept: 'application/json' });
  });
});
