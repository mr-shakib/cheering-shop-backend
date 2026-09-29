import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

import { EmptyState, ErrorState } from "./Feedback";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  className?: string;
  headerClassName?: string;
  align?: "left" | "right" | "center";
}

const alignClass = { left: "text-left", right: "text-right", center: "text-center" };

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  isRowActive,
  loading,
  error,
  onRetry,
  empty = "Nothing here yet.",
  skeletonRows = 8,
  className,
  minWidth = 760,
}: {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  isRowActive?: (row: T) => boolean;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: ReactNode;
  skeletonRows?: number;
  className?: string;
  minWidth?: number;
}) {
  if (error && !rows?.length) return <ErrorState error={error} onRetry={onRetry} />;

  return (
    <div className={cn("scrollbar-thin -mx-1 overflow-x-auto px-1", className)}>
      <table className="w-full border-collapse text-sm" style={{ minWidth }}>
        <thead>
          <tr className="border-b border-line">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cn(
                  "px-3.5 py-3 text-xs font-semibold tracking-wider whitespace-nowrap text-gray-900 uppercase",
                  alignClass[c.align ?? "left"],
                  c.headerClassName,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && !rows?.length
            ? Array.from({ length: skeletonRows }, (_, i) => (
                <tr key={i} className="border-b border-line">
                  {columns.map((c) => (
                    <td key={c.key} className="px-3.5 py-3.5">
                      <div className="h-4 w-3/4 animate-pulse rounded bg-gray-100" />
                    </td>
                  ))}
                </tr>
              ))
            : rows?.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "border-b border-line text-gray-800 transition-colors last:border-b-0",
                    onRowClick && "cursor-pointer hover:bg-gray-50",
                    isRowActive?.(row) && "bg-brand-50/60 hover:bg-brand-50",
                  )}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn("px-3.5 py-3 align-middle", alignClass[c.align ?? "left"], c.className)}
                    >
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
      {!loading && rows && rows.length === 0 && <EmptyState>{empty}</EmptyState>}
    </div>
  );
}
