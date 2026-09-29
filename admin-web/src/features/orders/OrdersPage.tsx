import { useState } from "react";
import { Upload } from "lucide-react";

import { useOrders } from "@/api/orders";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { SearchInput, Select } from "@/components/ui/Field";
import { DateRangeFilter } from "@/components/ui/Inputs";
import { Pagination } from "@/components/ui/Pagination";
import { useToast } from "@/components/ui/Toast";
import { downloadCsv, errorMessage, opt } from "@/lib/api";
import { count } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";

import { OrderDrawer } from "./OrderDrawer";
import { OrdersTable } from "./OrdersTable";

const STATUS_OPTIONS = [
  { value: "NEW", label: "New" },
  { value: "PREPARING", label: "Preparing" },
  { value: "AWAITING_RIDER", label: "Awaiting rider" },
  { value: "PICKED_UP", label: "On delivery" },
  { value: "ACTIVE", label: "In progress" },
  { value: "DELIVERED", label: "Delivered" },
  { value: "CANCELLED", label: "Cancelled" },
];

const PAYMENT_OPTIONS = [
  { value: "COD", label: "Cash on delivery" },
  { value: "BKASH", label: "bKash" },
  { value: "CARD", label: "Card" },
  { value: "WALLET", label: "Wallet" },
];

const KEYS = ["q", "status", "payment_method", "date_from", "date_to", "awaiting_rider", "order"] as const;

export function OrdersPage() {
  const list = useListParams(KEYS);
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const [exporting, setExporting] = useState(false);
  const toast = useToast();

  const filters = {
    q: opt(v.q),
    status: opt(v.status),
    payment_method: opt(v.payment_method),
    date_from: opt(v.date_from),
    date_to: opt(v.date_to),
    awaiting_rider: v.awaiting_rider === "true" ? true : undefined,
  };
  const orders = useOrders({ ...filters, limit: list.limit, offset: list.offset });

  const exportCsv = async () => {
    setExporting(true);
    try {
      await downloadCsv("/admin/orders", filters, "orders.csv");
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Orders"
        subtitle={orders.data ? `${count(orders.data.meta.total)} orders` : " "}
        actions={
          <Button variant="brand-outline" size="sm" className="h-10" icon={<Upload className="size-4" />} onClick={exportCsv} loading={exporting}>
            Export
          </Button>
        }
      />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search Order Id, vendor, Customer..." />
            <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
              <Select
                aria-label="Status"
                placeholder="All Status"
                options={STATUS_OPTIONS}
                value={v.awaiting_rider === "true" ? "AWAITING_RIDER" : v.status}
                onChange={(e) =>
                  e.target.value === "AWAITING_RIDER"
                    ? list.set({ awaiting_rider: "true", status: "" })
                    : list.set({ status: e.target.value, awaiting_rider: "" })
                }
              />
              <Select
                aria-label="Payment method"
                placeholder="Payment Method"
                options={PAYMENT_OPTIONS}
                value={v.payment_method}
                onChange={(e) => list.set({ payment_method: e.target.value })}
              />
              <DateRangeFilter from={v.date_from} to={v.date_to} onChange={(date_from, date_to) => list.set({ date_from, date_to })} />
            </div>
          </>
        }
      >
        <OrdersTable
          rows={orders.data?.items}
          loading={orders.isPending}
          error={orders.error}
          onRetry={() => orders.refetch()}
          columns={["id", "customer", "vendor", "rider", "amount", "payment", "status", "date"]}
          onOpen={(o) => list.set({ order: o.id, page: String(list.page) })}
          activeId={v.order}
        />
        <Pagination meta={orders.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      <OrderDrawer orderId={v.order || null} onClose={() => list.set({ order: "", page: String(list.page) })} />
    </>
  );
}
