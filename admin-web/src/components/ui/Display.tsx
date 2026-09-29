/* Small read-only building blocks shared by the detail screens. */
import { useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ExternalLink, FileText, Star } from "lucide-react";

import { cn } from "@/lib/cn";
import { fileName, initials } from "@/lib/format";

const avatarTones = [
  "bg-green-100 text-green-700",
  "bg-blue-100 text-blue-700",
  "bg-purple-100 text-purple-700",
  "bg-orange-100 text-orange-700",
  "bg-brand-100 text-brand-600",
  "bg-teal-100 text-teal-700",
];

function toneFor(seed: string) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return avatarTones[h % avatarTones.length];
}

/** A photo, or the person's initials on a colour derived from their name. */
export function Avatar({
  src,
  name,
  size = 32,
  rounded = "full",
  className,
}: {
  src?: string | null;
  name?: string | null;
  size?: 24 | 32 | 40 | 48 | 80 | 108 | 144;
  rounded?: "full" | "lg" | "xl";
  className?: string;
}) {
  const [broken, setBroken] = useState(false);
  const sizeClass = {
    24: "size-6 text-[10px]",
    32: "size-8 text-xs",
    40: "size-10 text-sm",
    48: "size-12 text-base",
    80: "size-20 text-2xl",
    108: "size-27 text-3xl",
    144: "size-36 text-4xl",
  }[size];
  const round = { full: "rounded-full", lg: "rounded-lg", xl: "rounded-xl" }[rounded];
  if (src && !broken) {
    return (
      <img
        src={src}
        alt=""
        onError={() => setBroken(true)}
        className={cn("shrink-0 bg-gray-100 object-cover", sizeClass, round, className)}
      />
    );
  }
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-semibold",
        sizeClass,
        round,
        toneFor(name ?? "?"),
        className,
      )}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}

/** Name with avatar, for the first column of people/vendor tables. */
export function Identity({
  src,
  name,
  sub,
  rounded,
}: {
  src?: string | null;
  name: string | null | undefined;
  sub?: ReactNode;
  rounded?: "full" | "lg";
}) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <Avatar src={src} name={name} size={32} rounded={rounded} />
      <span className="min-w-0">
        <span className="block truncate text-gray-900">{name || "—"}</span>
        {sub && <span className="block truncate text-xs text-gray-500">{sub}</span>}
      </span>
    </span>
  );
}

/** "↑ 2% vs yesterday". With nothing to compare against (the API sends a null
 * change when the previous period was zero) it shows `fallback` instead. */
export function Change({ pct, suffix, fallback }: { pct: number | null | undefined; suffix?: string; fallback?: string }) {
  if (pct === null || pct === undefined) {
    return <span className="text-xs text-gray-500">{fallback ?? ""}</span>;
  }
  const up = pct >= 0;
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <span className={cn("inline-flex items-center gap-0.5 font-medium", up ? "text-green-600" : "text-red-500")}>
        {up ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />}
        {Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}%
      </span>
      {suffix && <span className="text-gray-500">{suffix}</span>}
    </span>
  );
}

/** A stat card: label, big value, and a footer line (a change or a note). */
export function StatCard({
  label,
  value,
  footer,
  className,
  loading,
}: {
  label: ReactNode;
  value: ReactNode;
  footer?: ReactNode;
  className?: string;
  loading?: boolean;
}) {
  return (
    <div className={cn("rounded-2xl border border-line bg-white p-4", className)}>
      <p className="text-[13px] text-gray-700">{label}</p>
      {loading ? (
        <div className="mt-2 h-8 w-24 animate-pulse rounded bg-gray-100" />
      ) : (
        <p className="mt-1.5 truncate text-xl leading-8 font-semibold tracking-tight text-gray-900 sm:text-[26px] sm:leading-9">{value}</p>
      )}
      {footer && <div className="mt-1 min-h-4 text-xs text-gray-500">{footer}</div>}
    </div>
  );
}

/** A plain tile (Vendor Withdrawal, Rider earnings): grey border, label, value. */
export function Tile({ label, value, className }: { label: ReactNode; value: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-gray-200 bg-page px-3.5 py-3.5", className)}>
      <p className="text-sm text-gray-600">{label}</p>
      <p className="mt-2 text-xl font-semibold text-gray-900">{value}</p>
    </div>
  );
}

/** Label on the left, value on the right (Store Information, Pricing). */
export function InfoList({
  rows,
  className,
  valueClassName,
  labelWidth = "sm:w-52",
}: {
  rows: { label: ReactNode; value: ReactNode; hidden?: boolean }[];
  className?: string;
  valueClassName?: string;
  labelWidth?: string;
}) {
  return (
    <dl className={cn("space-y-3.5 text-sm", className)}>
      {rows
        .filter((r) => !r.hidden)
        .map((r, i) => (
          <div key={i} className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
            <dt className={cn("shrink-0 text-gray-600", labelWidth)}>{r.label}</dt>
            <dd className={cn("min-w-0 font-semibold break-words text-gray-900", valueClassName)}>
              {r.value === null || r.value === undefined || r.value === "" ? (
                <span className="font-normal text-gray-400">—</span>
              ) : (
                r.value
              )}
            </dd>
          </div>
        ))}
    </dl>
  );
}

/** The blue "nid.pdf ↗" chip that opens a document. */
export function DocumentChip({ url, label }: { url: string; label?: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex max-w-full items-center gap-2 rounded-md bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-100"
    >
      <span className="truncate">{label ?? fileName(url)}</span>
      <ExternalLink className="size-4 shrink-0" />
    </a>
  );
}

/** A bordered document card (Vendor/Rider Details → Document). */
export function DocumentCard({ label, url }: { label: string; url: string }) {
  const [broken, setBroken] = useState(false);
  const isImage = !broken && /\.(png|jpe?g|webp|gif)(\?|$)/i.test(url);
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3">
      <p className="mb-3 text-sm text-gray-700">{label}</p>
      <div className="flex items-center gap-3">
        {isImage ? (
          <img src={url} alt="" onError={() => setBroken(true)} className="size-9 shrink-0 rounded-md border border-line object-cover" />
        ) : (
          <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600">
            <FileText className="size-4" />
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-blue-600">{fileName(url)}</span>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${label}`}
          className="flex size-8 shrink-0 items-center justify-center rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50"
        >
          <ExternalLink className="size-4" />
        </a>
      </div>
    </div>
  );
}

export function Rating({ value, count, className }: { value: number | null | undefined; count?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs text-gray-800", className)}>
      <Star className="size-3.5 fill-amber-400 text-amber-400" />
      {value ? value.toFixed(1) : "—"}
      {count !== undefined && <span className="text-gray-500">({count})</span>}
    </span>
  );
}

export function Stars({ value, className }: { value: number; className?: string }) {
  return (
    <span className={cn("inline-flex gap-0.5", className)} aria-label={`${value} out of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={cn("size-3.5", i <= value ? "fill-amber-400 text-amber-400" : "fill-gray-200 text-gray-200")}
        />
      ))}
    </span>
  );
}
