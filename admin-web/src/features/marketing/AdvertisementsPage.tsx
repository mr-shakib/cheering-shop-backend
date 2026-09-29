import { Link } from "react-router";
import { Pause, Play, Square } from "lucide-react";

import { useAds, useSetAdStatus, type AdCampaign } from "@/api/marketing";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { IconButton } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, opt } from "@/lib/api";
import { count, dateOnly, money } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";
import { adStatus } from "@/lib/vocab";

export function AdvertisementsPage() {
  const list = useListParams(["q", "status"] as const);
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const ads = useAds({ q: opt(v.q), status: opt(v.status), limit: list.limit, offset: list.offset });
  const setStatus = useSetAdStatus();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const active = ads.data?.meta.active;

  const act = (a: AdCampaign, status: "ACTIVE" | "PAUSED") =>
    setStatus.mutate(
      { id: a.id, status },
      { onSuccess: () => toast(status === "PAUSED" ? "Campaign paused" : "Campaign resumed"), onError: (e) => toast(errorMessage(e), "error") },
    );

  const columns: Column<AdCampaign>[] = [
    {
      key: "vendor",
      header: "Vendor",
      cell: (a) => (
        <Link to={`/vendors/${a.restaurant_id}`} className="text-gray-900 hover:text-brand-500">
          {a.restaurant_name}
        </Link>
      ),
    },
    {
      key: "campaign",
      header: "Campaign",
      cell: (a) => (
        <span>
          <span className="block text-gray-900">{a.campaign}</span>
          <span className="block font-mono text-xs text-gray-500">{a.code}</span>
        </span>
      ),
    },
    {
      key: "budget",
      header: "Budget",
      cell: (a) => (
        <span>
          <span className="block">{a.budget != null ? money(a.budget) : "No cap"}</span>
          <span className="block text-xs text-gray-500">{money(a.spent)} spent</span>
        </span>
      ),
    },
    { key: "impressions", header: "Impression", cell: (a) => count(a.impressions) },
    {
      key: "clicks",
      header: "Click",
      cell: (a) => (
        <span>
          {count(a.clicks)}
          {a.impressions > 0 && <span className="ml-1 text-xs text-gray-500">({((a.clicks / a.impressions) * 100).toFixed(1)}%)</span>}
        </span>
      ),
    },
    { key: "redemptions", header: "Used", cell: (a) => count(a.redemptions) },
    { key: "revenue", header: "Revenue", cell: (a) => money(a.revenue) },
    {
      key: "window",
      header: "Runs",
      cell: (a) => (
        <span className="text-xs whitespace-nowrap text-gray-600">
          {dateOnly(a.valid_from)} – {dateOnly(a.valid_until)}
        </span>
      ),
    },
    { key: "status", header: "Status", cell: (a) => <StatusBadge {...adStatus(a.status)} dot={false} /> },
    {
      key: "action",
      header: "",
      align: "right",
      cell: (a) =>
        a.status === "ENDED" ? null : (
          <span className="inline-flex gap-1">
            {a.status === "PAUSED" ? (
              <IconButton label="Resume" className="size-8" onClick={() => act(a, "ACTIVE")}>
                <Play className="size-4" />
              </IconButton>
            ) : (
              <IconButton label="Pause" className="size-8" onClick={() => act(a, "PAUSED")}>
                <Pause className="size-4" />
              </IconButton>
            )}
            <IconButton
              label="End campaign"
              className="size-8 hover:bg-red-50 hover:text-red-600"
              onClick={() =>
                confirm({
                  title: `End ${a.campaign} for ${a.restaurant_name}?`,
                  description: "Ending is final: the offer stops at once and cannot be resumed. The vendor sees the change in their app.",
                  confirmLabel: "End campaign",
                  tone: "danger",
                  onConfirm: () => setStatus.mutateAsync({ id: a.id, status: "ENDED" }).then(() => toast("Campaign ended")),
                })
              }
            >
              <Square className="size-4" />
            </IconButton>
          </span>
        ),
    },
  ];

  return (
    <>
      <PageHeader title="Advertisements" subtitle={active !== undefined ? `${count(active)} active campaign${active === 1 ? "" : "s"}` : " "} />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search vendor or code..." />
            <Select
              className="sm:ml-auto"
              aria-label="Status"
              placeholder="All Status"
              options={[
                { value: "ACTIVE", label: "Active" },
                { value: "SCHEDULED", label: "Scheduled" },
                { value: "PAUSED", label: "Paused" },
                { value: "ENDED", label: "Ended" },
              ]}
              value={v.status}
              onChange={(e) => list.set({ status: e.target.value })}
            />
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={ads.data?.items}
          rowKey={(a) => a.id}
          loading={ads.isPending}
          error={ads.error}
          onRetry={() => ads.refetch()}
          minWidth={1000}
          empty="No campaigns match. Vendors create them as promotions in their app."
        />
        <Pagination meta={ads.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      {dialog}
    </>
  );
}
