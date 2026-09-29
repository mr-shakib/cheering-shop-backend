import type { AdminOrderRow } from "@/api/orders";
import { StatusBadge, TypeBadge } from "@/components/ui/Badge";
import { DataTable, type Column } from "@/components/ui/Table";
import { dateTime, money, orderNo } from "@/lib/format";
import { orderStatus, paymentMethod } from "@/lib/vocab";

export type OrderColumn = "id" | "customer" | "vendor" | "rider" | "type" | "amount" | "payment" | "status" | "date";

const ALL: Record<OrderColumn, Column<AdminOrderRow>> = {
  id: { key: "id", header: "Order ID", cell: (o) => <span className="whitespace-nowrap text-gray-900">{orderNo(o.order_number)}</span> },
  customer: { key: "customer", header: "Customer", cell: (o) => o.customer_name ?? "—" },
  vendor: { key: "vendor", header: "Vendor", cell: (o) => o.restaurant_name },
  rider: {
    key: "rider",
    header: "Rider",
    cell: (o) =>
      o.rider_name ?? (
        <span className="text-gray-400">{o.status === "PREPARING" || o.status === "READY" ? "Awaiting rider" : "—"}</span>
      ),
  },
  type: { key: "type", header: "Type", cell: (o) => <TypeBadge type={o.business_type} /> },
  amount: { key: "amount", header: "Amount", cell: (o) => money(o.grand_total) },
  payment: { key: "payment", header: "Payment", cell: (o) => paymentMethod(o.payment_method) },
  status: { key: "status", header: "Status", cell: (o) => <StatusBadge {...orderStatus(o.status)} /> },
  date: { key: "date", header: "Date", cell: (o) => <span className="whitespace-nowrap text-gray-600">{dateTime(o.placed_at)}</span> },
};

/** The Orders table and every tab that reuses it (customer, vendor, rider, overview). */
export function OrdersTable({
  rows,
  columns,
  loading,
  error,
  onRetry,
  onOpen,
  activeId,
  empty = "No orders match.",
}: {
  rows: AdminOrderRow[] | undefined;
  columns: OrderColumn[];
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  onOpen?: (order: AdminOrderRow) => void;
  activeId?: string | null;
  empty?: string;
}) {
  return (
    <DataTable
      columns={columns.map((c) => ALL[c])}
      rows={rows}
      rowKey={(o) => o.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      onRowClick={onOpen}
      isRowActive={activeId ? (o) => o.id === activeId : undefined}
      empty={empty}
    />
  );
}
