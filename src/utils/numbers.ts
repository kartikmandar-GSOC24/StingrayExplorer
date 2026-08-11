const DECIMAL_NUMBER_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

/** Whether text uses ordinary decimal/exponent notation (never JS hex, binary, or octal). */
export function isDecimalNumberText(value: string): boolean {
  const trimmed = value.trim();
  return trimmed !== '' && DECIMAL_NUMBER_PATTERN.test(trimmed);
}

/** Parse a text-field value into a finite positive decimal number, or null if invalid. */
export function parsePositiveNumber(value: string): number | null {
  const n = parseNumber(value);
  if (n === null) return null;
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Parse a text-field value into any finite decimal number, or null if invalid. */
export function parseNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!isDecimalNumberText(trimmed)) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}
