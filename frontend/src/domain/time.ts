const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/** "3 hours ago" / "vor 3 Stunden" in the given locale. */
export function relativeTime(iso: string, locale: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.trunc(seconds / size), unit);
  }
  return rtf.format(0, "minute");
}

export function formatDate(iso: string | null, locale: string): string {
  return iso ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(iso)) : "";
}

export function formatDateTime(iso: string | null, locale: string): string {
  return iso ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso)) : "";
}

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO instant -> value for `<input type="datetime-local">` (local time, minute precision). */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** `datetime-local` value (local time) -> ISO-8601 string with UTC offset. */
export function fromLocalInput(local: string): string {
  const d = new Date(local);
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const a = Math.abs(off);
  return `${local.length === 16 ? `${local}:00` : local}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}
