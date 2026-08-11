import { describe, expect, it } from 'vitest';
import { finiteNumber, positiveNumber } from './GtiCommon';

describe('strict GTI scalar parsing', () => {
  it('preserves signed decimal and exponent notation', () => {
    expect(finiteNumber(' -1.25e2 ')).toBe(-125);
    expect(positiveNumber('+2.5E-1')).toBe(0.25);
  });

  it('rejects JavaScript hexadecimal and binary notation', () => {
    expect(finiteNumber('0x10')).toBeNull();
    expect(positiveNumber('0b10')).toBeNull();
  });
});
