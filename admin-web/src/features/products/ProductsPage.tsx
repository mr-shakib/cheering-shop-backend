import { Star } from "lucide-react";

import { useProducts, type AdminProductRow } from "@/api/catalog";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { StatusBadge, TypeBadge } from "@/components/ui/Badge";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { opt } from "@/lib/api";
import { count, money, pct } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";
import { productStatus } from "@/lib/vocab";

import { BUSINESS_TYPE_OPTIONS } from "../vendors/VendorsPage";
import { ProductDrawer } from "./ProductDrawer";

export const PRODUCT_STATUS_OPTIONS = [
  { value: "ACTIVE", label: "Active" },
  { value: "HIDDEN", label: "Hidden" },
  { value: "UNAVAILABLE", label: "Sold out" },
];

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
  { key: "store", header: "Store", cell: (p) => p.restaurant_name },
  { key: "type", header: "Type", cell: (p) => <TypeBadge type={p.business_type} /> },
  { key: "category", header: "Category", cell: (p) => <span className="text-gray-600">{p.platform_category?.name ?? p.section_name}</span> },
  { key: "price", header: "Price", cell: (p) => money(p.base_price) },
  { key: "commission", header: "Commission", cell: (p) => <span className="text-gray-600">{pct(p.commission.rate)}</span> },
  { key: "status", header: "Status", cell: (p) => <StatusBadge {...productStatus(p.status)} /> },
];

export function ProductsPage() {
  const list = useListParams(["q", "business_type", "status", "featured", "product"] as const);
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const products = useProducts({
    q: opt(v.q),
    business_type: opt(v.business_type),
    status: opt(v.status),
    featured: opt(v.featured),
    limit: list.limit,
    offset: list.offset,
  });

  return (
    <>
      <PageHeader title="Product List" subtitle={products.data ? `Total ${count(products.data.meta.total)} Product` : " "} />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search product or store..." />
            <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
              <Select
                aria-label="Type"
                placeholder="All Type"
                options={BUSINESS_TYPE_OPTIONS}
                value={v.business_type}
                onChange={(e) => list.set({ business_type: e.target.value })}
              />
              <Select
                aria-label="Featured"
                placeholder="Featured & not"
                options={[
                  { value: "true", label: "Featured" },
                  { value: "false", label: "Not featured" },
                ]}
                value={v.featured}
                onChange={(e) => list.set({ featured: e.target.value })}
              />
              <Select
                aria-label="Status"
                placeholder="All Status"
                options={PRODUCT_STATUS_OPTIONS}
                value={v.status}
                onChange={(e) => list.set({ status: e.target.value })}
              />
            </div>
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={products.data?.items}
          rowKey={(p) => p.id}
          loading={products.isPending}
          error={products.error}
          onRetry={() => products.refetch()}
          onRowClick={(p) => list.set({ product: p.id, page: String(list.page) })}
          isRowActive={(p) => p.id === v.product}
          empty="No products match."
        />
        <Pagination meta={products.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      <ProductDrawer productId={v.product || null} onClose={() => list.set({ product: "", page: String(list.page) })} />
    </>
  );
}
