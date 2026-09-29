import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Plus, Upload } from "lucide-react";

import { useVendors, type AdminVendorRow } from "@/api/vendors";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Badge, TypeBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Identity, Rating } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { downloadCsv, errorMessage, opt } from "@/lib/api";
import { count, money } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";

export const BUSINESS_TYPE_OPTIONS = [
  { value: "RESTAURANT", label: "Food" },
  { value: "GROCERY", label: "Grocery" },
  { value: "PHARMACY", label: "Medicine" },
];

export const RATING_OPTIONS = [
  { value: "4.5", label: "4.5 and up" },
  { value: "4", label: "4 and up" },
  { value: "3", label: "3 and up" },
  { value: "2", label: "2 and up" },
];

const columns: Column<AdminVendorRow>[] = [
  {
    key: "name",
    header: "Vendor",
    cell: (v) => (
      <Identity
        src={v.logo_url}
        name={v.name}
        rounded="lg"
        sub={!v.is_verified ? <span className="text-red-500">Not approved</span> : v.status === "OPEN" ? "Open now" : "Closed"}
      />
    ),
  },
  { key: "type", header: "Type", cell: (v) => <TypeBadge type={v.business_type} /> },
  { key: "phone", header: "Phone Number", cell: (v) => v.phone ?? "—" },
  { key: "orders", header: "Order", cell: (v) => count(v.order_count) },
  { key: "revenue", header: "Revenue", cell: (v) => money(v.revenue) },
  { key: "rating", header: "Rating", cell: (v) => (v.rating_count ? <Rating value={v.rating_avg} /> : <span className="text-xs text-gray-400">No reviews</span>) },
  { key: "products", header: "Product", cell: (v) => <span className="text-gray-600">{count(v.product_count)}</span> },
];

export function VendorsPage() {
  const navigate = useNavigate();
  const list = useListParams(["q", "business_type", "min_rating", "status"] as const, { status: "ACTIVE" });
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const [exporting, setExporting] = useState(false);
  const toast = useToast();
  const filters = { q: opt(v.q), business_type: opt(v.business_type), min_rating: opt(v.min_rating), status: v.status };
  const vendors = useVendors({ ...filters, limit: list.limit, offset: list.offset });
  const noun = v.status === "SUSPENDED" ? "unapproved" : v.status === "ALL" ? "" : "active";

  return (
    <>
      <PageHeader
        title={v.status === "SUSPENDED" ? "Unapproved Vendors" : v.status === "ALL" ? "All Vendors" : "Active Vendors"}
        subtitle={
          vendors.data
            ? `${count(vendors.data.meta.total)} ${noun ? `${noun} ` : ""}vendor${vendors.data.meta.total === 1 ? "" : "s"}`
            : " "
        }
        actions={
          <>
            <Button
              variant="brand-outline"
              size="sm"
              className="h-10"
              icon={<Upload className="size-4" />}
              loading={exporting}
              onClick={async () => {
                setExporting(true);
                try {
                  await downloadCsv("/admin/vendors", filters, "vendors.csv");
                } catch (e) {
                  toast(errorMessage(e), "error");
                } finally {
                  setExporting(false);
                }
              }}
            >
              Export
            </Button>
            <Link to="/vendors/new">
              <Button size="sm" className="h-10 rounded-full px-4" icon={<Plus className="size-4" />}>
                Add Vendor
              </Button>
            </Link>
          </>
        }
      />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search vendor or phone..." />
            <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
              <Select
                aria-label="Category"
                placeholder="Category"
                options={BUSINESS_TYPE_OPTIONS}
                value={v.business_type}
                onChange={(e) => list.set({ business_type: e.target.value })}
              />
              <Select
                aria-label="Rating"
                placeholder="Rating"
                options={RATING_OPTIONS}
                value={v.min_rating}
                onChange={(e) => list.set({ min_rating: e.target.value })}
              />
              <Select
                aria-label="Status"
                options={[
                  { value: "ACTIVE", label: "Active" },
                  { value: "SUSPENDED", label: "Not approved" },
                  { value: "ALL", label: "All" },
                ]}
                value={v.status}
                onChange={(e) => list.set({ status: e.target.value })}
              />
            </div>
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={vendors.data?.items}
          rowKey={(r) => r.id}
          loading={vendors.isPending}
          error={vendors.error}
          onRetry={() => vendors.refetch()}
          onRowClick={(r) => navigate(`/vendors/${r.id}`)}
          empty={
            <>
              No vendors match.{" "}
              {v.status === "ACTIVE" && <Badge tone="gray">Unapproved stores are under Vendor → Application</Badge>}
            </>
          }
        />
        <Pagination meta={vendors.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
    </>
  );
}
