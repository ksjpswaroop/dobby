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

/**
 * Parse a timestamp the API produced.
 *
 * The backend stores and returns naive UTC — `2026-07-27T20:16:48`, with no
 * `Z`. JavaScript reads a suffix-less string as *local* time, so every such
 * stamp rendered hours off, and in the wrong direction depending on where you
 * are. Three pages had already grown their own `endsWith('Z')` patch and four
 * others had not, which is the argument for it living here.
 *
 * A string that already carries a zone (`Z` or `±HH:MM`) is left alone.
 */
export function parseUTC(iso: string): Date {
  if (!iso) return new Date(NaN);
  const zoned = /([Zz]|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(zoned ? iso : `${iso}Z`);
}

/** A timestamp as a local clock time, e.g. "3:16 PM". */
export function formatTime(iso: string): string {
  return parseUTC(iso).toLocaleTimeString(undefined, {
    hour: 'numeric', minute: '2-digit',
  });
}

/** A timestamp as a local date and time. */
export function formatDateTime(iso: string): string {
  return parseUTC(iso).toLocaleString();
}

/** "Today", "Yesterday", or a full local date — for grouping a feed by day. */
export function dayLabel(iso: string): string {
  const d = parseUTC(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (sameDay(d, today)) return 'Today';
  if (sameDay(d, yesterday)) return 'Yesterday';
  return d.toLocaleDateString(undefined, {
    month: 'long', day: 'numeric', year: 'numeric',
  });
}
