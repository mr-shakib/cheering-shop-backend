import { Link } from "react-router";

import { usePayoutAction, usePayouts } from "@/api/vendors";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { SearchInput, Select } from "@/components/ui/Field";
import { DateRangeFilter } from "@/components/ui/Inputs";
import { Pagination } from "@/components/ui/Pagination";
import { opt } from "@/lib/api";
import { count } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";

import { PAYOUT_STATUS_OPTIONS, PayoutsTable, payoutStatusParam } from "../payouts/PayoutsTable";

export function VendorWithdrawalsPage() {
  const list = useListParams(["q", "status", "date_from", "date_to"] as const, { status: "PROCESSING" });
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const payouts = usePayouts({
    q: opt(v.q),
    status: payoutStatusParam(v.status),
    date_from: opt(v.date_from),
    date_to: opt(v.date_to),
    limit: list.limit,
    offset: list.offset,
  });
  const action = usePayoutAction();
  const total = payouts.data?.meta.total;
  const label = { PROCESSING: "pending", COMPLETED: "paid", FAILED: "failed", ALL: "" }[v.status] ?? "";

  return (
    <>
      <PageHeader
        title="Vendor Withdrawal"
        subtitle={total !== undefined ? `${count(total)} ${label ? `${label} ` : ""}withdrawal${total === 1 ? "" : "s"}` : " "}
      />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search withdrawal ID or vendor..." />
            <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
              <Select aria-label="Status" options={PAYOUT_STATUS_OPTIONS} value={v.status} onChange={(e) => list.set({ status: e.target.value })} />
              <DateRangeFilter from={v.date_from} to={v.date_to} onChange={(date_from, date_to) => list.set({ date_from, date_to })} />
            </div>
          </>
        }
      >
        <PayoutsTable
          rows={payouts.data?.items}
          loading={payouts.isPending}
          error={payouts.error}
          onRetry={() => payouts.refetch()}
          party={{
            header: "Vendor",
            cell: (p) => (
              <Link to={`/vendors/${p.restaurant_id}?tab=withdrawal`} className="text-gray-900 hover:text-brand-500">
                {p.restaurant_name}
              </Link>
            ),
            name: (p) => p.restaurant_name,
          }}
          act={(vars) => action.mutateAsync(vars)}
        />
        <Pagination meta={payouts.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
    </>
  );
}
