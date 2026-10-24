/**
 * "1 document" / "2 documents".
 *
 * Trivial, but it was being written inline at fourteen call sites and missed at
 * several more, which is how a polished page ends up saying "1 documents".
 *
 * `irregular` covers the words where adding an "s" is wrong ("1 entry" /
 * "2 entries"); pass the full plural form, not a suffix.
 */
export function plural(count: number, word: string, irregular?: string): string {
  return count === 1 ? word : (irregular ?? `${word}s`);
}

/** The count and its noun together: "3 documents". */
export function pluralize(count: number, word: string, irregular?: string): string {
  return `${count} ${plural(count, word, irregular)}`;
}
