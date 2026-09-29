/* App banners: the images, GIFs and Lottie animations the apps show, by
 * placement (HOME is the top of the customer home screen). docs/ADMIN-API.md §14. */
import { useState } from "react";
import { format, parseISO } from "date-fns";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { useBanners, useCreateBanner, useDeleteBanner, useUpdateBanner, type Banner, type BannerWrite } from "@/api/content";
import { loadCategorySlugOptions, loadRestaurantOptions } from "@/api/pickers";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/Field";
import { FileDrop, Picker } from "@/components/ui/Inputs";
import { Modal } from "@/components/ui/Overlay";
import { Pagination } from "@/components/ui/Pagination";
import { useToast } from "@/components/ui/Toast";
import { count, dateTime, titleCase } from "@/lib/format";
import { useListParams } from "@/lib/hooks";
import { ACCEPT } from "@/lib/upload";
import { bannerStatus } from "@/lib/vocab";

import { BannerPreview, inferMediaType } from "./BannerPreview";

/** <input type="datetime-local"> speaks local wall-clock time; the API wants an instant. */
const toLocalInput = (iso: string | null) => (iso ? format(parseISO(iso), "yyyy-MM-dd'T'HH:mm") : "");
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : null);

function describeAction(b: Pick<Banner, "action_type" | "action_value">) {
  if (b.action_type === "NONE") return "No action";
  if (b.action_type === "URL") return b.action_value ?? "";
  return `${titleCase(b.action_type)}: ${b.action_value ?? ""}`;
}

