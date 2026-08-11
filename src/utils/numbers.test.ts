import { describe, expect, it } from 'vitest';
import { parseNumber, parsePositiveNumber } from './numbers';

describe('parsePositiveNumber', () => {
  it('parses valid positive numbers', () => {
    expect(parsePositiveNumber('0.0625')).toBe(0.0625);
    expect(parsePositiveNumber('32')).toBe(32);
    expect(parsePositiveNumber(' +6.25e-2 ')).toBe(0.0625);
  });

  it('rejects zero, negatives, and junk', () => {
    expect(parsePositiveNumber('0')).toBeNull();
    expect(parsePositiveNumber('-1')).toBeNull();
    expect(parsePositiveNumber('abc')).toBeNull();
    expect(parsePositiveNumber('')).toBeNull();
    expect(parsePositiveNumber('1e999')).toBeNull();
    expect(parsePositiveNumber('0x10')).toBeNull();
    expect(parsePositiveNumber('0b10')).toBeNull();
  });
});

describe('parseNumber', () => {
  it('parses any finite number', () => {
    expect(parseNumber('-2.5')).toBe(-2.5);
    expect(parseNumber('0')).toBe(0);
    expect(parseNumber('-.5E+2')).toBe(-50);
    expect(parseNumber('+1.')).toBe(1);
  });

  it('rejects non-numeric input', () => {
    expect(parseNumber('1e999')).toBeNull();
    expect(parseNumber('x')).toBeNull();
    expect(parseNumber('')).toBeNull();
    expect(parseNumber('   ')).toBeNull();
    expect(parseNumber('0x10')).toBeNull();
    expect(parseNumber('0b10')).toBeNull();
  });
});
