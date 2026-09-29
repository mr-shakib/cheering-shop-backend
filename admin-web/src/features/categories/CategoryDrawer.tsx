/* Create category / Edit category. A browse category holds products through
 * the vendors' menu sections, so "adding" a product moves it into its
 * restaurant's section for this category, and a product can only leave by
 * moving to another category (docs/ADMIN-API.md §6). */
import { useEffect, useState } from "react";
import { ArrowRightLeft, CheckCircle2, Combine, Plus, X } from "lucide-react";

import {
  useCreateCategory,
  useMergeCategory,
  useProducts,
  useUpdateCategory,
  useUpdateProduct,
  type AdminCategory,
} from "@/api/catalog";
import { loadCategoryOptions, loadProductOptions } from "@/api/pickers";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Avatar } from "@/components/ui/Display";
import { InlineError, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Select, Switch } from "@/components/ui/Field";
import { FileDrop, Picker, type PickerOption } from "@/components/ui/Inputs";
import { Drawer } from "@/components/ui/Overlay";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api";
import { ACCEPT } from "@/lib/upload";

import { percentFromRate, rateFromPercent } from "../products/ProductEditors";

interface Draft {
  name: string;
  image_url: string | null;
  commission: string;
  kind: "RESTAURANT" | "STORE";
  sort_order: string;
  aliases: string;
  is_active: boolean;
}

const draftOf = (c: AdminCategory | null, kind: "RESTAURANT" | "STORE"): Draft => ({
  name: c?.name ?? "",
  image_url: c?.image_url ?? null,
  commission: percentFromRate(c?.commission_rate),
  kind: c?.kind ?? kind,
  sort_order: c?.sort_order != null ? String(c.sort_order) : "",
  aliases: c?.aliases.join(", ") ?? "",
  is_active: c?.is_active ?? true,
});

/** Products in the category, each movable to another one. */
function ProductList({ category }: { category: AdminCategory }) {
  const products = useProducts({ category_id: category.id, limit: 50 });
  const update = useUpdateProduct();
  const toast = useToast();
  const [adding, setAdding] = useState(false);

  const move = (product: { id: string; name: string }, to: PickerOption) =>
    update.mutate(
      { id: product.id, body: { platform_category_id: to.value } },
      {
        onSuccess: () => toast(`${product.name} moved to ${to.label}`),
        onError: (e) => toast(errorMessage(e), "error"),
      },
    );

  const rows = products.data?.items ?? [];
  return (
    <Panel
      title={`Product List (${products.data?.meta.total ?? category.product_count})`}
      actions={
        <button type="button" onClick={() => setAdding((a) => !a)} className="inline-flex items-center gap-1 text-sm text-gray-700 hover:text-brand-500">
          {adding ? <X className="size-4" /> : <Plus className="size-4" />} {adding ? "Close" : "Add product"}
        </button>
      }
    >
      {adding && (
        <div className="mb-3">
          <Picker
            value={null}
            onChange={(o) => {
              if (!o) return;
              move({ id: o.value, name: o.label }, { value: category.id, label: category.name });
              setAdding(false);
            }}
            load={(q) => loadProductOptions(q)}
            placeholder="Search a product to move here"
            searchPlaceholder="Search Product..."
          />
          <p className="mt-1.5 text-xs text-gray-500">It moves into its restaurant's section for this category; one is created if needed.</p>
        </div>
      )}
      {products.isPending ? (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-500">No products are listed under this category yet.</p>
      ) : (
        <ul className="-mx-2 divide-y divide-line">
          {rows.map((p) => (
            <li key={p.id} className="group flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-gray-50">
              <Avatar src={p.image_url} name={p.name} size={32} rounded="lg" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-gray-900">{p.name}</span>
                <span className="block truncate text-xs text-gray-500">{p.restaurant_name}</span>
              </span>
              <Picker
                className="w-auto"
                buttonClassName="h-8 w-auto gap-1.5 bg-transparent px-2 text-xs text-gray-600 hover:bg-gray-100"
                value={category.id}
                valueLabel="Move"
                onChange={(o) => o && o.value !== category.id && move(p, o)}
                load={loadCategoryOptions}
                searchPlaceholder="Move to…"
              />
            </li>
          ))}
        </ul>
      )}
      {products.data?.meta.has_more && <p className="mt-2 text-xs text-gray-500">Showing the first 50. Use the Product list to see the rest.</p>}
    </Panel>
  );
}

function MergePanel({ category, onMerged }: { category: AdminCategory; onMerged: () => void }) {
  const merge = useMergeCategory();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [target, setTarget] = useState<PickerOption | null>(null);
  return (
    <Panel title="Merge">
      <p className="mb-3 text-sm text-gray-600">
        Fold “{category.name}” into another category: its sections move over and its name becomes an alias there, so the spelling cannot come back.
      </p>
      <div className="flex gap-2">
        <Picker
          className="flex-1"
          value={target?.value ?? null}
          valueLabel={target?.label}
          onChange={setTarget}
          load={async (q) => (await loadCategoryOptions(q)).filter((o) => o.value !== category.id)}
          placeholder="Choose the category that survives"
        />
        <Button
          variant="outline"
          size="sm"
          className="h-10"
          icon={<Combine className="size-4" />}
          disabled={!target}
          onClick={() =>
            target &&
            confirm({
              title: `Merge ${category.name} into ${target.label}?`,
              description: `Every menu section under ${category.name} moves to ${target.label}, and ${category.name} is deleted. This cannot be undone.`,
              confirmLabel: "Merge",
              tone: "danger",
              onConfirm: () =>
                merge.mutateAsync({ id: category.id, intoId: target.value }).then(() => {
                  toast(`${category.name} merged into ${target.label}`);
                  onMerged();
                }),
            })
          }
        >
          Merge
        </Button>
      </div>
      {dialog}
    </Panel>
  );
}

