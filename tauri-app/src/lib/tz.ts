/**
 * The browser's offset from UTC, in the sign convention the backend expects:
 * positive east of Greenwich.
 *
 * `Date.getTimezoneOffset()` is inverted — it returns +300 in New York, not
 * -300 — so it is negated exactly once, here, rather than at each call site
 * where getting it backwards would silently shift a whole day's totals.
 */
export function utcOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}

/**
 * Today as `YYYY-MM-DD` in the user's own timezone.
 *
 * `new Date().toISOString().slice(0, 10)` is the tempting one-liner and it is
 * wrong: it formats in UTC, so any evening west of Greenwich reports tomorrow
 * and the day's page opens blank.
 */
export function localDateISO(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
