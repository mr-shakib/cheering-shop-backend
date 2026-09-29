import { useState } from "react";
import { Link } from "react-router";
import { Check, CircleCheckBig, MapPin, PhoneCall, RotateCcw, UserPlus, X, XCircle } from "lucide-react";

import {
  useCancelOrder,
  useForceDeliver,
  useOrder,
  useRefundOrder,
  type AdminOrderDetail,
} from "@/api/orders";
import { Badge, StatusBadge, TypeBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ErrorState, PageSpinner } from "@/components/ui/Feedback";
import { Drawer } from "@/components/ui/Overlay";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { ago, dateTimeLong, money, orderNo, timeOnly } from "@/lib/format";
import { ORDER_STEPS, orderStatus, paymentMethod, paymentStatus } from "@/lib/vocab";

import { AssignRiderDialog } from "./AssignRiderDialog";

const RANK: Record<string, number> = { PENDING: 0, PREPARING: 2, READY: 3, PICKED_UP: 4, DELIVERED: 5 };

function Timeline({ order }: { order: AdminOrderDetail }) {
  const cancelled = order.status === "CANCELLED";
  // How far it got: for a cancelled order, the last status before the cancel.
  const reached = cancelled
    ? Math.max(0, ...order.timeline.filter((e) => e.status !== "CANCELLED").map((e) => RANK[e.status] ?? 0))
    : (RANK[order.status] ?? 0);
  const at = (status: string) => order.timeline.find((e) => e.status === status)?.at;

  return (
    <div>
      <div className="flex items-start">
        {ORDER_STEPS.map((step, i) => {
          const done = i <= reached;
          const time = at(step.key === "ACCEPTED" ? "PREPARING" : step.key);
          return (
            <div key={step.key} className="relative flex flex-1 flex-col items-center">
              {i > 0 && (
                <span
                  className={cn(
                    "absolute top-3 right-1/2 h-0.5 w-full",
                    i <= reached ? "bg-green-600" : "bg-gray-200",
                  )}
                />
              )}
              <span
                className={cn(
                  "relative z-10 flex size-6 items-center justify-center rounded-full border-2",
                  done ? "border-green-600 bg-green-600 text-white" : "border-gray-300 bg-white",
                )}
              >
                {done && <Check className="size-3.5" strokeWidth={3} />}
              </span>
              <span className={cn("mt-2 text-center text-[11px]", done ? "text-gray-700" : "text-gray-400")}>{step.label}</span>
              {time && done && <span className="text-[10px] text-gray-400">{timeOnly(time)}</span>}
            </div>
          );
        })}
      </div>
      {cancelled && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
          <XCircle className="mt-px size-4 shrink-0" />
          <span>
            Cancelled {order.cancelled_by ? `by ${order.cancelled_by.toLowerCase()}` : ""} {order.cancelled_at && `· ${dateTimeLong(order.cancelled_at)}`}
            {order.cancellation_reason && <span className="block text-red-600">“{order.cancellation_reason}”</span>}
          </span>
        </div>
      )}
    </div>
  );
}

function MoneyRow({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={cn("flex justify-between text-sm", strong ? "font-semibold text-gray-900" : "text-gray-600")}>
      <span>{label}</span>
      <span className={strong ? "" : "text-gray-900"}>{value}</span>
    </div>
  );
}

