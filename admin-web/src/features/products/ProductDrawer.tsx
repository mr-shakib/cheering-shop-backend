import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { CheckCircle2, EyeOff, Eye, Star, Trash2 } from "lucide-react";

import {
  useDeleteProduct,
  useProduct,
  useUpdateProduct,
  type AddOn,
  type AdminProductDetail,
  type Variant,
} from "@/api/catalog";
import { loadCategoryOptions } from "@/api/pickers";
import { Badge, StatusBadge, TypeBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Field, Input, TextArea } from "@/components/ui/Field";
import { FileDrop, Picker } from "@/components/ui/Inputs";
import { Drawer } from "@/components/ui/Overlay";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { ACCEPT } from "@/lib/upload";
import { productStatus } from "@/lib/vocab";

import { AddOnsEditor, VariantsEditor, cleanOptions, percentFromRate, rateFromPercent } from "./ProductEditors";

const SOURCE_LABEL = { PRODUCT: "this product's own rate", CATEGORY: "the category's rate", RESTAURANT: "the vendor's rate" };

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-6 py-1.5 text-sm">
      <span className="shrink-0 text-gray-500">{label}</span>
      <span className="text-right text-gray-900">{children}</span>
    </div>
  );
}

interface Draft {
  name: string;
  description: string;
  image_url: string | null;
  base_price: string;
  commission: string;
  platform_category: { id: string; name: string } | null;
  variants: Variant[];
  add_ons: AddOn[];
}

function draftOf(p: AdminProductDetail): Draft {
  return {
    name: p.name,
    description: p.description ?? "",
    image_url: p.image_url,
    base_price: String(p.base_price),
    commission: percentFromRate(p.commission.product_rate),
    platform_category: p.platform_category ? { id: p.platform_category.id, name: p.platform_category.name } : null,
    variants: p.variants,
    add_ons: p.add_ons,
  };
}

function ProductView({ p }: { p: AdminProductDetail }) {
  return (
    <>
      {p.image_url && <img src={p.image_url} alt="" className="aspect-[2/1] w-full rounded-lg object-cover" />}
      <div className="mt-3 divide-y divide-line">
        <Row label="Name">{p.name}</Row>
        <Row label="Description">{p.description || <span className="text-gray-400">None</span>}</Row>
        <Row label="Menu section">{p.section_name}</Row>
        {p.prep_time_mins != null && <Row label="Prep time">{p.prep_time_mins} min</Row>}
        {p.is_veg && <Row label="Diet">Vegetarian</Row>}
      </div>
    </>
  );
}

