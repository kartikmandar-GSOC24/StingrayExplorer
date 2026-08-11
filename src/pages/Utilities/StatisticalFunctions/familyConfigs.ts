export type FamilyKey = 'pds' | 'z2' | 'fold' | 'pdm';

export interface FamilyConfig {
  key: FamilyKey;
  title: string;
  description: string;
  statisticLabel: string;
  statisticDefault: string;
  statisticDomain: string;
  resultUnit: string;
  significantDirection: 'larger' | 'smaller';
  hasSummedSpectra?: boolean;
  hasRebin?: boolean;
  hasHarmonics?: boolean;
  hasPhaseBins?: boolean;
  hasSamples?: boolean;
  minimumPhaseBins?: number;
}

export const FAMILY_CONFIGS: Record<FamilyKey, FamilyConfig> = {
  pds: {
    key: 'pds',
    title: 'Power-spectrum significance',
    description:
      'Evaluate a Leahy-normalized PDS power under the white-noise χ² model, including averaging and rebinning.',
    statisticLabel: 'Observed Leahy power',
    statisticDefault: '20',
    statisticDomain: 'Domain: finite power ≥ 0; dimensionless Leahy normalization',
    resultUnit: 'dimensionless Leahy-normalized power',
    significantDirection: 'larger',
    hasSummedSpectra: true,
    hasRebin: true,
  },
  z2: {
    key: 'z2',
    title: 'Z²ₙ significance',
    description:
      'Evaluate the Z²ₙ periodicity statistic for an explicit harmonic count and optional averaged periodograms.',
    statisticLabel: 'Observed Z-squared statistic',
    statisticDefault: '20',
    statisticDomain: 'Domain: finite Z²ₙ ≥ 0; dimensionless',
    resultUnit: 'dimensionless Z-squared-n statistic',
    significantDirection: 'larger',
    hasSummedSpectra: true,
    hasHarmonics: true,
  },
  fold: {
    key: 'fold',
    title: 'Epoch-folding significance',
    description:
      'Evaluate a folded-profile χ² statistic using the number of phase bins and independent search trials.',
    statisticLabel: 'Observed epoch-folding statistic',
    statisticDefault: '20',
    statisticDomain: 'Domain: finite statistic ≥ 0; dimensionless',
    resultUnit: 'dimensionless epoch-folding statistic',
    significantDirection: 'larger',
    hasPhaseBins: true,
    minimumPhaseBins: 3,
  },
  pdm: {
    key: 'pdm',
    title: 'Phase-dispersion significance',
    description:
      'Evaluate the inverse PDM peak with Stingray’s lower-tail beta distribution. Smaller values are more significant.',
    statisticLabel: 'Observed inverse PDM peak statistic',
    statisticDefault: '0.2',
    statisticDomain: 'Domain: 0 ≤ statistic ≤ 1; dimensionless',
    resultUnit: 'dimensionless phase-dispersion statistic',
    significantDirection: 'smaller',
    hasPhaseBins: true,
    hasSamples: true,
    minimumPhaseBins: 2,
  },
};
