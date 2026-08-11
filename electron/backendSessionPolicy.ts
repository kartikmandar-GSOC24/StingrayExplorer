export const BACKEND_SESSION_HEADER = 'X-Stingray-Session';

export interface BackendSessionRequestContext {
  requestUrl: string;
  method: string;
  backendPort: number;
  requestWebContentsId?: number;
  trustedWebContentsId: number;
  isMainFrame: boolean;
  frameUrl: string;
  rendererEntryUrl: string;
}

/** Return true only for the trusted app document, never a child or navigated page. */
export function isTrustedRendererLocation(currentUrl: string, entryUrl: string): boolean {
  try {
    const current = new URL(currentUrl);
    const entry = new URL(entryUrl);
    return (
      current.protocol === entry.protocol &&
      current.username === entry.username &&
      current.password === entry.password &&
      current.hostname === entry.hostname &&
      current.port === entry.port &&
      current.pathname === entry.pathname &&
      current.search === entry.search
    );
  } catch {
    return false;
  }
}

/** Decide whether Electron main may authenticate one renderer request. */
export function shouldAuthenticateBackendRequest(
  context: BackendSessionRequestContext
): boolean {
  if (context.method.toUpperCase() === 'OPTIONS') return false;
  if (context.requestWebContentsId !== context.trustedWebContentsId) return false;
  if (!context.isMainFrame) return false;
  if (!isTrustedRendererLocation(context.frameUrl, context.rendererEntryUrl)) return false;

  try {
    const target = new URL(context.requestUrl);
    return (
      target.protocol === 'http:' &&
      target.hostname === '127.0.0.1' &&
      target.port === String(context.backendPort)
    );
  } catch {
    return false;
  }
}

/** Strip renderer-supplied copies and optionally install the main-process secret. */
export function withBackendSessionHeader(
  requestHeaders: Record<string, string>,
  sessionSecret?: string
): Record<string, string> {
  const headers = Object.fromEntries(
    Object.entries(requestHeaders).filter(
      ([name]) => name.toLowerCase() !== BACKEND_SESSION_HEADER.toLowerCase()
    )
  );
  if (sessionSecret) headers[BACKEND_SESSION_HEADER] = sessionSecret;
  return headers;
}
