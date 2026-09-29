import type { ReactNode } from "react";
import { Carrot, Pill, Utensils } from "lucide-react";

import { cn } from "@/lib/cn";
import { businessTypeLabel, type Label, type Tone } from "@/lib/vocab";

const tones: Record<Tone, string> = {
  green: "bg-green-50 text-green-600",
  orange: "bg-orange-50 text-orange-500",
  blue: "bg-blue-50 text-blue-600",
  red: "bg-red-50 text-red-500",
  gray: "bg-slate-100 text-slate-500",
  purple: "bg-purple-50 text-purple-600",
  pink: "bg-brand-50 text-brand-500",
  teal: "bg-emerald-50 text-emerald-600",
};

const dots: Record<Tone, string> = {
  green: "bg-green-500",
  orange: "bg-orange-400",
  blue: "bg-blue-500",
  red: "bg-red-500",
  gray: "bg-slate-400",
  purple: "bg-purple-500",
  pink: "bg-brand-500",
  teal: "bg-emerald-500",
};

export function Badge({
  tone = "gray",
  dot = false,
  icon,
  className,
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {dot && <span className={cn("size-1.5 rounded-full", dots[tone])} />}
      {icon}
      {children}
    </span>
  );
}

/** A status pill from one of the vocab lookups: `<StatusBadge {...orderStatus(o.status)} />`. */
export function StatusBadge({ label, tone, dot = true, className }: Label & { dot?: boolean; className?: string }) {
  return (
    <Badge tone={tone} dot={dot} className={className}>
      {label}
    </Badge>
  );
}

/** The Food / Grocery / Medicine tag. */
export function TypeBadge({ type, className }: { type: string | null | undefined; className?: string }) {
  if (!type) return <span className="text-sm text-gray-400">—</span>;
  const map: Record<string, { tone: Tone; icon: ReactNode }> = {
    RESTAURANT: { tone: "pink", icon: <Utensils className="size-3" /> },
    GROCERY: { tone: "green", icon: <Carrot className="size-3" /> },
    PHARMACY: { tone: "teal", icon: <Pill className="size-3" /> },
  };
  const style = map[type] ?? { tone: "gray" as Tone, icon: null };
  return (
    <Badge tone={style.tone} icon={style.icon} className={cn("rounded-md", className)}>
      {businessTypeLabel(type)}
    </Badge>
  );
}
