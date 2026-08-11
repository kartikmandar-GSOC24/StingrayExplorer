import { parseNumber } from '@/utils/numbers';

const MAX_COUNT = 2_147_483_647;

export interface ParsedField {
  value: number | null;
  error: string | null;
}

export function finiteNumber(raw: string, label: string): ParsedField {
  if (raw.trim() === '') return { value: null, error: `${label} is required` };
  const value = parseNumber(raw);
  return value !== null
    ? { value, error: null }
    : { value: null, error: `${label} must be a finite number` };
}

export function probability(raw: string, label: string): ParsedField {
  const parsed = finiteNumber(raw, label);
  if (parsed.value === null) return parsed;
  return parsed.value > 0 && parsed.value < 1
    ? parsed
    : { value: null, error: `${label} must be greater than 0 and less than 1` };
}

export function count(raw: string, label: string, minimum = 1): ParsedField {
  const parsed = finiteNumber(raw, label);
  if (parsed.value === null) return parsed;
  if (!Number.isSafeInteger(parsed.value)) {
    return { value: null, error: `${label} must be an integer` };
  }
  if (parsed.value < minimum || parsed.value > MAX_COUNT) {
    return {
      value: null,
      error: `${label} must be ${minimum}–${MAX_COUNT.toLocaleString()}`,
    };
  }
  return parsed;
}