function OrderBody({ order }: { order: AdminOrderDetail }) {
  const m = order.money;
  const riderState =
    order.status === "PICKED_UP"
      ? "On the way"
      : order.status === "DELIVERED"
        ? "Delivered"
        : order.rider
          ? "Heading to pickup"
          : null;

  return (
    <>
      <Panel title="Order timeline">
        <Timeline order={order} />
      </Panel>

      <div className="grid grid-cols-2 gap-4">
        <Panel title="Customer info" className="min-w-0">
          <Link to={`/customers/${order.customer.id}`} className="block truncate text-[15px] text-gray-900 hover:text-brand-500">
            {order.customer.full_name ?? "—"}
          </Link>
          <p className="mt-1 line-clamp-2 text-xs text-gray-500" title={order.customer.delivery_address_text}>
            {order.customer.delivery_address_text}
          </p>
        </Panel>
        <Panel title="Vendor info" className="min-w-0">
          <Link to={`/vendors/${order.vendor.id}`} className="block truncate text-[15px] text-gray-900 hover:text-brand-500">
            {order.vendor.name}
          </Link>
          <div className="mt-1.5">
            <TypeBadge type={order.vendor.business_type} />
          </div>
        </Panel>
        <Panel title="Rider info" className="min-w-0">
          {order.rider ? (
            <>
              <Link to={`/riders/${order.rider.id}`} className="block truncate text-[15px] text-gray-900 hover:text-brand-500">
                {order.rider.full_name ?? order.rider.phone}
              </Link>
              <p className="mt-1 text-xs text-gray-500">{riderState}</p>
            </>
          ) : (
            <p className="text-sm text-gray-500">
              {order.status === "PREPARING" || order.status === "READY" ? "Waiting for a rider to accept" : "No rider"}
            </p>
          )}
        </Panel>
        <Panel title="Payment info" className="min-w-0">
          <p className="text-[15px] text-gray-900">{paymentMethod(order.payment.method)}</p>
          <p className="mt-1 flex items-center gap-2 text-xs text-gray-500">
            {money(m.grand_total)} <StatusBadge {...paymentStatus(order.payment.status)} dot={false} className="px-2" />
          </p>
        </Panel>
      </div>

      {order.payment.refunded_at && (
        <div className="rounded-xl border border-purple-100 bg-purple-50 px-4 py-3 text-sm text-purple-800">
          Refunded {dateTimeLong(order.payment.refunded_at)}
          {order.payment.refund_reason && <span className="block text-purple-700">“{order.payment.refund_reason}”</span>}
          <span className="mt-1 block text-xs text-purple-600">
            No payment gateway is connected: the transfer back to the customer happens outside the platform.
          </span>
        </div>
      )}

      <Panel title="Commission info">
        <div className="space-y-2">
          <MoneyRow label="Platform commission" value={money(m.commission_amount)} />
          <MoneyRow label="Vendor payout" value={money(m.vendor_payout)} />
        </div>
      </Panel>

      <Panel title="Order items">
        <div className="divide-y divide-line">
          {order.items.map((it) => (
            <div key={it.id} className="py-2.5 first:pt-0">
              <div className="flex justify-between gap-3 text-[15px] text-gray-900">
                <span>
                  {it.quantity} × {it.item_name}
                  {it.variant_name && <span className="text-gray-500"> ({it.variant_name})</span>}
                </span>
                <span>{money(it.line_total)}</span>
              </div>
              {it.add_ons.length > 0 && (
                <p className="mt-0.5 text-xs text-gray-500">
                  + {it.add_ons.map((a) => `${a.quantity && a.quantity > 1 ? `${a.quantity}× ` : ""}${a.name}`).join(", ")}
                </p>
              )}
              {it.notes && <p className="mt-0.5 text-xs text-gray-500 italic">“{it.notes}”</p>}
            </div>
          ))}
        </div>
        <div className="mt-3 space-y-1.5 border-t border-line pt-3">
          <MoneyRow label="Items" value={money(m.item_total)} />
          <MoneyRow label="Delivery fee" value={money(m.delivery_fee)} />
          {m.packaging_fee > 0 && <MoneyRow label="Packaging" value={money(m.packaging_fee)} />}
          {m.platform_fee > 0 && <MoneyRow label="Platform fee" value={money(m.platform_fee)} />}
          {m.tax_amount > 0 && <MoneyRow label="Tax" value={money(m.tax_amount)} />}
          {m.tip > 0 && <MoneyRow label="Tip" value={money(m.tip)} />}
          {m.discount > 0 && <MoneyRow label="Discount" value={`−${money(m.discount)}`} />}
          <MoneyRow label="Total" value={money(m.grand_total)} strong />
        </div>
        {order.special_instructions && (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">Note: {order.special_instructions}</p>
        )}
      </Panel>

      <Panel title="Live location">
        {order.rider_location ? (
          <p className="flex items-start gap-2 text-sm text-gray-600">
            <MapPin className="mt-0.5 size-4 shrink-0 text-gray-500" />
            <span>
              Rider is {order.rider_location.distance_to_dropoff_km.toFixed(1)} km from drop-off
              {order.rider_location.updated_at && (
                <span className="text-gray-400"> · updated {ago(order.rider_location.updated_at)}</span>
              )}
            </span>
          </p>
        ) : (
          <p className="flex items-center gap-2 text-sm text-gray-500">
            <MapPin className="size-4 shrink-0" />
            {order.status === "READY" || order.status === "PICKED_UP"
              ? "The rider has not reported a position recently."
              : "Shown while a rider is carrying the order."}
          </p>
        )}
      </Panel>
    </>
  );
}

