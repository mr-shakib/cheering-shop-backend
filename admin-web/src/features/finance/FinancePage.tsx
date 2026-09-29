import { useNavigate } from "react-router";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { useFinanceSummary, useTransactions, type FinanceTransaction } from "@/api/insights";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Card } from "@/components/ui/Card";
import { Change, StatCard } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { DateRangeFilter } from "@/components/ui/Inputs";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { opt } from "@/lib/api";
import { dateTime, money, orderNo } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";
import { businessTypeLabel, paymentMethod } from "@/lib/vocab";

import { RevenueChart } from "../overview/RevenueChart";

const serviceLabel = (type: string) => (type === "UNKNOWN" ? "Other" : businessTypeLabel(type));

const SERVICE_COLORS: Record<string, string> = {
  RESTAURANT: "#14b8a6",
  GROCERY: "#3b82f6",
  PHARMACY: "#facc15",
  UNKNOWN: "#cbd5e1",
};

const columns: Column<FinanceTransaction>[] = [
  {
    key: "trx",
    header: "Transaction",
    cell: (t) => <span className="font-medium whitespace-nowrap text-gray-900">{t.payment_reference ?? <span className="font-normal text-gray-500">Cash (COD)</span>}</span>,
  },
  { key: "order", header: "Order ID", cell: (t) => orderNo(t.order_number) },
  { key: "vendor", header: "Vendor", cell: (t) => t.restaurant_name },
  { key: "customer", header: "Customer", cell: (t) => t.customer_name ?? "—" },
  { key: "method", header: "Method", cell: (t) => paymentMethod(t.payment_method) },
  { key: "amount", header: "Amount", cell: (t) => <span className="font-medium text-gray-900">{money(t.amount)}</span> },
  { key: "commission", header: "Commission", cell: (t) => <span className="text-gray-600">{money(t.commission_amount)}</span> },
  { key: "date", header: "Delivered", cell: (t) => <span className="whitespace-nowrap text-gray-600">{dateTime(t.delivered_at)}</span> },
];

export function FinancePage() {
  const navigate = useNavigate();
  const list = useListParams(["days", "q", "date_from", "date_to"] as const, { days: "30" });
  const { values: v } = list;
  const days = Number(v.days) || 30;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const summary = useFinanceSummary(days);
  const tx = useTransactions({ q: opt(v.q), date_from: opt(v.date_from), date_to: opt(v.date_to), limit: list.limit, offset: list.offset });
  const s = summary.data;
  const suffix = `vs previous ${days} days`;
  const services = (s?.revenue_by_service ?? []).filter((r) => r.gmv > 0);

  return (
    <>
      <PageHeader
        title="Finance"
        subtitle="Delivered orders only"
        actions={
          <Select
            aria-label="Period"
            options={[
              { value: "7", label: "Last 7 days" },
              { value: "30", label: "Last 30 days" },
              { value: "90", label: "Last 90 days" },
              { value: "365", label: "Last 12 months" },
            ]}
            value={v.days}
            onChange={(e) => list.set({ days: e.target.value })}
          />
        }
      />
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard loading={summary.isPending} label="GMV" value={money(s?.gmv.value)} footer={<Change pct={s?.gmv.change_pct} suffix={suffix} fallback={`Nothing in the previous ${days} days`} />} />
          <StatCard
            loading={summary.isPending}
            label="Net revenue"
            value={money(s?.net_revenue.value)}
            footer={<Change pct={s?.net_revenue.change_pct} suffix={suffix} fallback="Commission + platform fees" />}
          />
          <StatCard
            loading={summary.isPending}
            label="Commission revenue"
            value={money(s?.commission_revenue.value)}
            footer={<Change pct={s?.commission_revenue.change_pct} suffix={suffix} fallback={`Nothing in the previous ${days} days`} />}
          />
          <StatCard
            loading={summary.isPending}
            label="Delivery revenue"
            value={money(s?.delivery_revenue.value)}
            footer={<Change pct={s?.delivery_revenue.change_pct} suffix={suffix} fallback="Paid on to riders" />}
          />
        </div>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_370px]">
          <RevenueChart />
          <Card className="p-5">
            <h2 className="text-base font-semibold text-gray-900">Revenue By Services</h2>
            <p className="text-xs text-gray-500">GMV share, last {days} days</p>
            {services.length === 0 ? (
              <p className="py-16 text-center text-sm text-gray-500">No delivered orders in this period.</p>
            ) : (
              <>
                <div className="h-44">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={services} dataKey="gmv" nameKey="business_type" innerRadius={52} outerRadius={70} paddingAngle={1} strokeWidth={0} isAnimationActive={false}>
                        {services.map((r) => (
                          <Cell key={r.business_type} fill={SERVICE_COLORS[r.business_type] ?? SERVICE_COLORS.UNKNOWN} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value, name) => [money(Number(value)), serviceLabel(String(name))]} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <ul className="mt-2 space-y-2.5">
                  {services.map((r) => (
                    <li key={r.business_type} className="flex items-center gap-3 text-[15px]">
                      <span className="size-2.5 rounded-full" style={{ background: SERVICE_COLORS[r.business_type] ?? SERVICE_COLORS.UNKNOWN }} />
                      <span className="flex-1 text-gray-700">{serviceLabel(r.business_type)}</span>
                      <span className="text-gray-500">{money(r.gmv)}</span>
                      <span className="w-14 text-right font-medium text-gray-900">{r.share_pct.toFixed(1)}%</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Card>
        </div>

        <ListCard
          toolbar={
            <>
              <h2 className="mr-auto text-lg font-semibold text-gray-900">Transaction details</h2>
              <SearchInput value={search} onChange={setSearch} placeholder="Search order, reference, vendor..." />
              <DateRangeFilter from={v.date_from} to={v.date_to} onChange={(date_from, date_to) => list.set({ date_from, date_to })} />
            </>
          }
        >
          <DataTable
            columns={columns}
            rows={tx.data?.items}
            rowKey={(t) => t.order_id}
            loading={tx.isPending}
            error={tx.error}
            onRetry={() => tx.refetch()}
            onRowClick={(t) => navigate(`/orders?order=${t.order_id}`)}
            empty="No delivered orders match."
          />
          <Pagination meta={tx.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
        </ListCard>
      </div>
    </>
  );
}

