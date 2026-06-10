import { describe, expect, it } from 'vitest';
import { parseNumber, parsePositiveNumber } from './numbers';

describe('parsePositiveNumber', () => {
  it('parses valid positive numbers', () => {
    expect(parsePositiveNumber('0.0625')).toBe(0.0625);
    expect(parsePositiveNumber('32')).toBe(32);
  });

  it('rejects zero, negatives, and junk', () => {
    expect(parsePositiveNumber('0')).toBeNull();
    expect(parsePositiveNumber('-1')).toBeNull();
    expect(parsePositiveNumber('abc')).toBeNull();
    expect(parsePositiveNumber('')).toBeNull();
  });
});

describe('parseNumber', () => {
  it('parses any finite number', () => {
    expect(parseNumber('-2.5')).toBe(-2.5);
    expect(parseNumber('0')).toBe(0);
  });

  it('rejects non-numeric input', () => {
    expect(parseNumber('1e999')).toBeNull();
    expect(parseNumber('x')).toBeNull();
    expect(parseNumber('')).toBeNull();
  });
});
