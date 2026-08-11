import { describe, expect, it } from 'vitest';
import {
  MAX_FILE_GRANT_RESPONSE_BYTES,
  parseFileGrantResponse,
} from '../../electron/fileGrantResponse';

describe('native file grant response policy', () => {
  it('returns only the validated path and grant', () => {
    expect(
      parseFileGrantResponse(
        JSON.stringify({
          path: '/data/selected.fits',
          grant: 'v2.123.4.5.signature',
          ignored: 'not forwarded',
        })
      )
    ).toEqual({ path: '/data/selected.fits', grant: 'v2.123.4.5.signature' });
  });

  it.each([
    ['not JSON', '{'],
    ['an array', '[]'],
    ['a missing path', JSON.stringify({ grant: 'v2.token' })],
    ['an empty grant', JSON.stringify({ path: '/data/file.fits', grant: '' })],
    [
      'a control character in the path',
      JSON.stringify({ path: '/data/file.fits\nsecond', grant: 'v2.token' }),
    ],
    [
      'a control character in the grant',
      JSON.stringify({ path: '/data/file.fits', grant: 'v2.token\tmore' }),
    ],
  ])('rejects %s', (_description, body) => {
    expect(() => parseFileGrantResponse(body)).toThrow();
  });

  it('rejects an oversized body before parsing it', () => {
    expect(() => parseFileGrantResponse('x'.repeat(MAX_FILE_GRANT_RESPONSE_BYTES + 1))).toThrow(
      /too large/
    );
  });
});
