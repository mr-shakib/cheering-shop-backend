import { useState } from "react";
import { useNavigate } from "react-router";
import { Upload } from "lucide-react";

import { useCustomers, type AdminCustomerRow } from "@/api/customers";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { downloadCsv, errorMessage, opt } from "@/lib/api";
import { count, dateOnly, money } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";

const columns: Column<AdminCustomerRow>[] = [
  { key: "name", header: "Customer", cell: (c) => <Identity src={c.avatar_url} name={c.full_name} sub={c.email} /> },
  { key: "phone", header: "Phone Number", cell: (c) => c.phone ?? "—" },
  { key: "orders", header: "Order", cell: (c) => count(c.order_count) },
  { key: "spent", header: "Spent", cell: (c) => money(c.total_spent) },
  {
    key: "status",
    header: "Status",
    cell: (c) => <StatusBadge label={c.is_active ? "Active" : "Blocked"} tone={c.is_active ? "green" : "red"} dot={false} />,
  },
  { key: "joined", header: "Joined", cell: (c) => <span className="text-gray-600">{dateOnly(c.created_at)}</span> },
];

export function CustomersPage() {
  const navigate = useNavigate();
  const list = useListParams(["q", "status"] as const);
  const [search, setSearch] = useSearchParam(list.values.q, (q) => list.set({ q }));
  const [exporting, setExporting] = useState(false);
  const toast = useToast();
  const filters = { q: opt(list.values.q), status: opt(list.values.status) };
  const customers = useCustomers({ ...filters, limit: list.limit, offset: list.offset });

  return (
    <>
      <PageHeader
        title="Customers"
        subtitle={customers.data ? `${count(customers.data.meta.total)} customers` : " "}
        actions={
          <Button
            variant="brand-outline"
            size="sm"
            className="h-10"
            icon={<Upload className="size-4" />}
            loading={exporting}
            onClick={async () => {
              setExporting(true);
              try {
                await downloadCsv("/admin/customers", filters, "customers.csv");
              } catch (e) {
                toast(errorMessage(e), "error");
              } finally {
                setExporting(false);
              }
            }}
          >
            Export
          </Button>
        }
      />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search name, phone, email" />
            <Select
              className="sm:ml-auto"
              aria-label="Status"
              placeholder="All Status"
              options={[
                { value: "ACTIVE", label: "Active" },
                { value: "BLOCKED", label: "Blocked" },
              ]}
              value={list.values.status}
              onChange={(e) => list.set({ status: e.target.value })}
            />
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={customers.data?.items}
          rowKey={(c) => c.id}
          loading={customers.isPending}
          error={customers.error}
          onRetry={() => customers.refetch()}
          onRowClick={(c) => navigate(`/customers/${c.id}`)}
          empty="No customers match."
        />
        <Pagination meta={customers.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
    </>
  );
}