export function CategoryDrawer({
  open,
  category,
  defaultKind,
  onClose,
}: {
  open: boolean;
  category: AdminCategory | null;
  defaultKind: "RESTAURANT" | "STORE";
  onClose: () => void;
}) {
  const create = useCreateCategory();
  const update = useUpdateCategory();
  const updateProduct = useUpdateProduct();
  const toast = useToast();
  const [draft, setDraft] = useState<Draft>(() => draftOf(category, defaultKind));
  const [initialProducts, setInitialProducts] = useState<PickerOption[]>([]);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (open) {
      setDraft(draftOf(category, defaultKind));
      setInitialProducts([]);
      setError(null);
    }
  }, [open, category, defaultKind]);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const busy = create.isPending || update.isPending || updateProduct.isPending;

  const submit = async () => {
    setError(null);
    try {
      if (!draft.name.trim()) throw new Error("The category needs a name.");
      const sort = draft.sort_order.trim() ? Number(draft.sort_order) : null;
      if (sort !== null && (!Number.isInteger(sort) || sort < 0)) throw new Error("The pinned position must be a whole number.");
      const body = {
        name: draft.name.trim(),
        image_url: draft.image_url,
        commission_rate: rateFromPercent(draft.commission),
        kind: draft.kind,
        sort_order: sort,
        aliases: draft.aliases.split(",").map((a) => a.trim()).filter(Boolean),
        is_active: draft.is_active,
      };
      if (category) {
        await update.mutateAsync({ id: category.id, body });
        toast("Category saved");
      } else {
        const created = await create.mutateAsync(body);
        for (const p of initialProducts) {
          await updateProduct.mutateAsync({ id: p.value, body: { platform_category_id: created.id } });
        }
        toast(`${created.name} created${initialProducts.length ? ` with ${initialProducts.length} product${initialProducts.length === 1 ? "" : "s"}` : ""}`);
      }
      onClose();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={category ? "Edit category" : "Create category"}
      footer={
        <div className="grid grid-cols-2 gap-3">
          <Button variant="outline" onClick={() => (category ? setDraft(draftOf(category, defaultKind)) : onClose())} disabled={busy}>
            {category ? "Reset" : "Cancel"}
          </Button>
          <Button onClick={submit} loading={busy} icon={<CheckCircle2 className="size-4" />}>
            {category ? "Save Changes" : "Create category"}
          </Button>
        </div>
      }
    >
      <Panel>
        <div className="space-y-4">
          <Field label="Category Name">{(id) => <Input id={id} value={draft.name} onChange={(e) => set({ name: e.target.value })} maxLength={80} autoFocus={!category} />}</Field>
          <Field label="Category Image">{() => <FileDrop value={draft.image_url} onChange={(url) => set({ image_url: url })} accept={ACCEPT.image} label="Add Category Image" />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Commission (%)" hint="Empty: each vendor's own rate">
              {(id) => <Input id={id} type="number" min={0} max={100} step="0.5" value={draft.commission} onChange={(e) => set({ commission: e.target.value })} />}
            </Field>
            <Field label="Tab">
              {(id) => (
                <Select
                  id={id}
                  look="filled"
                  options={[
                    { value: "RESTAURANT", label: "Restaurant" },
                    { value: "STORE", label: "Store" },
                  ]}
                  value={draft.kind}
                  onChange={(e) => set({ kind: e.target.value as Draft["kind"] })}
                />
              )}
            </Field>
            <Field label="Pinned position" hint="Empty: ordered by popularity">
              {(id) => <Input id={id} type="number" min={0} max={9999} value={draft.sort_order} onChange={(e) => set({ sort_order: e.target.value })} />}
            </Field>
            <Field label="Aliases" hint="Other spellings, comma separated">
              {(id) => <Input id={id} value={draft.aliases} onChange={(e) => set({ aliases: e.target.value })} placeholder="burgers, hamburger" />}
            </Field>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-lg bg-page px-3 py-2.5">
            <span className="text-sm text-gray-700">
              Shown to customers
              {category?.is_pending && <span className="block text-xs text-orange-600">A vendor created this; saving records your decision.</span>}
            </span>
            <Switch checked={draft.is_active} onChange={(v) => set({ is_active: v })} label="Shown to customers" />
          </div>
        </div>
      </Panel>

      {category ? (
        <>
          <ProductList category={category} />
          <MergePanel category={category} onMerged={onClose} />
        </>
      ) : (
        <Panel title="Product List">
          <Picker
            value={null}
            onChange={(o) => o && !initialProducts.some((p) => p.value === o.value) && setInitialProducts((all) => [...all, o])}
            load={(q) => loadProductOptions(q)}
            placeholder="Add products to this category"
            searchPlaceholder="Search Product..."
          />
          {initialProducts.length > 0 && (
            <ul className="mt-3 divide-y divide-line">
              {initialProducts.map((p) => (
                <li key={p.value} className="flex items-center gap-3 py-2">
                  {p.icon}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-gray-900">{p.label}</span>
                    <span className="block truncate text-xs text-gray-500">{p.sub}</span>
                  </span>
                  <button
                    type="button"
                    aria-label={`Leave ${p.label} where it is`}
                    onClick={() => setInitialProducts((all) => all.filter((x) => x.value !== p.value))}
                    className="rounded p-1 text-gray-400 hover:text-gray-700"
                  >
                    <X className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 flex items-center gap-1.5 text-xs text-gray-500">
            <ArrowRightLeft className="size-3.5" /> Each product moves out of the category it is in now.
          </p>
        </Panel>
      )}
      <InlineError error={error} />
    </Drawer>
  );
}
