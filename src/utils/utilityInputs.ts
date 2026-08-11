import { isDecimalNumberText } from './numbers';

export const MAX_UTILITY_VALUES = 100_000;
export const MAX_GTI_ROWS = 10_000;
export const MAX_MATRIX_CELLS = 200_000;

export interface ParseResult<T> {
  value: T | null;
  error: string | null;
}

/** Parse comma/space/newline-delimited finite numbers with an allocation cap. */
export function parseNumericArray(
  text: string,
  label = 'Values',
  maxValues = MAX_UTILITY_VALUES
): ParseResult<number[]> {
  const trimmed = text.trim();
  if (!trimmed) return { value: null, error: `${label} are required` };
  const tokens = trimmed.split(/[\s,]+/);
  if (tokens.length > maxValues) {
    return { value: null, error: `${label} contain ${tokens.length.toLocaleString()} values; the cap is ${maxValues.toLocaleString()}` };
  }
  const values: number[] = [];
  for (let index = 0; index < tokens.length; index += 1) {
    if (!isDecimalNumberText(tokens[index])) {
      return {
        value: null,
        error: `${label} value ${index + 1} is not a finite decimal number`,
      };
    }
    const value = Number(tokens[index]);
    if (!Number.isFinite(value)) {
      return { value: null, error: `${label} value ${index + 1} is not a finite number` };
    }
    values.push(value);
  }
  return { value: values, error: null };
}

/** Parse one ``start, stop`` GTI per non-empty line without sorting or merging. */
export function parseGtiRows(text: string): ParseResult<[number, number][]> {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== '');
  if (lines.length === 0) return { value: null, error: 'At least one GTI row is required' };
  if (lines.length > MAX_GTI_ROWS) {
    return { value: null, error: `GTI input contains ${lines.length.toLocaleString()} rows; the cap is ${MAX_GTI_ROWS.toLocaleString()}` };
  }
  const rows: [number, number][] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const parts = lines[index].trim().split(/[\s,]+/);
    if (parts.length !== 2) {
      return { value: null, error: `GTI row ${index + 1} must contain exactly start and stop` };
    }
    if (!parts.every((part) => isDecimalNumberText(part))) {
      return {
        value: null,
        error: `GTI row ${index + 1} must contain finite decimal start and stop values`,
      };
    }
    const start = Number(parts[0]);
    const stop = Number(parts[1]);
    if (!Number.isFinite(start) || !Number.isFinite(stop)) {
      return { value: null, error: `GTI row ${index + 1} must contain finite numbers` };
    }
    rows.push([start, stop]);
  }
  return { value: rows, error: null };
}

/** Parse one equally sized numeric sample vector per line for SEM calculations. */
export function parseNumericMatrix(
  text: string,
  maxCells = MAX_MATRIX_CELLS
): ParseResult<number[][]> {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== '');
  if (lines.length < 2) {
    return { value: null, error: 'At least two sample rows are required' };
  }
  const rows: number[][] = [];
  let columns: number | null = null;
  let cells = 0;
  for (let index = 0; index < lines.length; index += 1) {
    const parsed = parseNumericArray(lines[index], `Sample row ${index + 1}`);
    if (!parsed.value) return { value: null, error: parsed.error };
    columns ??= parsed.value.length;
    if (parsed.value.length !== columns) {
      return { value: null, error: `Sample row ${index + 1} has ${parsed.value.length} columns; expected ${columns}` };
    }
    cells += parsed.value.length;
    if (cells > maxCells) {
      return { value: null, error: `Sample matrix exceeds the ${maxCells.toLocaleString()}-value cap` };
    }
    rows.push(parsed.value);
  }
  return { value: rows, error: null };
}

export function validateDerivedName(name: string): string | null {
  if (name !== name.trim()) return 'Name must not start or end with whitespace';
  if (!/^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$/.test(name)) {
    return "Use 1-64 letters, digits, spaces, '.', '_' or '-', starting with a letter or digit";
  }
  return null;
}

export function parsePositiveInteger(value: string): number | null {
  const trimmed = value.trim();
  if (!isDecimalNumberText(trimmed)) return null;
  const parsed = Number(trimmed);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}