export function ProductDrawer({ productId, onClose }: { productId: string | null; onClose: () => void }) {
  const product = useProduct(productId);
  const update = useUpdateProduct();
  const remove = useDeleteProduct();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [formError, setFormError] = useState<unknown>(null);
  const p = product.data;

  useEffect(() => {
    setEditing(false);
    setFormError(null);
  }, [productId]);

  useEffect(() => {
    if (p && !editing) setDraft(draftOf(p));
  }, [p, editing]);

  const set = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  const save = async () => {
    if (!p || !draft) return;
    setFormError(null);
    try {
      const price = Number(draft.base_price);
      if (!draft.name.trim()) throw new Error("The product needs a name.");
      if (!Number.isFinite(price) || price < 0) throw new Error("Enter a valid price.");
      await update.mutateAsync({
        id: p.id,
        body: {
          name: draft.name.trim(),
          description: draft.description.trim() || null,
          image_url: draft.image_url,
          base_price: price,
          commission_rate: rateFromPercent(draft.commission),
          ...(draft.platform_category && draft.platform_category.id !== p.platform_category?.id
            ? { platform_category_id: draft.platform_category.id }
            : {}),
          variants: cleanOptions(draft.variants, "variant"),
          add_ons: cleanOptions(draft.add_ons, "add-on"),
        },
      });
      toast("Product saved");
      setEditing(false);
    } catch (e) {
      setFormError(e);
    }
  };

  const flag = (body: { is_hidden?: boolean; is_featured?: boolean }, message: string) =>
    p &&
    update.mutate(
      { id: p.id, body },
      { onSuccess: () => toast(message), onError: (e) => toast(errorMessage(e), "error") },
    );

  const footer = p && (
    editing ? (
      <div className="flex gap-3">
        <Button variant="outline" onClick={() => setEditing(false)} disabled={update.isPending}>
          Discard
        </Button>
        <Button icon={<CheckCircle2 className="size-4" />} onClick={save} loading={update.isPending} className="flex-1 sm:flex-none sm:px-8">
          Save Changes
        </Button>
      </div>
    ) : (
      <div className="grid grid-cols-3 gap-3">
        <Button
          variant="outline"
          icon={p.is_hidden ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
          onClick={() =>
            p.is_hidden
              ? flag({ is_hidden: false }, "Product is visible to customers again")
              : confirm({
                  title: `Hide ${p.name}?`,
                  description:
                    "It leaves the customer app — menu, search, categories and carts. The vendor still sees it, marked hidden, and cannot undo this.",
                  confirmLabel: "Hide product",
                  tone: "danger",
                  onConfirm: () => update.mutateAsync({ id: p.id, body: { is_hidden: true } }).then(() => toast("Product hidden")),
                })
          }
          loading={update.isPending && update.variables?.body.is_hidden !== undefined}
        >
          {p.is_hidden ? "Unhide" : "Hide Product"}
        </Button>
        <Button
          variant={p.is_featured ? "brand-outline" : "primary"}
          icon={<Star className={p.is_featured ? "size-4 fill-brand-500" : "size-4"} />}
          onClick={() => flag({ is_featured: !p.is_featured }, p.is_featured ? "No longer featured" : "Product featured")}
          loading={update.isPending && update.variables?.body.is_featured !== undefined}
        >
          {p.is_featured ? "Featured" : "Feature"}
        </Button>
        <Button
          variant="danger-soft"
          icon={<Trash2 className="size-4" />}
          onClick={() =>
            confirm({
              title: `Delete ${p.name}?`,
              description: "It is removed from every menu. Past orders keep it. To take it down without deleting, hide it instead.",
              confirmLabel: "Delete product",
              tone: "danger",
              onConfirm: () =>
                remove.mutateAsync(p.id).then(() => {
                  toast("Product deleted");
                  onClose();
                }),
            })
          }
        >
          Delete
        </Button>
      </div>
    )
  );

  return (
    <Drawer open={!!productId} onClose={onClose} eyebrow="Product" title={p?.name ?? "Product"} footer={footer}>
      {product.isPending ? (
        <PageSpinner />
      ) : product.isError ? (
        <ErrorState error={product.error} onRetry={() => product.refetch()} />
      ) : p && draft ? (
        <>
          <Panel>
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                {p.business_type && <TypeBadge type={p.business_type} />}
                {p.is_featured && (
                  <Badge tone="pink" icon={<Star className="size-3 fill-brand-500" />}>
                    Featured
                  </Badge>
                )}
              </div>
              <StatusBadge {...productStatus(p.status)} />
            </div>
            <Link to={`/vendors/${p.restaurant_id}`} className="mt-2 block text-sm text-gray-800 hover:text-brand-500">
              {p.restaurant_name}
            </Link>
            {editing ? (
              <Field label="Category" className="mt-3">
                {() => (
                  <Picker
                    value={draft.platform_category?.id ?? null}
                    valueLabel={draft.platform_category?.name}
                    onChange={(o) => o && set({ platform_category: { id: o.value, name: o.label } })}
                    load={loadCategoryOptions}
                    placeholder="Choose a category"
                    searchPlaceholder="Search categories…"
                  />
                )}
              </Field>
            ) : (
              <p className="mt-1 text-xs text-gray-500">Category: {p.platform_category?.name ?? "None"}</p>
            )}
          </Panel>

          <Panel
            title="Basic"
            actions={
              editing ? (
                <Button size="xs" className="rounded-full" onClick={() => setEditing(false)}>
                  Done Editing
                </Button>
              ) : (
                <Button size="xs" variant="outline" onClick={() => setEditing(true)}>
                  Edit
                </Button>
              )
            }
          >
            {editing ? (
              <div className="space-y-3">
                <FileDrop value={draft.image_url} onChange={(url) => set({ image_url: url })} accept={ACCEPT.image} label="Add product image" />
                <Field label="Name">{(id) => <Input id={id} value={draft.name} onChange={(e) => set({ name: e.target.value })} maxLength={180} />}</Field>
                <Field label="Description">
                  {(id) => (
                    <TextArea id={id} value={draft.description} onChange={(e) => set({ description: e.target.value })} maxLength={2000} className="min-h-20" />
                  )}
                </Field>
              </div>
            ) : (
              <ProductView p={p} />
            )}
          </Panel>

          <Panel title="Pricing">
            {editing ? (
              <div className="space-y-3">
                <Field label="Price (৳)" hint={draft.variants.length ? "With variants this is only a “from” price; the variant price is charged." : undefined}>
                  {(id) => <Input id={id} type="number" min={0} value={draft.base_price} onChange={(e) => set({ base_price: e.target.value })} />}
                </Field>
                <Field
                  label="Commission (%)"
                  hint={`Leave empty to use ${p.commission.category_rate != null ? `the category's ${pct(p.commission.category_rate)}` : `the vendor's ${pct(p.commission.restaurant_rate)}`}.`}
                >
                  {(id) => (
                    <Input
                      id={id}
                      type="number"
                      min={0}
                      max={100}
                      step="0.5"
                      value={draft.commission}
                      onChange={(e) => set({ commission: e.target.value })}
                      placeholder={pct(p.commission.category_rate ?? p.commission.restaurant_rate).replace("%", "")}
                    />
                  )}
                </Field>
              </div>
            ) : (
              <div className="divide-y divide-line">
                <Row label="Price">{money(p.base_price)}</Row>
                <Row label="Commission">
                  {pct(p.commission.rate)}
                  <span className="block text-xs text-gray-500">{SOURCE_LABEL[p.commission.source]}</span>
                </Row>
                <Row label="Net amount">{money(p.net_amount)}</Row>
              </div>
            )}
          </Panel>

          <Panel title="Variants">
            {editing ? (
              <VariantsEditor value={draft.variants} onChange={(variants) => set({ variants })} />
            ) : p.variants.length ? (
              <div className="flex flex-wrap gap-2">
                {p.variants.map((v) => (
                  <span key={v.id} className="rounded-full border border-gray-200 px-3 py-1 text-xs text-gray-800">
                    {v.name} · {money(v.price)}
                    {!v.is_available && <span className="text-gray-400"> (sold out)</span>}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">None</p>
            )}
          </Panel>

          <Panel title="Addons">
            {editing ? (
              <AddOnsEditor value={draft.add_ons} onChange={(add_ons) => set({ add_ons })} />
            ) : p.add_ons.length ? (
              <div className="divide-y divide-line">
                {p.add_ons.map((a) => (
                  <Row key={a.id} label={a.max_quantity > 1 ? `${a.name} (up to ${a.max_quantity})` : a.name}>
                    {money(a.price)}
                  </Row>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">None</p>
            )}
          </Panel>
          {editing && <InlineError error={formError} />}
        </>
      ) : null}
      {dialog}
    </Drawer>
  );
}
