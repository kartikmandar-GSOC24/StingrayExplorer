import { describe, expect, it } from 'vitest';
import { computePowerColorRatios } from './powerColors';

describe('computePowerColorRatios', () => {
  const powerColors = {
    A: [1, 2],
    B: [10, 20],
    C: [100, 200],
    D: [5, 10],
  };

  it('computes PC1 = C/A and PC2 = B/D per segment', () => {
    const result = computePowerColorRatios(powerColors, ['A', 'B', 'C', 'D']);
    expect(result).not.toBeNull();
    expect(result?.pc1).toEqual([100, 100]);
    expect(result?.pc2).toEqual([2, 2]);
  });

  it('returns null when a band is missing or count is not 4', () => {
    expect(computePowerColorRatios(powerColors, ['A', 'B', 'C'])).toBeNull();
    expect(computePowerColorRatios({ A: [1] }, ['A', 'B', 'C', 'D'])).toBeNull();
  });

  it('skips segments with non-positive denominators', () => {
    const result = computePowerColorRatios(
      { A: [0, 1], B: [1, 1], C: [1, 1], D: [1, 1] },
      ['A', 'B', 'C', 'D']
    );
    expect(result?.pc1).toEqual([1]);
    expect(result?.pc2).toEqual([1]);
  });

  it('skips segments where any band value is null', () => {
    const result = computePowerColorRatios(
      { A: [1, null], B: [1, 1], C: [1, 1], D: [1, 1] },
      ['A', 'B', 'C', 'D']
    );
    expect(result?.pc1).toEqual([1]);
    expect(result?.pc2).toEqual([1]);
  });
});
