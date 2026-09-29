import { Ban, ShieldCheck, Trash2 } from "lucide-react";

import { useSetAccountActive } from "@/api/customers";
import { usePosts, useRemovePost, type ModeratedPost } from "@/api/content";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, opt } from "@/lib/api";
import { ago, count } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";

export function CommunityPage() {
  const list = useListParams(["q", "status", "sort"] as const, { status: "LIVE", sort: "reports" });
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const posts = usePosts({ q: opt(v.q), status: v.status, sort: v.sort, limit: list.limit, offset: list.offset });
  const remove = useRemovePost();
  const setActive = useSetAccountActive();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();

  const columns: Column<ModeratedPost>[] = [
    {
      key: "user",
      header: "User",
      cell: (p) => (
        <Identity
          src={p.author.avatar_url}
          name={p.author.full_name}
          sub={!p.author_is_active ? <span className="text-red-500">Banned</span> : ago(p.created_at)}
        />
      ),
    },
    {
      key: "content",
      header: "Content",
      cell: (p) => (
        <div className="max-w-xl">
          <p className="line-clamp-2 text-gray-900">{p.body}</p>
          {(p.image_urls.length > 0 || p.restaurant) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              {p.image_urls.map((url) => (
                <a key={url} href={url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                  <img src={url} alt="" className="size-10 rounded-md border border-line object-cover" />
                </a>
              ))}
              {p.restaurant && <Badge tone="pink">@ {p.restaurant.name}</Badge>}
            </div>
          )}
          {p.is_removed && (
            <p className="mt-1 text-xs text-red-600">
              Removed {ago(p.removed_at)}
              {p.removal_reason && ` — “${p.removal_reason}”`}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "reports",
      header: "Report",
      cell: (p) => (p.report_count > 0 ? <Badge tone={p.report_count >= 3 ? "red" : "orange"}>{p.report_count}</Badge> : <span className="text-gray-500">0</span>),
    },
    {
      key: "action",
      header: "Action",
      align: "right",
      cell: (p) => (
        <span className="inline-flex gap-2">
          {!p.is_removed && (
            <Button
              size="xs"
              variant="danger-soft"
              icon={<Trash2 className="size-3.5" />}
              onClick={() =>
                confirm({
                  title: "Delete this post?",
                  description: "It leaves every feed at once. It stays on record here.",
                  confirmLabel: "Delete post",
                  tone: "danger",
                  reason: { label: "Reason", required: true, minLength: 3, placeholder: "e.g. Spam, harassment, misleading claim" },
                  onConfirm: (reason) => remove.mutateAsync({ id: p.id, reason }).then(() => toast("Post removed")),
                })
              }
            >
              Delete
            </Button>
          )}
          {p.author_is_active ? (
            <Button
              size="xs"
              variant="outline"
              icon={<Ban className="size-3.5" />}
              onClick={() =>
                confirm({
                  title: `Ban ${p.author.full_name ?? "this user"}?`,
                  description: "Their account is blocked and signed out everywhere: they cannot post, order or sign in until you unban them.",
                  confirmLabel: "Ban user",
                  tone: "danger",
                  onConfirm: () => setActive.mutateAsync({ id: p.author.id, isActive: false }).then(() => toast("User banned")),
                })
              }
            >
              Ban user
            </Button>
          ) : (
            <Button
              size="xs"
              variant="success-soft"
              icon={<ShieldCheck className="size-3.5" />}
              onClick={() =>
                setActive.mutate(
                  { id: p.author.id, isActive: true },
                  { onSuccess: () => toast("User unbanned"), onError: (e) => toast(errorMessage(e), "error") },
                )
              }
            >
              Unban
            </Button>
          )}
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Community" subtitle={posts.data ? `${count(posts.data.meta.total)} posts` : " "} />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search post text or author..." />
            <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
              <Select
                aria-label="Status"
                options={[
                  { value: "LIVE", label: "Live" },
                  { value: "REPORTED", label: "Reported" },
                  { value: "REMOVED", label: "Removed" },
                  { value: "ALL", label: "All posts" },
                ]}
                value={v.status}
                onChange={(e) => list.set({ status: e.target.value })}
              />
              <Select
                aria-label="Sort"
                options={[
                  { value: "reports", label: "Most reported" },
                  { value: "recent", label: "Newest" },
                ]}
                value={v.sort}
                onChange={(e) => list.set({ sort: e.target.value })}
              />
            </div>
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={posts.data?.items}
          rowKey={(p) => p.id}
          loading={posts.isPending}
          error={posts.error}
          onRetry={() => posts.refetch()}
          empty="No posts match."
        />
        <Pagination meta={posts.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      {dialog}
    </>
  );
}
