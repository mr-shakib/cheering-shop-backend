import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { BarChart3, Bike, CircleAlert, Clock, FileText, Hourglass } from "lucide-react";

import { useDashboard } from "@/api/insights";
import { PageHeader, usePageTitle } from "@/components/layout/Page";
import { Card } from "@/components/ui/Card";
import { Change, StatCard } from "@/components/ui/Display";
import { ErrorState } from "@/components/ui/Feedback";
import { cn } from "@/lib/cn";
import { count, money } from "@/lib/format";

import { OrdersTable } from "../orders/OrdersTable";
import { RevenueChart } from "./RevenueChart";

function LiveRow({
  icon,
  tone,
  label,
  value,
  to,
}: {
  icon: ReactNode;
  tone: string;
  label: string;
  value: ReactNode;
  to?: string;
}) {
  const inner = (
    <>
      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-full [&>svg]:size-[18px]", tone)}>
        {icon}
      </span>
      <span className="flex-1 text-[15px] text-gray-700">{label}</span>
      <span className="text-lg font-semibold text-gray-900">{value}</span>
    </>
  );
  const cls = "flex items-center gap-3 border-b border-line py-2.5 last:border-b-0";
  return to ? (
    <Link to={to} className={cn(cls, "-mx-2 rounded-lg px-2 hover:bg-gray-50")}>
      {inner}
    </Link>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

export function OverviewPage() {
  usePageTitle("Overview");
  const dashboard = useDashboard();
  const navigate = useNavigate();
  const d = dashboard.data;
  const loading = dashboard.isPending;

  if (dashboard.isError && !d) {
    return (
      <>
        <PageHeader title="Overview" />
        <Card>
          <ErrorState error={dashboard.error} onRetry={() => dashboard.refetch()} />
        </Card>
      </>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="sr-only">Overview</h1>
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 min-[87.5rem]:grid-cols-6">
        <StatCard
          loading={loading}
          label="Revenue today"
          value={money(d?.revenue_today.value)}
          footer={<Change pct={d?.revenue_today.change_pct} suffix="vs yesterday" fallback={d && `${money(d.revenue_today.previous)} yesterday`} />}
        />
        <StatCard
          loading={loading}
          label="Orders today"
          value={count(d?.orders_today.value)}
          footer={<Change pct={d?.orders_today.change_pct} suffix="vs yesterday" fallback={d && `${count(d.orders_today.previous)} yesterday`} />}
        />
        <StatCard loading={loading} label="Active riders" value={count(d?.active_riders)} footer="On shift now" />
        <StatCard loading={loading} label="Online vendors" value={count(d?.online_vendors)} footer="Open and approved" />
        <Link to="/vendor-applications" className="rounded-2xl transition-shadow hover:shadow-md">
          <StatCard
            loading={loading}
            label="Pending approvals"
            value={count(d?.pending_approvals.total)}
            footer={d && `${d.pending_approvals.vendors} vendors, ${d.pending_approvals.riders} riders`}
          />
        </Link>
        <Link to="/support?status=ACTIVE" className="rounded-2xl transition-shadow hover:shadow-md">
          <StatCard
            loading={loading}
            label="Support tickets"
            value={count(d?.support_tickets.open)}
            footer={d && `${d.support_tickets.urgent} Urgent`}
          />
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_370px]">
        <RevenueChart />
        <Card className="p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Live order</h2>
            <span className="relative flex size-2.5" title="Refreshes every 30 seconds">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-green-400 opacity-60" />
              <span className="relative inline-flex size-2.5 rounded-full bg-green-500" />
            </span>
          </div>
          <LiveRow icon={<FileText />} tone="bg-blue-100 text-blue-600" label="New order" value={count(d?.live_orders.new)} to="/orders?status=NEW" />
          <LiveRow icon={<Clock />} tone="bg-purple-100 text-purple-600" label="Preparing" value={count(d?.live_orders.preparing)} to="/orders?status=PREPARING" />
          <LiveRow icon={<Hourglass />} tone="bg-amber-100 text-amber-600" label="Awaiting rider" value={count(d?.live_orders.awaiting_rider)} to="/orders?awaiting_rider=true" />
          <LiveRow icon={<Bike />} tone="bg-green-100 text-green-600" label="On delivery" value={count(d?.live_orders.on_delivery)} to="/orders?status=PICKED_UP" />
          <LiveRow icon={<CircleAlert />} tone="bg-red-100 text-red-500" label="Canceled today" value={count(d?.live_orders.cancelled_today)} />
          <LiveRow
            icon={<BarChart3 />}
            tone="bg-indigo-100 text-indigo-600"
            label="AVG Delivery"
            value={d?.live_orders.avg_delivery_minutes != null ? `${d.live_orders.avg_delivery_minutes}m` : "—"}
          />
        </Card>
      </div>

      <Card className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Recent orders</h2>
          <Link to="/orders" className="text-sm font-medium text-brand-500 hover:underline">
            View all
          </Link>
        </div>
        <OrdersTable
          rows={d?.recent_orders}
          loading={loading}
          columns={["id", "customer", "vendor", "type", "amount", "status"]}
          onOpen={(o) => navigate(`/orders?order=${o.id}`)}
          empty="No orders yet."
        />
      </Card>
    </div>
  );
}