function BannerDialog({ banner, onClose }: { banner: Banner | null; onClose: () => void }) {
  const create = useCreateBanner();
  const update = useUpdateBanner();
  const toast = useToast();
  const [f, setF] = useState({
    title: banner?.title ?? "",
    media_url: banner?.media_url ?? (null as string | null),
    media_type: banner?.media_type ?? ("" as "" | Banner["media_type"]),
    placement: banner?.placement ?? "HOME",
    action_type: banner?.action_type ?? ("NONE" as Banner["action_type"]),
    action_value: banner?.action_value ?? "",
    action_label: banner?.action_value ?? "",
    sort_order: String(banner?.sort_order ?? 0),
    is_active: banner?.is_active ?? true,
    starts_at: toLocalInput(banner?.starts_at ?? null),
    ends_at: toLocalInput(banner?.ends_at ?? null),
  });
  const [error, setError] = useState<unknown>(null);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));
  const type = f.media_type || inferMediaType(f.media_url);

  const save = async () => {
    setError(null);
    try {
      if (!f.title.trim()) throw new Error("Give the banner a title: it is also the app's accessibility text.");
      if (!f.media_url) throw new Error("Upload the banner image, GIF or Lottie file.");
      if (f.action_type !== "NONE" && !f.action_value.trim()) throw new Error("Choose what a tap opens.");
      if (!/^[A-Z][A-Z0-9_]{1,39}$/.test(f.placement)) throw new Error("Placement is an upper-case name like HOME or OFFERS.");
      const body: BannerWrite = {
        title: f.title.trim(),
        media_url: f.media_url,
        media_type: type,
        placement: f.placement,
        action_type: f.action_type,
        action_value: f.action_type === "NONE" ? null : f.action_value.trim(),
        sort_order: Number(f.sort_order) || 0,
        is_active: f.is_active,
        starts_at: fromLocalInput(f.starts_at),
        ends_at: fromLocalInput(f.ends_at),
      };
      if (banner) await update.mutateAsync({ id: banner.id, body });
      else await create.mutateAsync(body);
      toast(banner ? "Banner saved" : "Banner added");
      onClose();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={banner ? "Edit banner" : "Add banner"}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={create.isPending || update.isPending}>
            {banner ? "Save" : "Add banner"}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <Field label="Media" hint="PNG, JPG, WebP, GIF, or a Lottie .json">
            {() => (
              <FileDrop
                kind={type === "LOTTIE" ? "file" : "image"}
                value={f.media_url}
                onChange={(u) => setF((x) => ({ ...x, media_url: u, media_type: "" }))}
                accept={ACCEPT.banner}
                label="Upload banner"
              />
            )}
          </Field>
          {f.media_url && <BannerPreview url={f.media_url} type={type} className="aspect-[2/1] w-full rounded-lg border border-line" />}
          <Field label="Type">
            {(id) => (
              <Select
                id={id}
                look="filled"
                options={[
                  { value: "IMAGE", label: "Image" },
                  { value: "GIF", label: "GIF" },
                  { value: "LOTTIE", label: "Lottie animation" },
                ]}
                value={type}
                onChange={(e) => set("media_type", e.target.value as Banner["media_type"])}
              />
            )}
          </Field>
        </div>
        <div className="space-y-3">
          <Field label="Title">{(id) => <Input id={id} value={f.title} onChange={(e) => set("title", e.target.value)} maxLength={120} placeholder="Weekend 50% off" />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Placement">{(id) => <Input id={id} value={f.placement} onChange={(e) => set("placement", e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""))} />}</Field>
            <Field label="Order" hint="Lowest first">{(id) => <Input id={id} type="number" min={0} max={9999} value={f.sort_order} onChange={(e) => set("sort_order", e.target.value)} />}</Field>
          </div>
          <Field label="A tap opens">
            {(id) => (
              <Select
                id={id}
                look="filled"
                options={[
                  { value: "NONE", label: "Nothing" },
                  { value: "RESTAURANT", label: "A restaurant" },
                  { value: "CATEGORY", label: "A category" },
                  { value: "URL", label: "A web link" },
                ]}
                value={f.action_type}
                onChange={(e) => setF((x) => ({ ...x, action_type: e.target.value as Banner["action_type"], action_value: "", action_label: "" }))}
              />
            )}
          </Field>
          {f.action_type === "RESTAURANT" && (
            <Picker
              value={f.action_value || null}
              valueLabel={f.action_label}
              onChange={(o) => setF((x) => ({ ...x, action_value: o?.value ?? "", action_label: o?.label ?? "" }))}
              load={loadRestaurantOptions}
              placeholder="Choose a restaurant"
            />
          )}
          {f.action_type === "CATEGORY" && (
            <Picker
              value={f.action_value || null}
              valueLabel={f.action_label}
              onChange={(o) => setF((x) => ({ ...x, action_value: o?.value ?? "", action_label: o?.label ?? "" }))}
              load={loadCategorySlugOptions}
              placeholder="Choose a category"
            />
          )}
          {f.action_type === "URL" && <Input aria-label="Link" type="url" value={f.action_value} onChange={(e) => set("action_value", e.target.value)} placeholder="https://" />}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Show from" hint="Optional">
              {(id) => <Input id={id} type="datetime-local" value={f.starts_at} onChange={(e) => set("starts_at", e.target.value)} />}
            </Field>
            <Field label="Until" hint="Optional">
              {(id) => <Input id={id} type="datetime-local" value={f.ends_at} onChange={(e) => set("ends_at", e.target.value)} />}
            </Field>
          </div>
          <Checkbox checked={f.is_active} onChange={(v) => set("is_active", v)} label="Active" />
        </div>
      </div>
      <div className="mt-3">
        <InlineError error={error} />
      </div>
    </Modal>
  );
}

export function BannersPage() {
  const list = useListParams(["status", "placement"] as const, { status: "ALL" });
  const { values: v } = list;
  const banners = useBanners({ status: v.status, placement: v.placement || undefined, limit: 12, offset: (list.page - 1) * 12 });
  const remove = useDeleteBanner();
  const update = useUpdateBanner();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [editing, setEditing] = useState<Banner | "new" | null>(null);

  return (
    <>
      <PageHeader
        title="App Banners"
        subtitle={banners.data ? `${count(banners.data.meta.total)} banners` : " "}
        actions={
          <Button size="sm" className="h-10 rounded-full px-4" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
            Add Banner
          </Button>
        }
      />
      <ListCard
        toolbar={
          <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
            <Input
              aria-label="Placement"
              look="outline"
              value={v.placement}
              onChange={(e) => list.set({ placement: e.target.value.toUpperCase() })}
              placeholder="Any placement"
              className="w-44"
            />
            <Select
              aria-label="Status"
              options={[
                { value: "ALL", label: "All banners" },
                { value: "LIVE", label: "Live now" },
                { value: "SCHEDULED", label: "Scheduled" },
                { value: "EXPIRED", label: "Expired" },
                { value: "INACTIVE", label: "Inactive" },
              ]}
              value={v.status}
              onChange={(e) => list.set({ status: e.target.value })}
            />
          </div>
        }
      >
        {banners.isPending ? (
          <PageSpinner />
        ) : banners.isError ? (
          <ErrorState error={banners.error} onRetry={() => banners.refetch()} />
        ) : banners.data.items.length === 0 ? (
          <EmptyState>No banners yet. The apps show nothing in that slot until you add one.</EmptyState>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {banners.data.items.map((b) => (
              <div key={b.id} className="overflow-hidden rounded-xl border border-line bg-white">
                <BannerPreview url={b.media_url} type={b.media_type} className="aspect-[2/1] w-full" />
                <div className="space-y-2 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium text-gray-900">{b.title}</p>
                    <StatusBadge {...bannerStatus(b.status)} />
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone="gray">{b.placement}</Badge>
                    <Badge tone="gray">#{b.sort_order}</Badge>
                    <Badge tone="blue">{b.media_type === "LOTTIE" ? "Lottie" : titleCase(b.media_type)}</Badge>
                  </div>
                  <p className="truncate text-xs text-gray-500">Tap: {describeAction(b)}</p>
                  {(b.starts_at || b.ends_at) && (
                    <p className="text-xs text-gray-500">
                      {b.starts_at ? dateTime(b.starts_at) : "Now"} → {b.ends_at ? dateTime(b.ends_at) : "no end"}
                    </p>
                  )}
                  <div className="flex items-center justify-between pt-1">
                    <Checkbox
                      checked={b.is_active}
                      onChange={(active) => update.mutate({ id: b.id, body: { is_active: active } }, { onSuccess: () => toast(active ? "Banner activated" : "Banner deactivated") })}
                      label="Active"
                    />
                    <span className="flex gap-1">
                      <IconButton label="Edit" className="size-8" onClick={() => setEditing(b)}>
                        <Pencil className="size-4" />
                      </IconButton>
                      <IconButton
                        label="Delete"
                        className="size-8 hover:bg-red-50 hover:text-red-600"
                        onClick={() =>
                          confirm({
                            title: `Delete “${b.title}”?`,
                            description: "It disappears from the apps. To take it down for now, untick Active instead.",
                            confirmLabel: "Delete banner",
                            tone: "danger",
                            onConfirm: () => remove.mutateAsync(b.id).then(() => toast("Banner deleted")),
                          })
                        }
                      >
                        <Trash2 className="size-4" />
                      </IconButton>
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        <Pagination meta={banners.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      {editing && <BannerDialog banner={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {dialog}
    </>
  );
}
