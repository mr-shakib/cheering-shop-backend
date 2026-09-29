import { useNavigate } from "react-router";

import { TICKET_TYPES, useTickets, type SupportTicket } from "@/api/support";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { opt } from "@/lib/api";
import { ago, count, orderNo, titleCase } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";
import { ticketPriority, ticketStatus } from "@/lib/vocab";

export const TICKET_TYPE_OPTIONS = TICKET_TYPES.map((t) => ({ value: t, label: titleCase(t) }));

const columns: Column<SupportTicket>[] = [
  {
    key: "code",
    header: "Ticket ID",
    cell: (t) => (
      <span className="flex items-center gap-2 font-medium whitespace-nowrap text-gray-900">
        {t.unread && <span className="size-2 rounded-full bg-red-500" aria-label="Unread" />}#{t.code}
      </span>
    ),
  },
  { key: "user", header: "User", cell: (t) => <Identity src={t.user.avatar_url} name={t.user.full_name ?? t.user.phone} sub={titleCase(t.user.role)} /> },
  {
    key: "subject",
    header: "Subject",
    cell: (t) => (
      <span className="block max-w-72">
        <span className="block truncate text-gray-900">{t.subject}</span>
        <span className="block truncate text-xs text-gray-500">
          {titleCase(t.type)}
          {t.order_number != null && ` · ${orderNo(t.order_number)}`}
        </span>
      </span>
    ),
  },
  { key: "priority", header: "Priority", cell: (t) => <StatusBadge {...ticketPriority(t.priority)} dot={false} /> },
  { key: "status", header: "Status", cell: (t) => <StatusBadge {...ticketStatus(t.status)} /> },
  { key: "activity", header: "Last activity", cell: (t) => <span className="whitespace-nowrap text-gray-600">{ago(t.last_message_at)}</span> },
];

export function SupportTicketsPage() {
  const navigate = useNavigate();
  const list = useListParams(["q", "status", "priority", "type"] as const);
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const tickets = useTickets(
    { q: opt(v.q), status: opt(v.status), priority: opt(v.priority), type: opt(v.type), limit: list.limit, offset: list.offset },
    true,
  );
  const counts = tickets.data?.meta.counts;

  return (
    <>
      <PageHeader
        title="Support Ticket"
        subtitle={counts ? `${count(counts.open)} open · ${count(counts.pending)} pending · ${count(counts.unread)} unread` : " "}
      />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search ticket, subject, user or phone..." />
            <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
              <Select
                aria-label="Status"
                placeholder="All Status"
                options={[
                  { value: "ACTIVE", label: "Open & pending" },
                  { value: "OPEN", label: "Open" },
                  { value: "PENDING", label: "Pending" },
                  { value: "RESOLVED", label: "Resolved" },
                  { value: "CLOSED", label: "Closed" },
                ]}
                value={v.status}
                onChange={(e) => list.set({ status: e.target.value })}
              />
              <Select
                aria-label="Priority"
                placeholder="Any priority"
                options={["URGENT", "HIGH", "MEDIUM", "LOW"].map((p) => ({ value: p, label: titleCase(p) }))}
                value={v.priority}
                onChange={(e) => list.set({ priority: e.target.value })}
              />
              <Select aria-label="Type" placeholder="All Types" options={TICKET_TYPE_OPTIONS} value={v.type} onChange={(e) => list.set({ type: e.target.value })} />
            </div>
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={tickets.data?.items}
          rowKey={(t) => t.id}
          loading={tickets.isPending}
          error={tickets.error}
          onRetry={() => tickets.refetch()}
          onRowClick={(t) => navigate(`/live-chat?ticket=${t.id}`)}
          empty="No tickets match."
        />
        <Pagination meta={tickets.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
    </>
  );
}
