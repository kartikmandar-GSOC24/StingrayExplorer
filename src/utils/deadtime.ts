/**
 * Client-side dead-time rate conversions for a NON-PARALYZABLE detector,
 * mirroring `stingray.deadtime.filters.r_det` / `r_in`:
 *
 *   r_det = r_in  / (1 + r_in  * dead_time)
 *   r_in  = r_det / (1 - r_det * dead_time)
 *
 * The second relation only exists while `r_det * dead_time < 1`; at or above 1
 * the detector would be busy for more than 100% of the time, which is
 * unphysical (and is the same guard the backend applies before calling
 * `deadtime_correct`). stingray does not implement the paralyzable case, so
 * these are the only conversions offered.
 */

/** Helper text shown when a detected rate implies >= 100% detector occupancy. */
export const UNPHYSICAL_DETECTED_RATE_MESSAGE =
  'unphysical: detected rate x dead time must be < 1';

/** Parse a text-field value into a finite non-negative number, or null if invalid. */
export function parseNonNegativeNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

/** Detected (observed) rate for an incident rate and dead time, or null if inputs are invalid. */
export function detectedRateFromIncident(
  incidentRate: number,
  deadTime: number
): number | null {
  if (!Number.isFinite(incidentRate) || !Number.isFinite(deadTime)) return null;
  if (incidentRate < 0 || deadTime < 0) return null;
  return incidentRate / (1 + incidentRate * deadTime);
}

/**
 * Incident (true) rate implied by a detected rate and dead time.
 * Returns null when `detectedRate * deadTime >= 1` (unphysical occupancy) or
 * when the inputs are invalid.
 */
export function incidentRateFromDetected(
  detectedRate: number,
  deadTime: number
): number | null {
  if (!Number.isFinite(detectedRate) || !Number.isFinite(deadTime)) return null;
  if (detectedRate < 0 || deadTime < 0) return null;
  if (detectedRate * deadTime >= 1) return null;
  return detectedRate / (1 - detectedRate * deadTime);
}

/** Fraction of incident events lost to dead time, or null when it is undefined. */
export function deadTimeLossFraction(
  incidentRate: number,
  detectedRate: number
): number | null {
  if (!Number.isFinite(incidentRate) || !Number.isFinite(detectedRate)) return null;
  if (incidentRate <= 0) return null;
  return (incidentRate - detectedRate) / incidentRate;
}
