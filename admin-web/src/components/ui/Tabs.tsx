import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface TabItem<K extends string> {
  key: K;
  label: ReactNode;
}

/** Underlined tabs (Vendor Details, Category Restaurant/Store). */
export function Tabs<K extends string>({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: TabItem<K>[];
  active: K;
  onChange: (key: K) => void;
  className?: string;
}) {
  return (
    <div className={cn("scrollbar-thin overflow-x-auto", className)}>
      <div role="tablist" className="inline-flex min-w-max border-b border-gray-200">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={t.key === active}
            onClick={() => onChange(t.key)}
            className={cn(
              "-mb-px border-b-2 px-5 py-3 text-base font-medium transition-colors",
              t.key === active
                ? "border-brand-500 text-brand-500"
                : "border-transparent text-gray-600 hover:text-gray-900",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Rounded filter chips (Live Chat's All / Open / Pending, Live Tracking). */
export function Chips<K extends string>({
  items,
  active,
  onChange,
  className,
}: {
  items: { key: K; label: ReactNode }[];
  active: K;
  onChange: (key: K) => void;
  className?: string;
}) {
  return (
    <div className={cn("scrollbar-thin flex gap-2 overflow-x-auto pb-1", className)}>
      {items.map((i) => (
        <button
          key={i.key}
          type="button"
          onClick={() => onChange(i.key)}
          className={cn(
            "h-8 shrink-0 rounded-full border px-4 text-xs font-medium whitespace-nowrap transition-colors",
            i.key === active
              ? "border-brand-500 bg-brand-50 text-brand-500"
              : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
          )}
        >
          {i.label}
        </button>
      ))}
    </div>
  );
}

/** The 7 day / 30 day / 12 Month toggle. */
export function Segmented<K extends string>({
  items,
  active,
  onChange,
}: {
  items: { key: K; label: string }[];
  active: K;
  onChange: (key: K) => void;
}) {
  return (
    <div className="inline-flex rounded-lg bg-gray-100 p-1">
      {items.map((i) => (
        <button
          key={i.key}
          type="button"
          onClick={() => onChange(i.key)}
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            i.key === active ? "bg-white text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-900",
          )}
        >
          {i.label}
        </button>
      ))}
    </div>
  );
}
