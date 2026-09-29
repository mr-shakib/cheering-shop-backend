import { useState } from "react";
import { Check, EyeOff, Pencil, Pin, Plus, Trash2 } from "lucide-react";

import { useCategories, useDeleteCategory, useUpdateCategory, type AdminCategory } from "@/api/catalog";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, opt } from "@/lib/api";
import { count, pct } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";

import { CategoryDrawer } from "./CategoryDrawer";

export function CategoriesPage() {
  const list = useListParams(["kind", "q", "sort", "pending"] as const, { kind: "RESTAURANT" });
  const { values: v } = list;
  const kind = v.kind === "STORE" ? "STORE" : "RESTAURANT";
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const categories = useCategories({
    kind,
    q: opt(v.q),
    sort: opt(v.sort),
    pending: v.pending === "true" ? true : undefined,
    limit: list.limit,
    offset: list.offset,
  });
  const queue = useCategories({ pending: true, limit: 1 });
  const update = useUpdateCategory();
  const remove = useDeleteCategory();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [editing, setEditing] = useState<AdminCategory | "new" | null>(null);
  const waiting = queue.data?.meta.total ?? 0;

  const decide = (c: AdminCategory, show: boolean) =>
    update.mutate(
      { id: c.id, body: { is_active: show } },
      { onSuccess: () => toast(show ? `${c.name} is live` : `${c.name} kept hidden`), onError: (e) => toast(errorMessage(e), "error") },
    );

  const columns: Column<AdminCategory>[] = [
    {
      key: "name",
      header: "Category Name",
      cell: (c) => <Identity src={c.image_url} name={c.name} rounded="lg" sub={c.aliases.length ? `Also: ${c.aliases.slice(0, 3).join(", ")}` : undefined} />,
    },
    { key: "restaurants", header: "Restaurants", cell: (c) => count(c.restaurant_count) },
    { key: "products", header: "Total Product", cell: (c) => count(c.product_count) },
    { key: "commission", header: "Commission", cell: (c) => <span className="text-gray-600">{c.commission_rate != null ? pct(c.commission_rate) : "Vendor's"}</span> },
    {
      key: "status",
      header: "Status",
      cell: (c) => (
        <span className="flex items-center gap-1.5">
          {c.is_pending ? (
            <StatusBadge label="Needs review" tone="orange" dot={false} />
          ) : (
            <StatusBadge label={c.is_active ? "Active" : "Inactive"} tone={c.is_active ? "green" : "red"} dot={false} />
          )}
          {c.sort_order != null && (
            <Badge tone="gray" icon={<Pin className="size-3" />}>
              {c.sort_order}
            </Badge>
          )}
        </span>
      ),
    },
    {
      key: "action",
      header: "Action",
      align: "right",
      cell: (c) => (
        <span className="inline-flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {c.is_pending && (
            <>
              <Button size="xs" variant="success-soft" icon={<Check className="size-3.5" />} onClick={() => decide(c, true)}>
                Approve
              </Button>
              <Button size="xs" variant="ghost" icon={<EyeOff className="size-3.5" />} onClick={() => decide(c, false)}>
                Keep hidden
              </Button>
            </>
          )}
          <IconButton label={`Edit ${c.name}`} onClick={() => setEditing(c)}>
            <Pencil className="size-[18px]" />
          </IconButton>
          <IconButton
            label={`Delete ${c.name}`}
            className="hover:bg-red-50 hover:text-red-600"
            onClick={() =>
              confirm({
                title: `Delete ${c.name}?`,
                description:
                  c.section_count > 0
                    ? `${c.section_count} menu section${c.section_count === 1 ? " is" : "s are"} filed under it, so it cannot be deleted. Hide it, or merge it into another category from the edit drawer.`
                    : "Nothing is filed under it, so it can be deleted.",
                confirmLabel: "Delete",
                tone: "danger",
                onConfirm: () => remove.mutateAsync(c.id).then(() => toast(`${c.name} deleted`)),
              })
            }
          >
            <Trash2 className="size-[18px]" />
          </IconButton>
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Category"
        subtitle={categories.data ? `${count(categories.data.meta.total)} ${kind === "STORE" ? "store" : "restaurant"} categories` : " "}
      />
      {waiting > 0 && v.pending !== "true" && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-900">
          <span>
            <strong>{waiting}</strong> categor{waiting === 1 ? "y was" : "ies were"} created by vendors and {waiting === 1 ? "is" : "are"} hidden from customers until you decide.
          </span>
          <Button size="sm" variant="outline" onClick={() => list.set({ pending: "true" })}>
            Review now
          </Button>
        </div>
      )}
      <ListCard>
        <Tabs
          className="mb-5"
          tabs={[
            { key: "RESTAURANT", label: "Restaurant" },
            { key: "STORE", label: "Store" },
          ]}
          active={kind}
          onChange={(k) => list.set({ kind: k })}
        />
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <SearchInput value={search} onChange={setSearch} placeholder="Search category..." />
          <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
            <Select
              aria-label="Show"
              options={[
                { value: "", label: "All categories" },
                { value: "true", label: `Needs review${waiting ? ` (${waiting})` : ""}` },
              ]}
              value={v.pending}
              onChange={(e) => list.set({ pending: e.target.value })}
            />
            <Select
              aria-label="Sort"
              options={[
                { value: "", label: "Customer order" },
                { value: "name", label: "A to Z" },
                { value: "-name", label: "Z to A" },
              ]}
              value={v.sort}
              onChange={(e) => list.set({ sort: e.target.value })}
            />
            <Button icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
              Add Category
            </Button>
          </div>
        </div>
        <DataTable
          columns={columns}
          rows={categories.data?.items}
          rowKey={(c) => c.id}
          loading={categories.isPending}
          error={categories.error}
          onRetry={() => categories.refetch()}
          onRowClick={(c) => setEditing(c)}
          empty={v.pending === "true" ? "Nothing is waiting for review." : "No categories match."}
        />
        <Pagination meta={categories.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      <CategoryDrawer
        open={editing !== null}
        category={editing === "new" ? null : editing}
        defaultKind={kind}
        onClose={() => setEditing(null)}
      />
      {dialog}
    </>
  );
}
