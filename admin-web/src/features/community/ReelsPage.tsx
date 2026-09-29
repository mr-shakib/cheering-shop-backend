/* Reels: restaurants' short videos in the customer app. An admin can post
 * for any restaurant, hide one from the feed (the vendor sees the reason),
 * edit the caption, or delete it (docs/ADMIN-API.md §13). */
import { useState } from "react";
import { EyeOff, Eye, Pencil, Play, Plus, Trash2 } from "lucide-react";

import { useCreateReel, useDeleteReel, useReels, useUpdateReel, type Reel } from "@/api/content";
import { loadProductOptions, loadRestaurantOptions } from "@/api/pickers";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Badge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Field, Select, TextArea } from "@/components/ui/Field";
import { FileDrop, Picker, type PickerOption } from "@/components/ui/Inputs";
import { Modal } from "@/components/ui/Overlay";
import { Pagination } from "@/components/ui/Pagination";
import { useToast } from "@/components/ui/Toast";
import { ago, count } from "@/lib/format";
import { useListParams } from "@/lib/hooks";
import { ACCEPT } from "@/lib/upload";

function ReelDialog({ reel, onClose }: { reel: Reel | null; onClose: () => void }) {
  const create = useCreateReel();
  const update = useUpdateReel();
  const toast = useToast();
  const [restaurant, setRestaurant] = useState<PickerOption | null>(reel ? { value: reel.restaurant_id, label: reel.restaurant_name } : null);
  const [video, setVideo] = useState<string | null>(reel?.video_url ?? null);
  const [thumb, setThumb] = useState<string | null>(reel?.thumbnail_url ?? null);
  const [caption, setCaption] = useState(reel?.caption ?? "");
  const [duration, setDuration] = useState<number | null>(reel?.duration_seconds ?? null);
  const [dish, setDish] = useState<PickerOption | null>(reel?.menu_item_id ? { value: reel.menu_item_id, label: reel.menu_item_name ?? "Dish" } : null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setError(null);
    try {
      if (reel) {
        await update.mutateAsync({ id: reel.id, body: { caption: caption.trim() || null, thumbnail_url: thumb, menu_item_id: dish?.value ?? null } });
        toast("Reel saved");
      } else {
        if (!restaurant) throw new Error("Choose the restaurant the reel belongs to.");
        if (!video) throw new Error("Upload the video first.");
        await create.mutateAsync({
          restaurant_id: restaurant.value,
          video_url: video,
          thumbnail_url: thumb,
          caption: caption.trim() || null,
          duration_seconds: duration,
          menu_item_id: dish?.value ?? null,
        });
        toast("Reel posted");
      }
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
      title={reel ? "Edit reel" : "Post a reel"}
      description={reel ? `${reel.restaurant_name}` : "Posted on the restaurant's behalf; it appears in the customer app's Reels feed."}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={create.isPending || update.isPending}>
            {reel ? "Save" : "Post reel"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {!reel && (
          <Field label="Restaurant">
            {() => (
              <Picker
                value={restaurant?.value ?? null}
                valueLabel={restaurant?.label}
                onChange={(o) => {
                  setRestaurant(o);
                  setDish(null);
                }}
                load={loadRestaurantOptions}
                placeholder="Choose a restaurant"
              />
            )}
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {!reel && (
            <Field label="Video" hint={duration ? `${duration} seconds` : "MP4, MOV or WebM"}>
              {() => (
                <>
                  <FileDrop kind="file" value={video} onChange={setVideo} accept={ACCEPT.video} label="Upload video" />
                  {video && (
                    <video
                      src={video}
                      className="hidden"
                      preload="metadata"
                      onLoadedMetadata={(e) => setDuration(Math.max(1, Math.round(e.currentTarget.duration)) || null)}
                    />
                  )}
                </>
              )}
            </Field>
          )}
          <Field label="Thumbnail">{() => <FileDrop value={thumb} onChange={setThumb} accept={ACCEPT.image} label="Add thumbnail" />}</Field>
        </div>
        <Field label="Caption">
          {(id) => <TextArea id={id} value={caption} onChange={(e) => setCaption(e.target.value)} maxLength={300} counter className="min-h-16" />}
        </Field>
        <Field label="Dish shown (optional)">
          {() => (
            <Picker
              value={dish?.value ?? null}
              valueLabel={dish?.label}
              onChange={setDish}
              allowClear
              disabled={!restaurant}
              load={async (q) => (restaurant ? loadProductOptions(q, restaurant.value) : [])}
              placeholder={restaurant ? "Link a dish from the menu" : "Choose the restaurant first"}
            />
          )}
        </Field>
        <InlineError error={error} />
      </div>
    </Modal>
  );
}

export function ReelsPage() {
  const list = useListParams(["status"] as const, { status: "ALL" });
  const reels = useReels({ status: list.values.status, limit: 12, offset: (list.page - 1) * 12 });
  const update = useUpdateReel();
  const remove = useDeleteReel();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [editing, setEditing] = useState<Reel | "new" | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        title="Reels"
        subtitle={reels.data ? `${count(reels.data.meta.total)} reels` : " "}
        actions={
          <Button size="sm" className="h-10 rounded-full px-4" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
            Post Reel
          </Button>
        }
      />
      <ListCard
        toolbar={
          <Select
            className="sm:ml-auto"
            aria-label="Status"
            options={[
              { value: "ALL", label: "All reels" },
              { value: "LIVE", label: "Live" },
              { value: "HIDDEN", label: "Hidden" },
            ]}
            value={list.values.status}
            onChange={(e) => list.set({ status: e.target.value })}
          />
        }
      >
        {reels.isPending ? (
          <PageSpinner />
        ) : reels.isError ? (
          <ErrorState error={reels.error} onRetry={() => reels.refetch()} />
        ) : reels.data.items.length === 0 ? (
          <EmptyState>No reels yet.</EmptyState>
        ) : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4 min-[87.5rem]:grid-cols-6">
            {reels.data.items.map((r) => (
              <div key={r.id} className="overflow-hidden rounded-xl border border-line bg-white">
                <div className="relative aspect-[9/16] bg-gray-900">
                  {playing === r.id ? (
                    <video src={r.video_url} className="size-full object-cover" controls autoPlay />
                  ) : (
                    <button type="button" onClick={() => setPlaying(r.id)} className="group absolute inset-0" aria-label="Play">
                      {r.thumbnail_url && <img src={r.thumbnail_url} alt="" className="size-full object-cover" />}
                      <span className="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/30">
                        <span className="flex size-11 items-center justify-center rounded-full bg-white/90 text-gray-900">
                          <Play className="ml-0.5 size-5 fill-gray-900" />
                        </span>
                      </span>
                    </button>
                  )}
                  {r.is_hidden && (
                    <Badge tone="red" className="absolute top-2 left-2">
                      Hidden
                    </Badge>
                  )}
                  {r.duration_seconds && <span className="absolute right-2 bottom-2 rounded bg-black/60 px-1.5 text-[11px] text-white">{r.duration_seconds}s</span>}
                </div>
                <div className="p-3">
                  <p className="truncate text-sm font-medium text-gray-900">{r.restaurant_name}</p>
                  <p className="line-clamp-2 min-h-8 text-xs text-gray-600">{r.caption || <span className="text-gray-400">No caption</span>}</p>
                  {r.is_hidden && r.hidden_reason && <p className="mt-1 line-clamp-2 text-[11px] text-red-600">“{r.hidden_reason}”</p>}
                  <p className="mt-1 text-[11px] text-gray-400">
                    {ago(r.created_at)}
                    {r.menu_item_name && ` · ${r.menu_item_name}`}
                  </p>
                  <div className="mt-2 flex items-center justify-end gap-1">
                    <IconButton label="Edit" className="size-8" onClick={() => setEditing(r)}>
                      <Pencil className="size-4" />
                    </IconButton>
                    <IconButton
                      label={r.is_hidden ? "Show in feed" : "Hide from feed"}
                      className="size-8"
                      onClick={() =>
                        r.is_hidden
                          ? update.mutate({ id: r.id, body: { is_hidden: false } }, { onSuccess: () => toast("Reel is back in the feed") })
                          : confirm({
                              title: "Hide this reel?",
                              description: "It leaves the customer feed. The vendor still sees it, with your reason.",
                              confirmLabel: "Hide reel",
                              tone: "danger",
                              reason: { label: "Reason (shown to the vendor)", placeholder: "e.g. The video shows another brand's logo" },
                              onConfirm: (reason) =>
                                update.mutateAsync({ id: r.id, body: { is_hidden: true, hidden_reason: reason || null } }).then(() => toast("Reel hidden")),
                            })
                      }
                    >
                      {r.is_hidden ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
                    </IconButton>
                    <IconButton
                      label="Delete"
                      className="size-8 hover:bg-red-50 hover:text-red-600"
                      onClick={() =>
                        confirm({
                          title: "Delete this reel?",
                          description: "It is removed for good, for the vendor too. Hide it instead to keep it.",
                          confirmLabel: "Delete reel",
                          tone: "danger",
                          onConfirm: () => remove.mutateAsync(r.id).then(() => toast("Reel deleted")),
                        })
                      }
                    >
                      <Trash2 className="size-4" />
                    </IconButton>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        <Pagination meta={reels.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      {editing && <ReelDialog reel={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {dialog}
    </>
  );
}

