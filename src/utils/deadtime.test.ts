import { describe, expect, it } from 'vitest';
import {
  UNPHYSICAL_DETECTED_RATE_MESSAGE,
  deadTimeLossFraction,
  detectedRateFromIncident,
  incidentRateFromDetected,
  parseNonNegativeNumber,
} from './deadtime';

describe('detectedRateFromIncident', () => {
  it('applies r_det = r_in / (1 + r_in * dead_time)', () => {
    // 300 c/s incident with a 2.5 ms dead time -> 300 / 1.75
    expect(detectedRateFromIncident(300, 0.0025)).toBeCloseTo(171.428571, 6);
  });

  it('is the identity for a zero dead time', () => {
    expect(detectedRateFromIncident(300, 0)).toBe(300);
  });

  it('rejects negative or non-finite inputs', () => {
    expect(detectedRateFromIncident(-1, 0.0025)).toBeNull();
    expect(detectedRateFromIncident(300, -0.0025)).toBeNull();
    expect(detectedRateFromIncident(Number.NaN, 0.0025)).toBeNull();
    expect(detectedRateFromIncident(300, Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('incidentRateFromDetected', () => {
  it('applies r_in = r_det / (1 - r_det * dead_time)', () => {
    // 300 * 0.0025 = 0.75 occupancy -> 300 / 0.25
    expect(incidentRateFromDetected(300, 0.0025)).toBeCloseTo(1200, 9);
  });

  it('inverts detectedRateFromIncident', () => {
    const detected = detectedRateFromIncident(300, 0.0025) as number;
    expect(incidentRateFromDetected(detected, 0.0025)).toBeCloseTo(300, 9);
  });

  it('returns null when detected rate x dead time reaches 1', () => {
    expect(incidentRateFromDetected(400, 0.0025)).toBeNull();
    expect(incidentRateFromDetected(500, 0.0025)).toBeNull();
  });

  it('rejects negative or non-finite inputs', () => {
    expect(incidentRateFromDetected(-1, 0.0025)).toBeNull();
    expect(incidentRateFromDetected(300, -0.0025)).toBeNull();
    expect(incidentRateFromDetected(Number.NaN, 0.0025)).toBeNull();
  });

  it('exposes the unphysical-occupancy message for the UI', () => {
    expect(UNPHYSICAL_DETECTED_RATE_MESSAGE).toBe(
      'unphysical: detected rate x dead time must be < 1'
    );
  });
});

describe('deadTimeLossFraction', () => {
  it('is (incident - detected) / incident', () => {
    expect(deadTimeLossFraction(300, 171.428571)).toBeCloseTo(0.428571, 6);
  });

  it('returns null when the incident rate is zero or invalid', () => {
    expect(deadTimeLossFraction(0, 0)).toBeNull();
    expect(deadTimeLossFraction(-5, 1)).toBeNull();
    expect(deadTimeLossFraction(300, Number.NaN)).toBeNull();
  });
});

describe('parseNonNegativeNumber', () => {
  it('accepts zero and positive numbers', () => {
    expect(parseNonNegativeNumber('0')).toBe(0);
    expect(parseNonNegativeNumber(' 2.5 ')).toBe(2.5);
  });

  it('rejects blank, negative and non-numeric values', () => {
    expect(parseNonNegativeNumber('')).toBeNull();
    expect(parseNonNegativeNumber('   ')).toBeNull();
    expect(parseNonNegativeNumber('-1')).toBeNull();
    expect(parseNonNegativeNumber('abc')).toBeNull();
    expect(parseNonNegativeNumber('Infinity')).toBeNull();
  });
});
