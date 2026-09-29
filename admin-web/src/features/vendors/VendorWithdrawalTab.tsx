import { useState } from "react";

import { usePayoutAction, usePayouts, useVendorFinance } from "@/api/vendors";
import { Tile } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { DateRangeFilter } from "@/components/ui/Inputs";
import { Pagination } from "@/components/ui/Pagination";
import { opt } from "@/lib/api";
import { money } from "@/lib/format";
import { PAGE_SIZE, useDebounced } from "@/lib/hooks";

import { PAYOUT_STATUS_OPTIONS, PayoutsTable, payoutStatusParam } from "../payouts/PayoutsTable";

export function VendorWithdrawalTab({ vendorId }: { vendorId: string }) {
  const finance = useVendorFinance(vendorId);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("ALL");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const debounced = useDebounced(q, 300);
  const payouts = usePayouts({
    restaurant_id: vendorId,
    q: opt(debounced),
    status: payoutStatusParam(status),
    date_from: opt(from),
    date_to: opt(to),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });
  const action = usePayoutAction();
  const f = finance.data;

  return (
    <div className="space-y-5">
      <div className="grid gap-3 rounded-xl border border-line p-4 sm:grid-cols-2 xl:grid-cols-5">
        <Tile label="Total Earning" value={money(f?.total_earning)} />
        <Tile label="Total commission" value={money(f?.total_commission)} />
        <Tile label="Total Payout" value={money(f?.total_payout)} />
        <Tile label="Pending Amount" value={money(f?.pending_amount)} />
        <Tile label="Available balance" value={money(f?.available_balance)} />
      </div>
      <div className="rounded-xl border border-line p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <SearchInput
            value={q}
            onChange={(v) => {
              setQ(v);
              setPage(1);
            }}
            placeholder="Search withdrawal ID..."
          />
          <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
            <Select
              aria-label="Status"
              options={PAYOUT_STATUS_OPTIONS}
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            />
            <DateRangeFilter
              from={from}
              to={to}
              onChange={(a, b) => {
                setFrom(a);
                setTo(b);
                setPage(1);
              }}
            />
          </div>
        </div>
        <PayoutsTable
          rows={payouts.data?.items}
          loading={payouts.isPending}
          error={payouts.error}
          onRetry={() => payouts.refetch()}
          showParty={false}
          party={{ header: "Vendor", cell: (p) => p.restaurant_name, name: (p) => p.restaurant_name }}
          act={(vars) => action.mutateAsync(vars)}
        />
        <Pagination meta={payouts.data?.meta} onPage={setPage} />
      </div>
    </div>
  );
}
