/** Parse a text-field value into a finite positive number, or null if invalid. */
export function parsePositiveNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Parse a text-field value into any finite number, or null if invalid. */
export function parseNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
