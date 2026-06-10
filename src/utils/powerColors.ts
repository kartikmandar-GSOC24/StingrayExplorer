/**
 * Power-color ratios following the Heil et al. (2015) convention: with four
 * frequency bands A < B < C < D (ascending f_min),
 *   PC1 = P(C) / P(A)  and  PC2 = P(B) / P(D)
 * computed per dynamical-spectrum segment.
 */
export interface PowerColorRatios {
  pc1: number[];
  pc2: number[];
}

export function computePowerColorRatios(
  powerColors: Record<string, Array<number | null>>,
  bandOrder: string[]
): PowerColorRatios | null {
  if (bandOrder.length !== 4) return null;
  const [a, b, c, d] = bandOrder.map((key) => powerColors[key]);
  if (!a || !b || !c || !d) return null;

  const n = Math.min(a.length, b.length, c.length, d.length);
  const pc1: number[] = [];
  const pc2: number[] = [];
  for (let i = 0; i < n; i++) {
    const av = a[i];
    const bv = b[i];
    const cv = c[i];
    const dv = d[i];
    if (av != null && bv != null && cv != null && dv != null && av > 0 && bv > 0 && cv > 0 && dv > 0) {
      pc1.push(cv / av);
      pc2.push(bv / dv);
    }
  }
  return { pc1, pc2 };
}
