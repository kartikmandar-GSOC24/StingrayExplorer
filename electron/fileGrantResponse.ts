export interface NativeFileGrant {
  path: string;
  grant: string;
}

export const MAX_FILE_GRANT_RESPONSE_BYTES = 32 * 1024;

const MAX_GRANTED_PATH_LENGTH = 4096;
const MAX_GRANT_LENGTH = 4096;
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/;

/**
 * Parse the private grant issuer's response without trusting its shape or size.
 * Keeping this independent from Electron and Node HTTP makes the fail-closed
 * response policy easy to exercise under Vitest.
 */
export function parseFileGrantResponse(body: string): NativeFileGrant {
  if (Buffer.byteLength(body, 'utf8') > MAX_FILE_GRANT_RESPONSE_BYTES) {
    throw new Error('The native file authorization response was too large');
  }

  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    throw new Error('The native file authorization response was not valid JSON');
  }

  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('The native file authorization response had an invalid shape');
  }

  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.path !== 'string' ||
    candidate.path.length === 0 ||
    candidate.path.length > MAX_GRANTED_PATH_LENGTH ||
    CONTROL_CHARACTER.test(candidate.path)
  ) {
    throw new Error('The native file authorization response contained an invalid path');
  }
  if (
    typeof candidate.grant !== 'string' ||
    candidate.grant.length === 0 ||
    candidate.grant.length > MAX_GRANT_LENGTH ||
    CONTROL_CHARACTER.test(candidate.grant)
  ) {
    throw new Error('The native file authorization response contained an invalid grant');
  }

  return { path: candidate.path, grant: candidate.grant };
}
