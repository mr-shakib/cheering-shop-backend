import { Link } from "react-router";
import { BellOff, Plus } from "lucide-react";

import { useCampaigns, useCancelCampaign, type NotificationCampaign } from "@/api/marketing";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { opt } from "@/lib/api";
import { count, dateTimeLong, titleCase } from "@/lib/format";
import { useListParams } from "@/lib/hooks";
import { campaignStatus } from "@/lib/vocab";

export const AUDIENCE_OPTIONS = [
  { value: "CUSTOMER", label: "Customer" },
  { value: "VENDOR", label: "Vendor" },
  { value: "RIDER", label: "Rider" },
  { value: "ALL", label: "Everyone" },
];

export function NotificationsPage() {
  const list = useListParams(["status", "audience"] as const);
  const { values: v } = list;
  const campaigns = useCampaigns({ status: opt(v.status), audience: opt(v.audience), limit: list.limit, offset: list.offset });
  const cancel = useCancelCampaign();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const pushOff = campaigns.data?.items.some((c) => !c.push_enabled);

  const columns: Column<NotificationCampaign>[] = [
    {
      key: "title",
      header: "Title",
      cell: (c) => (
        <span className="block max-w-80">
          <span className="block truncate text-gray-900">{c.title}</span>
          <span className="block truncate text-xs text-gray-500">{c.message}</span>
        </span>
      ),
    },
    { key: "type", header: "Type", cell: (c) => titleCase(c.type) },
    { key: "audience", header: "Audience", cell: (c) => (c.audience === "ALL" ? "Everyone" : titleCase(c.audience)) },
    {
      key: "when",
      header: "Sent At",
      cell: (c) => <span className="whitespace-nowrap text-gray-600">{dateTimeLong(c.sent_at ?? c.scheduled_for)}</span>,
    },
    {
      key: "reach",
      header: "Reached",
      cell: (c) =>
        c.status === "SENT" ? (
          <span className="text-xs text-gray-600">
            {count(c.recipient_count)} inboxes · {count(c.push_sent_count)} phones
          </span>
        ) : (
          <span className="text-gray-400">—</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      cell: (c) => (
        <span title={c.failure_reason ?? undefined}>
          <StatusBadge {...campaignStatus(c.status)} dot={false} />
        </span>
      ),
    },
    {
      key: "action",
      header: "",
      align: "right",
      cell: (c) =>
        c.status === "SCHEDULED" ? (
          <Button
            size="xs"
            variant="ghost"
            className="text-red-600 hover:bg-red-50"
            onClick={() =>
              confirm({
                title: `Cancel “${c.title}”?`,
                description: `It was going out ${dateTimeLong(c.scheduled_for)}. Nobody will receive it.`,
                confirmLabel: "Cancel notification",
                tone: "danger",
                onConfirm: () => cancel.mutateAsync(c.id).then(() => toast("Notification cancelled")),
              })
            }
          >
            Cancel
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        title="Notification"
        subtitle="Compose and send a push campaign"
        actions={
          <Link to="/notifications/new">
            <Button size="sm" className="h-10 px-4" icon={<Plus className="size-4" />}>
              Create New Notification
            </Button>
          </Link>
        }
      />
      {pushOff && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-900">
          <BellOff className="mt-0.5 size-4 shrink-0" />
          Push is not configured on the server (FCM_SERVICE_ACCOUNT_JSON), so notifications reach in-app inboxes but no phone is buzzed.
        </div>
      )}
      <ListCard
        toolbar={
          <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
            <Select aria-label="Audience" placeholder="All audiences" options={AUDIENCE_OPTIONS} value={v.audience} onChange={(e) => list.set({ audience: e.target.value })} />
            <Select
              aria-label="Status"
              placeholder="All Status"
              options={[
                { value: "SENT", label: "Sent" },
                { value: "SCHEDULED", label: "Scheduled" },
                { value: "FAILED", label: "Failed" },
                { value: "CANCELLED", label: "Cancelled" },
              ]}
              value={v.status}
              onChange={(e) => list.set({ status: e.target.value })}
            />
          </div>
        }
      >
        <DataTable
          columns={columns}
          rows={campaigns.data?.items}
          rowKey={(c) => c.id}
          loading={campaigns.isPending}
          error={campaigns.error}
          onRetry={() => campaigns.refetch()}
          empty="No notifications have been sent yet."
        />
        <Pagination meta={campaigns.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      {dialog}
    </>
  );
}
