import { format, formatDistanceToNowStrict, isValid, parseISO } from "date-fns";

/** Money is whole taka as a JSON number (docs/ADMIN-API.md, Conventions). */
export function money(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  return `৳${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

/** Axis ticks: 450k, 1.2M. */
export function compact(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${+(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

export function count(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US");
}

/** A fraction (0.15) as a percentage ("15%"). */
export function pct(rate: number | null | undefined, digits = 2): string {
  if (rate === null || rate === undefined) return "—";
  return `${+(rate * 100).toFixed(digits)}%`;
}

export function orderNo(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : `ORD-${n}`;
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const d = typeof value === "string" ? parseISO(value) : value;
  return isValid(d) ? d : null;
}

/** "Aug 22, 20:17" — table cells. */
export function dateTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "MMM d, HH:mm") : "—";
}

/** "Aug 22, 2026 (10:17 AM)" — detail headers. */
export function dateTimeLong(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "MMM d, yyyy (h:mm a)") : "—";
}

/** "1 Jun 2026" */
export function dateOnly(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "d MMM yyyy") : "—";
}

export function timeOnly(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "h:mm a") : "";
}

export function ago(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? `${formatDistanceToNowStrict(d)} ago` : "—";
}

/** yyyy-MM-dd for date filters (calendar days, per the API). */
export function isoDay(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "")).toUpperCase() || "?";
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "—";
  return s
    .toLowerCase()
    .split(/[_\s]+/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

/** The file name at the end of a document URL, for the blue document chips. */
export function fileName(url: string): string {
  try {
    const path = new URL(url).pathname;
    const last = decodeURIComponent(path.split("/").pop() ?? "");
    return last || url;
  } catch {
    return url;
  }
}
