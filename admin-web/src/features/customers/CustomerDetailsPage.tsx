import type { ReactNode } from "react";
import { useParams, useSearchParams } from "react-router";
import { Ban, CalendarClock, CircleUser, Clock, Mail, MapPin, PhoneCall, ShieldCheck } from "lucide-react";

import { useCustomer, useSetAccountActive } from "@/api/customers";
import { useOrders } from "@/api/orders";
import { PageHeader } from "@/components/layout/Page";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Avatar } from "@/components/ui/Display";
import { ErrorState, PageSpinner } from "@/components/ui/Feedback";
import { Pagination } from "@/components/ui/Pagination";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { ago, count, dateTimeLong, money } from "@/lib/format";
import { PAGE_SIZE } from "@/lib/hooks";

import { OrderDrawer } from "../orders/OrderDrawer";
import { OrdersTable } from "../orders/OrdersTable";

function Contact({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <p className="flex items-center gap-3 text-[15px] text-gray-700 [&>svg]:size-5 [&>svg]:shrink-0 [&>svg]:text-gray-600">
      {icon}
      <span className="min-w-0 break-words">{children}</span>
    </p>
  );
}

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone: string }) {
  return (
    <div className={cn("rounded-xl border p-3.5", tone)}>
      <p className="text-sm">{label}</p>
      <p className="mt-2 text-xl font-semibold">{value}</p>
    </div>
  );
}

export function CustomerDetailsPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const openOrder = params.get("order");
  const customer = useCustomer(id);
  const orders = useOrders({ customer_id: id, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }, !!id);
  const setActive = useSetAccountActive();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();

  const setParam = (k: string, v: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (v) next.set(k, v);
        else next.delete(k);
        return next;
      },
      { replace: true },
    );

  if (customer.isPending) return <PageSpinner />;
  if (customer.isError) {
    return (
      <>
        <PageHeader title="Customer Details" back={{ to: "/customers", label: "Back to customers" }} />
        <Card>
          <ErrorState error={customer.error} onRetry={() => customer.refetch()} />
        </Card>
      </>
    );
  }
  const c = customer.data;

  return (
    <>
      <PageHeader
        title="Customer Details"
        back={{ to: "/customers", label: "Back to customers" }}
        actions={
          c.is_active ? (
            <Button
              variant="danger-soft"
              icon={<Ban className="size-4" />}
              onClick={() =>
                confirm({
                  title: `Block ${c.full_name ?? "this customer"}?`,
                  description: "They are signed out everywhere and cannot sign in or order until you unblock them.",
                  confirmLabel: "Block customer",
                  tone: "danger",
                  onConfirm: () => setActive.mutateAsync({ id: c.id, isActive: false }).then(() => toast("Customer blocked")),
                })
              }
            >
              Block customer
            </Button>
          ) : (
            <Button
              variant="success-soft"
              icon={<ShieldCheck className="size-4" />}
              loading={setActive.isPending}
              onClick={() =>
                setActive.mutate(
                  { id: c.id, isActive: true },
                  { onSuccess: () => toast("Customer unblocked"), onError: (e) => toast(errorMessage(e), "error") },
                )
              }
            >
              Unblock customer
            </Button>
          )
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Card className="flex flex-col gap-6 p-5 sm:flex-row sm:items-start">
          <div className="shrink-0">
            <Avatar src={c.avatar_url} name={c.full_name} size={144} rounded="xl" />
            <h2 className="mt-4 max-w-40 text-2xl font-semibold break-words text-gray-900">{c.full_name ?? "Unnamed"}</h2>
            {!c.is_active && (
              <Badge tone="red" className="mt-2">
                Blocked
              </Badge>
            )}
          </div>
          <div className="min-w-0 space-y-4 pt-1">
            <Contact icon={<PhoneCall />}>
              {c.phone ? (
                <a href={`tel:${c.phone}`} className="hover:text-brand-500">
                  {c.phone}
                </a>
              ) : (
                "No phone"
              )}
            </Contact>
            <Contact icon={<Mail />}>{c.email ?? "No email"}</Contact>
            <Contact icon={<CircleUser />}>
              <span className="font-mono text-sm">User ID: {c.id}</span>
            </Contact>
            <Contact icon={<Clock />}>Joined {dateTimeLong(c.created_at)}</Contact>
            <Contact icon={<CalendarClock />}>{c.last_login_at ? `Last seen ${ago(c.last_login_at)}` : "Never signed in"}</Contact>
            <Contact icon={<MapPin />}>{c.default_address ?? "No saved address"}</Contact>
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="mb-4 text-base font-semibold text-gray-900">Statistics</h2>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Total Order" value={count(c.stats.total_orders)} tone="border-blue-200 bg-blue-50 text-blue-900 [&>p:first-child]:text-blue-600" />
            <Stat label="Total Spent" value={money(c.stats.total_spent)} tone="border-purple-200 bg-purple-50 text-purple-900 [&>p:first-child]:text-purple-600" />
            <Stat label="Average Order" value={money(c.stats.average_order)} tone="border-orange-200 bg-orange-50 text-orange-900 [&>p:first-child]:text-orange-600" />
            <Stat label="Canceled Orders" value={count(c.stats.cancelled_orders)} tone="border-red-200 bg-red-50 text-red-900 [&>p:first-child]:text-red-500" />
          </div>
          <p className="mt-3 text-xs text-gray-500">
            Spent and average count delivered orders only ({count(c.stats.delivered_orders)} delivered).
          </p>
        </Card>
      </div>

      <Card className="mt-5 p-5">
        <h2 className="mb-2 text-lg font-semibold text-gray-900">Recent orders</h2>
        <OrdersTable
          rows={orders.data?.items}
          loading={orders.isPending}
          error={orders.error}
          onRetry={() => orders.refetch()}
          columns={["id", "vendor", "type", "amount", "status", "date"]}
          onOpen={(o) => setParam("order", o.id)}
          activeId={openOrder}
          empty="This customer has not ordered yet."
        />
        <Pagination meta={orders.data?.meta} onPage={(p) => setParam("page", String(p))} />
      </Card>
      <OrderDrawer orderId={openOrder} onClose={() => setParam("order", null)} />
      {dialog}
    </>
  );
}
