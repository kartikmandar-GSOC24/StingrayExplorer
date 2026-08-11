import { describe, expect, it } from 'vitest';
import { count, finiteNumber } from './validation';

describe('strict statistical scalar parsing', () => {
  it('accepts signed decimal and exponent notation', () => {
    expect(finiteNumber(' -2.5e+3 ', 'Statistic')).toEqual({ value: -2500, error: null });
    expect(count('+2e1', 'Trials')).toEqual({ value: 20, error: null });
  });

  it('rejects JavaScript hexadecimal and binary notation', () => {
    expect(finiteNumber('0x10', 'Statistic')).toEqual({
      value: null,
      error: 'Statistic must be a finite number',
    });
    expect(count('0b10', 'Trials')).toEqual({
      value: null,
      error: 'Trials must be a finite number',
    });
  });
});
