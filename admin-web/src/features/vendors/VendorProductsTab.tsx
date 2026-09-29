import { useState } from "react";
import { Plus, Star } from "lucide-react";

import { useProducts, type AdminProductRow } from "@/api/catalog";
import type { AdminVendorDetail } from "@/api/vendors";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { opt } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { PAGE_SIZE, useDebounced } from "@/lib/hooks";
import { productStatus } from "@/lib/vocab";

import { ProductCreateDrawer } from "../products/ProductCreateDrawer";
import { ProductDrawer } from "../products/ProductDrawer";
import { PRODUCT_STATUS_OPTIONS } from "../products/ProductsPage";

const columns: Column<AdminProductRow>[] = [
  {
    key: "product",
    header: "Product",
    cell: (p) => (
      <span className="flex items-center gap-1.5">
        <Identity src={p.image_url} name={p.name} rounded="lg" />
        {p.is_featured && <Star className="size-3.5 shrink-0 fill-brand-500 text-brand-500" aria-label="Featured" />}
      </span>
    ),
  },
  { key: "category", header: "Category", cell: (p) => p.platform_category?.name ?? p.section_name },
  { key: "price", header: "Price", cell: (p) => money(p.base_price) },
  { key: "commission", header: "Commission", cell: (p) => <span className="text-gray-600">{pct(p.commission.rate)}</span> },
  { key: "status", header: "Status", cell: (p) => <StatusBadge {...productStatus(p.status)} dot={false} /> },
];

export function VendorProductsTab({ vendor }: { vendor: AdminVendorDetail }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const debounced = useDebounced(q, 300);
  const products = useProducts({
    restaurant_id: vendor.id,
    q: opt(debounced),
    status: opt(status),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  return (
    <div className="rounded-xl border border-line p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchInput
          value={q}
          onChange={(v) => {
            setQ(v);
            setPage(1);
          }}
          placeholder="Search product..."
        />
        <Select
          className="sm:ml-auto"
          aria-label="Status"
          placeholder="All Status"
          options={PRODUCT_STATUS_OPTIONS}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        />
        <Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
          Add Product
        </Button>
      </div>
      <DataTable
        columns={columns}
        rows={products.data?.items}
        rowKey={(p) => p.id}
        loading={products.isPending}
        error={products.error}
        onRetry={() => products.refetch()}
        onRowClick={(p) => setOpen(p.id)}
        isRowActive={(p) => p.id === open}
        empty="This vendor has no products yet."
      />
      <Pagination meta={products.data?.meta} onPage={setPage} />
      <p className="mt-3 text-xs text-gray-400">Stock is not tracked yet; a sold-out product shows as “Sold out”.</p>
      <ProductDrawer productId={open} onClose={() => setOpen(null)} />
      <ProductCreateDrawer vendor={vendor} open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}
