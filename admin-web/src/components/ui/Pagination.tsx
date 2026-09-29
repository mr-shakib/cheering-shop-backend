import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "@/lib/cn";
import type { PageMeta } from "@/lib/api";

function windowOf(page: number, total: number): (number | "gap")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const wanted = new Set([1, 2, 3, total - 2, total - 1, total, page - 1, page, page + 1]);
  const pages = [...wanted].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  pages.forEach((p, i) => {
    if (i > 0 && p - pages[i - 1] > 1) out.push("gap");
    out.push(p);
  });
  return out;
}

export function Pagination({
  meta,
  onPage,
  className,
}: {
  meta: PageMeta | undefined;
  onPage: (page: number) => void;
  className?: string;
}) {
  if (!meta) return null;
  const totalPages = Math.max(1, Math.ceil(meta.total / Math.max(1, meta.limit)));
  const page = Math.min(meta.page, totalPages);

  return (
    <div
      className={cn(
        "mt-2 flex flex-col items-center justify-between gap-3 border-t border-line px-2 pt-4 sm:flex-row sm:px-6",
        className,
      )}
    >
      <p className="text-[15px] text-gray-700">
        Page {page} of {totalPages}
        <span className="ml-2 text-sm text-gray-400">({meta.total.toLocaleString("en-US")} total)</span>
      </p>
      {totalPages > 1 && (
        <nav className="flex items-center gap-1.5" aria-label="Pagination">
          <button
            type="button"
            onClick={() => onPage(page - 1)}
            disabled={page <= 1}
            className="mr-2 flex size-10 items-center justify-center rounded-lg border border-gray-300 text-gray-800 hover:bg-gray-50 disabled:opacity-40"
            aria-label="Previous page"
          >
            <ChevronLeft className="size-4" />
          </button>
          {windowOf(page, totalPages).map((p, i) =>
            p === "gap" ? (
              <span key={`gap-${i}`} className="w-8 text-center text-gray-500">
                …
              </span>
            ) : (
              <button
                key={p}
                type="button"
                onClick={() => onPage(p)}
                aria-current={p === page ? "page" : undefined}
                className={cn(
                  "flex size-10 items-center justify-center rounded-lg text-[15px] text-gray-700 hover:bg-gray-50",
                  p === page && "bg-gray-100 font-medium text-gray-900",
                )}
              >
                {p}
              </button>
            ),
          )}
          <button
            type="button"
            onClick={() => onPage(page + 1)}
            disabled={page >= totalPages}
            className="ml-2 flex size-10 items-center justify-center rounded-lg border border-gray-300 text-gray-800 hover:bg-gray-50 disabled:opacity-40"
            aria-label="Next page"
          >
            <ChevronRight className="size-4" />
          </button>
        </nav>
      )}
    </div>
  );
}
