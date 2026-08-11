import { describe, expect, it } from 'vitest';
import {
  parseGtiRows,
  parseNumericArray,
  parseNumericMatrix,
  parsePositiveInteger,
  validateDerivedName,
} from './utilityInputs';

describe('utility input parsing', () => {
  it('parses finite numeric arrays across supported delimiters', () => {
    expect(parseNumericArray('1, 2\n3 4').value).toEqual([1, 2, 3, 4]);
    expect(parseNumericArray('-.5, +2.0e3').value).toEqual([-0.5, 2000]);
    expect(parseNumericArray('1, NaN').error).toMatch(/finite/);
    expect(parseNumericArray('0x10').error).toMatch(/decimal/);
    expect(parseNumericArray('1 2 3', 'x', 2).error).toMatch(/cap/);
  });

  it('preserves GTI row order and identifies malformed rows', () => {
    expect(parseGtiRows('5, 6\n1 2').value).toEqual([[5, 6], [1, 2]]);
    expect(parseGtiRows('1 2 3').error).toMatch(/row 1/);
    expect(parseGtiRows('0x10, 20').error).toMatch(/finite decimal/);
  });

  it('requires a rectangular multi-row matrix', () => {
    expect(parseNumericMatrix('1 2\n3 4').value).toEqual([[1, 2], [3, 4]]);
    expect(parseNumericMatrix('1 2\n3').error).toMatch(/expected 2/);
    expect(parseNumericMatrix('1 2').error).toMatch(/two/);
    expect(parseNumericMatrix('1 2\n3 4', 3).error).toMatch(/3-value cap/);
  });

  it('validates unique destination names and positive integers', () => {
    expect(validateDerivedName('filtered-events_2')).toBeNull();
    expect(validateDerivedName(' ../bad')).not.toBeNull();
    expect(parsePositiveInteger('3')).toBe(3);
    expect(parsePositiveInteger('1e3')).toBe(1000);
    expect(parsePositiveInteger('3.5')).toBeNull();
    expect(parsePositiveInteger('0x10')).toBeNull();
  });
});
