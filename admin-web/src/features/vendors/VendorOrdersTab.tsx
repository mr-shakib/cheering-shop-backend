import { useState } from "react";

import { useOrders } from "@/api/orders";
import { SearchInput, Select } from "@/components/ui/Field";
import { DateRangeFilter } from "@/components/ui/Inputs";
import { Pagination } from "@/components/ui/Pagination";
import { opt } from "@/lib/api";
import { PAGE_SIZE, useDebounced } from "@/lib/hooks";

import { OrderDrawer } from "../orders/OrderDrawer";
import { OrdersTable, type OrderColumn } from "../orders/OrdersTable";

export const PARTY_STATUS_OPTIONS = [
  { value: "ACTIVE", label: "In progress" },
  { value: "PREPARING", label: "Preparing" },
  { value: "PICKED_UP", label: "On delivery" },
  { value: "DELIVERED", label: "Delivered" },
  { value: "CANCELLED", label: "Cancelled" },
];

const PAYMENT_OPTIONS = [
  { value: "COD", label: "Cash on delivery" },
  { value: "BKASH", label: "bKash" },
  { value: "CARD", label: "Card" },
  { value: "WALLET", label: "Wallet" },
];

/** One party's orders, with the Orders screen's filters. Used by the vendor
 * and rider profiles. */
export function PartyOrders({ filter, columns }: { filter: { restaurant_id?: string; rider_id?: string }; columns: OrderColumn[] }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [payment, setPayment] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const debounced = useDebounced(q, 300);
  const orders = useOrders({
    ...filter,
    q: opt(debounced),
    status: opt(status),
    payment_method: opt(payment),
    date_from: opt(from),
    date_to: opt(to),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });
  const reset = () => setPage(1);

  return (
    <div className="rounded-xl border border-line p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchInput
          value={q}
          onChange={(v) => {
            setQ(v);
            reset();
          }}
          placeholder="Search Order Id, Customer..."
        />
        <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
          <Select
            aria-label="Status"
            placeholder="All Status"
            options={PARTY_STATUS_OPTIONS}
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              reset();
            }}
          />
          <Select
            aria-label="Payment method"
            placeholder="Payment Method"
            options={PAYMENT_OPTIONS}
            value={payment}
            onChange={(e) => {
              setPayment(e.target.value);
              reset();
            }}
          />
          <DateRangeFilter
            from={from}
            to={to}
            onChange={(f, t) => {
              setFrom(f);
              setTo(t);
              reset();
            }}
          />
        </div>
      </div>
      <OrdersTable
        rows={orders.data?.items}
        loading={orders.isPending}
        error={orders.error}
        onRetry={() => orders.refetch()}
        columns={columns}
        onOpen={(o) => setOpen(o.id)}
        activeId={open}
        empty="No orders match."
      />
      <Pagination meta={orders.data?.meta} onPage={setPage} />
      <OrderDrawer orderId={open} onClose={() => setOpen(null)} />
    </div>
  );
}

export function VendorOrdersTab({ vendorId }: { vendorId: string }) {
  return <PartyOrders filter={{ restaurant_id: vendorId }} columns={["id", "customer", "rider", "amount", "payment", "status", "date"]} />;
}
