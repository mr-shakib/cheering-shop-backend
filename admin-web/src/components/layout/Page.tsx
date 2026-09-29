import { useEffect, type ReactNode } from "react";
import { Link } from "react-router";
import { ArrowLeft } from "lucide-react";

import { cn } from "@/lib/cn";

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · Cheering Admin`;
  }, [title]);
}

export function PageHeader({
  title,
  subtitle,
  actions,
  back,
  className,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label: string };
  className?: string;
}) {
  usePageTitle(title);
  return (
    <div className={cn("mb-6 flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {back && (
          <Link
            to={back.to}
            className="mb-2 inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
          >
            <ArrowLeft className="size-4" /> {back.label}
          </Link>
        )}
        <h1 className="text-2xl font-semibold tracking-tight text-gray-900">{title}</h1>
        {subtitle && <p className="mt-1 text-[15px] text-gray-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
    </div>
  );
}

/** The white container around a list: toolbar row, table, pagination. */
export function ListCard({ toolbar, children, className }: { toolbar?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-2xl border border-line bg-white p-4 sm:p-5", className)}>
      {toolbar && <div className="mb-4 flex flex-wrap items-center gap-3">{toolbar}</div>}
      {children}
    </div>
  );
}