export function OrderDrawer({ orderId, onClose }: { orderId: string | null; onClose: () => void }) {
  const order = useOrder(orderId);
  const cancel = useCancelOrder();
  const refund = useRefundOrder();
  const deliver = useForceDeliver();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [assigning, setAssigning] = useState(false);
  const o = order.data;
  const phone = o?.customer.delivery_contact_phone || o?.customer.phone;

  return (
    <Drawer
      open={!!orderId}
      onClose={onClose}
      eyebrow="Order"
      title={o ? orderNo(o.order_number) : "Order"}
      footer={
        o && (
          <div className="grid grid-cols-2 gap-3">
            <Button icon={<UserPlus className="size-4" />} disabled={!o.actions.can_assign_rider} onClick={() => setAssigning(true)}>
              {o.rider ? "Reassign rider" : "Assign rider"}
            </Button>
            {phone ? (
              <a
                href={`tel:${phone}`}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-full border border-gray-300 bg-white px-5 text-sm font-medium text-gray-800 hover:bg-gray-50"
              >
                <PhoneCall className="size-4" /> Call Customer
              </a>
            ) : (
              <Button variant="outline" disabled icon={<PhoneCall className="size-4" />}>
                No phone
              </Button>
            )}
            <Button
              variant="outline"
              icon={<RotateCcw className="size-4" />}
              disabled={!o.actions.can_refund}
              onClick={() =>
                confirm({
                  title: `Refund ${orderNo(o.order_number)}?`,
                  description: `Records that ${money(o.money.grand_total)} is owed back to the customer. It does not cancel the order.`,
                  confirmLabel: "Record refund",
                  tone: "danger",
                  reason: { label: "Reason", required: true, minLength: 3, placeholder: "Kept on the order for whoever reads the dispute later" },
                  onConfirm: (reason) =>
                    refund.mutateAsync({ id: o.id, reason }).then(() => toast("Refund recorded")),
                })
              }
            >
              Refund order
            </Button>
            <Button
              variant="danger-soft"
              icon={<X className="size-4" />}
              disabled={!o.actions.can_cancel}
              onClick={() =>
                confirm({
                  title: `Cancel ${orderNo(o.order_number)}?`,
                  description:
                    o.payment.status === "PAID"
                      ? "The customer and the vendor are told at once, and the paid amount is refunded."
                      : "The customer and the vendor are told at once.",
                  confirmLabel: "Cancel order",
                  tone: "danger",
                  reason: { label: "Reason", required: true, minLength: 3, placeholder: "Shown to the customer and the vendor" },
                  onConfirm: (reason) => cancel.mutateAsync({ id: o.id, reason }).then(() => toast("Order cancelled")),
                })
              }
            >
              Cancel order
            </Button>
            {o.actions.can_force_deliver && (
              <Button
                variant="success-soft"
                className="col-span-2"
                icon={<CircleCheckBig className="size-4" />}
                onClick={() =>
                  confirm({
                    title: "Confirm this delivery?",
                    description:
                      "Use this only when the rider cannot mark it delivered themselves. The history records an administrator as the one who confirmed it.",
                    confirmLabel: "Mark delivered",
                    tone: "success",
                    onConfirm: () => deliver.mutateAsync({ id: o.id }).then(() => toast("Order marked delivered")),
                  })
                }
              >
                Confirm delivery
              </Button>
            )}
          </div>
        )
      }
    >
      {order.isPending ? (
        <PageSpinner />
      ) : order.isError ? (
        <ErrorState error={order.error} onRetry={() => order.refetch()} />
      ) : o ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <StatusBadge {...orderStatus(o.status)} />
            <span>Placed {dateTimeLong(o.placed_at)}</span>
            {o.scheduled_for && <Badge tone="blue">Scheduled {dateTimeLong(o.scheduled_for)}</Badge>}
          </div>
          <OrderBody order={o} />
        </>
      ) : null}
      {dialog}
      {assigning && o && <AssignRiderDialog order={o} onClose={() => setAssigning(false)} />}
    </Drawer>
  );
}
