import { useState } from "react";

import { useVendorReviews } from "@/api/vendors";
import { Avatar, Stars } from "@/components/ui/Display";
import { EmptyState, ErrorState, PageSpinner } from "@/components/ui/Feedback";
import { Pagination } from "@/components/ui/Pagination";
import { ago, orderNo } from "@/lib/format";
import { PAGE_SIZE } from "@/lib/hooks";

export function VendorReviewsTab({ vendorId }: { vendorId: string }) {
  const [page, setPage] = useState(1);
  const reviews = useVendorReviews(vendorId, { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });

  if (reviews.isPending) return <PageSpinner />;
  if (reviews.isError) return <ErrorState error={reviews.error} onRetry={() => reviews.refetch()} />;
  const { summary, reviews: rows, meta } = reviews.data;
  const most = Math.max(1, ...Object.values(summary.histogram));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-8">
        <div>
          <p className="text-4xl font-semibold text-gray-900">{summary.rating_count ? summary.rating_avg.toFixed(1) : "—"}</p>
          <Stars value={Math.round(summary.rating_avg)} className="mt-1" />
          <p className="mt-1 text-sm text-gray-500">
            {summary.rating_count} rating{summary.rating_count === 1 ? "" : "s"}
          </p>
        </div>
        <div className="w-full max-w-56 space-y-1.5">
          {[5, 4, 3, 2, 1].map((star) => {
            const n = summary.histogram[String(star)] ?? 0;
            return (
              <div key={star} className="flex items-center gap-2 text-[11px] text-gray-500">
                <span className="w-2">{star}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <span className="block h-full rounded-full bg-amber-400" style={{ width: `${(n / most) * 100}%` }} />
                </span>
                <span className="w-6 text-right">{n}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-6 divide-y divide-line">
        {rows.length === 0 ? (
          <EmptyState>No reviews yet.</EmptyState>
        ) : (
          rows.map((r) => (
            <div key={r.id} className="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
              <div className="flex items-center gap-3">
                <Avatar name={r.customer_name} size={40} />
                <div>
                  <p className="text-[15px] font-medium text-gray-900">{r.customer_name ?? "Customer"}</p>
                  <p className="text-xs text-gray-500">
                    {ago(r.created_at)}
                    {r.order_number != null && ` · ${orderNo(r.order_number)}`}
                  </p>
                </div>
              </div>
              <div>
                <Stars value={r.restaurant_rating} />
                {r.comment ? (
                  <p className="mt-1.5 text-sm text-gray-700">{r.comment}</p>
                ) : (
                  <p className="mt-1.5 text-sm text-gray-400 italic">No comment</p>
                )}
              </div>
            </div>
          ))
        )}
      </div>
      <Pagination meta={meta} onPage={setPage} />
    </div>
  );
}
