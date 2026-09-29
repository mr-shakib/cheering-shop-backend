import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { Loader2, MessagesSquare, Paperclip, SendHorizonal, X } from "lucide-react";

import { useReply, useTicket, useTickets, useUpdateTicket, type Attachment, type SupportTicketDetail } from "@/api/support";
import { PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Avatar } from "@/components/ui/Display";
import { EmptyState, ErrorState, InlineError, Spinner } from "@/components/ui/Feedback";
import { SearchInput } from "@/components/ui/Field";
import { Chips } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, opt } from "@/lib/api";
import { cn } from "@/lib/cn";
import { count, dateTimeLong, orderNo, timeOnly, titleCase } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { uploadFile, ACCEPT } from "@/lib/upload";
import { ticketPriority, ticketStatus } from "@/lib/vocab";

import { OrderDrawer } from "../orders/OrderDrawer";

type Filter = "ACTIVE" | "ALL" | "OPEN" | "PENDING" | "RESOLVED";

function TicketList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const [filter, setFilter] = useState<Filter>("ACTIVE");
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 300);
  const tickets = useTickets({ status: filter === "ALL" ? undefined : filter, q: opt(debounced), limit: 50 }, true);
  const counts = tickets.data?.meta.counts;

  return (
    <Card className="flex min-h-0 flex-col p-4 lg:h-[640px] min-[87.5rem]:h-full">
      <Chips
        items={[
          { key: "ACTIVE" as Filter, label: "Active" },
          { key: "OPEN" as Filter, label: `Open${counts ? ` ${counts.open}` : ""}` },
          { key: "PENDING" as Filter, label: `Pending${counts ? ` ${counts.pending}` : ""}` },
          { key: "RESOLVED" as Filter, label: "Resolved" },
          { key: "ALL" as Filter, label: "All" },
        ]}
        active={filter}
        onChange={setFilter}
      />
      <SearchInput value={q} onChange={setQ} placeholder="Search tickets..." className="mt-3 sm:max-w-none" />
      <div className="scrollbar-thin -mx-2 mt-3 min-h-0 flex-1 overflow-y-auto px-2">
        {tickets.isPending ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : tickets.isError ? (
          <ErrorState error={tickets.error} onRetry={() => tickets.refetch()} />
        ) : tickets.data.items.length === 0 ? (
          <EmptyState>No tickets here.</EmptyState>
        ) : (
          tickets.data.items.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onSelect(t.id)}
              className={cn(
                "flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors hover:bg-gray-50",
                selected === t.id && "bg-gray-100 hover:bg-gray-100",
              )}
            >
              <Avatar src={t.user.avatar_url} name={t.user.full_name} size={40} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="truncate text-[15px] text-gray-900">{t.user.full_name ?? t.user.phone ?? "User"}</span>
                  {t.priority === "URGENT" && <span className="rounded bg-red-50 px-1.5 text-[10px] font-semibold text-red-600">URGENT</span>}
                </span>
                <span className="block truncate text-xs text-gray-500">
                  {titleCase(t.type)} · {t.code}
                </span>
              </span>
              {t.unread && <span className="size-2 shrink-0 rounded-full bg-red-500" aria-label="Unread" />}
            </button>
          ))
        )}
      </div>
    </Card>
  );
}

function Composer({ ticket }: { ticket: SupportTicketDetail }) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const reply = useReply();
  const fileInput = useRef<HTMLInputElement>(null);
  const closed = ticket.status === "CLOSED";

  useEffect(() => {
    setText("");
    setFiles([]);
    setUploadError(null);
  }, [ticket.id]);

  const send = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || reply.isPending) return;
    reply.mutate(
      { id: ticket.id, body: text.trim(), attachments: files },
      {
        onSuccess: () => {
          setText("");
          setFiles([]);
        },
      },
    );
  };

  if (closed) {
    return <p className="border-t border-line px-5 py-4 text-center text-sm text-gray-500">This ticket is closed. Nobody can reply.</p>;
  }

  return (
    <form onSubmit={send} className="border-t border-line px-4 py-3">
      {(files.length > 0 || uploading) && (
        <div className="mb-2 flex flex-wrap gap-2">
          {files.map((f) => (
            <span key={f.url} className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700">
              <Paperclip className="size-3" /> {f.name}
              <button type="button" onClick={() => setFiles((all) => all.filter((x) => x.url !== f.url))} aria-label={`Remove ${f.name}`}>
                <X className="size-3 text-gray-400 hover:text-gray-700" />
              </button>
            </span>
          ))}
          {uploading && <Loader2 className="size-4 animate-spin text-gray-400" />}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          className="flex size-10 shrink-0 items-center justify-center rounded-full text-gray-600 hover:bg-gray-100"
          aria-label="Attach a file"
        >
          <Paperclip className="size-5" />
        </button>
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT.document}
          className="hidden"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            setUploading(true);
            setUploadError(null);
            try {
              const url = await uploadFile(file);
              setFiles((all) => [...all, { url, name: file.name }]);
            } catch (err) {
              setUploadError(err);
            } finally {
              setUploading(false);
            }
          }}
        />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type a reply..."
          maxLength={5000}
          className="h-10 min-w-0 flex-1 rounded-full border border-gray-200 px-4 text-sm outline-none focus:border-brand-300 focus:ring-3 focus:ring-brand-100"
        />
        <button
          type="submit"
          disabled={!text.trim() || reply.isPending || uploading}
          className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-500 text-white hover:bg-brand-600 disabled:bg-brand-300"
          aria-label="Send"
        >
          {reply.isPending ? <Loader2 className="size-4 animate-spin" /> : <SendHorizonal className="size-4" />}
        </button>
      </div>
      <div className="mt-2 empty:hidden">
        <InlineError error={reply.error ?? uploadError} />
      </div>
    </form>
  );
}

function Conversation({ ticket }: { ticket: SupportTicketDetail }) {
  const update = useUpdateTicket();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const end = useRef<HTMLDivElement>(null);
  const messages = ticket.messages.filter((m) => m.kind === "MESSAGE");

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [ticket.id, messages.length]);

  return (
    <Card className="flex min-h-[520px] flex-col overflow-hidden lg:h-[640px] min-[87.5rem]:h-full">
      <div className="flex items-center gap-3 border-b border-line px-5 py-3.5">
        <Avatar src={ticket.user.avatar_url} name={ticket.user.full_name} size={48} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold text-gray-900">{ticket.user.full_name ?? ticket.user.phone ?? "User"}</p>
          <p className="truncate text-xs text-gray-500">
            {ticket.code} · {ticket.subject}
          </p>
        </div>
        {ticket.status !== "CLOSED" && (
          <div className="flex shrink-0 gap-2">
            {ticket.status !== "RESOLVED" && (
              <Button
                size="sm"
                variant="success-soft"
                loading={update.isPending && update.variables?.body.status === "RESOLVED"}
                onClick={() =>
                  update.mutate(
                    { id: ticket.id, body: { status: "RESOLVED" } },
                    { onSuccess: () => toast("Marked resolved. The user replying reopens it."), onError: (e) => toast(errorMessage(e), "error") },
                  )
                }
              >
                Resolve
              </Button>
            )}
            <Button
              size="sm"
              variant="danger-soft"
              onClick={() =>
                confirm({
                  title: `Close ${ticket.code}?`,
                  description: "Closing is final: nobody can reply to it afterwards.",
                  confirmLabel: "Close ticket",
                  tone: "danger",
                  onConfirm: () => update.mutateAsync({ id: ticket.id, body: { status: "CLOSED" } }).then(() => toast("Ticket closed")),
                })
              }
            >
              Close
            </Button>
          </div>
        )}
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-5">
        {messages.map((m) => {
          const mine = m.sender_role === "ADMIN";
          return (
            <div key={m.id} className={cn("flex flex-col", mine ? "items-end" : "items-start")}>
              {mine && m.sender_name && <span className="mb-1 text-[11px] text-gray-400">{m.sender_name}</span>}
              <div
                className={cn(
                  "max-w-[80%] rounded-xl px-3.5 py-2.5 text-[15px] whitespace-pre-wrap",
                  mine ? "bg-brand-500 text-white" : "border border-gray-200 bg-white text-gray-900",
                )}
              >
                {m.body}
                <span className={cn("mt-1.5 block text-[11px]", mine ? "text-brand-100" : "text-gray-500")}>{timeOnly(m.created_at)}</span>
              </div>
              {m.attachments.length > 0 && (
                <div className={cn("mt-1.5 flex flex-wrap gap-2", mine && "justify-end")}>
                  {m.attachments.map((a) => (
                    <a
                      key={a.url}
                      href={a.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-800 hover:bg-gray-50"
                    >
                      <Paperclip className="size-3.5" /> {a.name}
                    </a>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        <div ref={end} />
      </div>
      <Composer ticket={ticket} />
      {dialog}
    </Card>
  );
}

function TicketDetails({ ticket, onOpenOrder }: { ticket: SupportTicketDetail; onOpenOrder: (id: string) => void }) {
  const update = useUpdateTicket();
  const toast = useToast();
  const history = ticket.messages.filter((m) => m.kind === "EVENT");
  const row = "flex items-center justify-between gap-3 py-1.5 text-sm";
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h3 className="mb-3 text-base font-semibold text-gray-900">Ticket details</h3>
        <div className={row}>
          <span className="text-gray-500">Type</span>
          <span className="text-gray-900">{titleCase(ticket.type)}</span>
        </div>
        <div className={row}>
          <span className="text-gray-500">Priority</span>
          <select
            aria-label="Priority"
            value={ticket.priority}
            disabled={ticket.status === "CLOSED" || update.isPending}
            onChange={(e) =>
              update.mutate(
                { id: ticket.id, body: { priority: e.target.value } },
                { onSuccess: () => toast("Priority changed"), onError: (err) => toast(errorMessage(err), "error") },
              )
            }
            className={cn(
              "h-7 cursor-pointer appearance-none rounded-full border-0 px-3 text-xs font-medium outline-none",
              { green: "bg-green-50 text-green-600", orange: "bg-orange-50 text-orange-500", red: "bg-red-50 text-red-500", gray: "bg-slate-100 text-slate-600" }[
                ticketPriority(ticket.priority).tone as "green" | "orange" | "red" | "gray"
              ] ?? "bg-slate-100",
            )}
          >
            {["LOW", "MEDIUM", "HIGH", "URGENT"].map((p) => (
              <option key={p} value={p}>
                {titleCase(p)}
              </option>
            ))}
          </select>
        </div>
        <div className={row}>
          <span className="text-gray-500">Status</span>
          <StatusBadge {...ticketStatus(ticket.status)} />
        </div>
        <div className={row}>
          <span className="text-gray-500">User</span>
          <span className="text-gray-900">{titleCase(ticket.user.role)}</span>
        </div>
        <div className={row}>
          <span className="text-gray-500">Phone</span>
          {ticket.user.phone ? (
            <a href={`tel:${ticket.user.phone}`} className="text-gray-900 hover:text-brand-500">
              {ticket.user.phone}
            </a>
          ) : (
            <span className="text-gray-400">—</span>
          )}
        </div>
        <div className={row}>
          <span className="text-gray-500">Related order</span>
          {ticket.order_id ? (
            <button type="button" onClick={() => onOpenOrder(ticket.order_id!)} className="font-medium text-gray-900 hover:text-brand-500">
              {orderNo(ticket.order_number)}
            </button>
          ) : (
            <span className="text-gray-400">None</span>
          )}
        </div>
        <div className={row}>
          <span className="text-gray-500">Assigned to</span>
          <span className="text-gray-900">{ticket.assigned_to?.full_name ?? "Nobody yet"}</span>
        </div>
        {ticket.user.role === "CUSTOMER" && (
          <Link to={`/customers/${ticket.user.id}`} className="mt-2 block text-xs font-medium text-brand-500 hover:underline">
            Open customer profile
          </Link>
        )}
        {ticket.user.role === "RIDER" && (
          <Link to={`/riders/${ticket.user.id}`} className="mt-2 block text-xs font-medium text-brand-500 hover:underline">
            Open rider profile
          </Link>
        )}
      </Card>
      <Card className="p-4">
        <h3 className="mb-3 text-base font-semibold text-gray-900">History</h3>
        <ol className="space-y-3">
          {history.map((h) => (
            <li key={h.id} className="flex gap-2.5">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand-500" />
              <span className="text-xs">
                <span className="block text-gray-900">{h.body}</span>
                <span className="text-gray-500">{dateTimeLong(h.created_at)}</span>
              </span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

export function LiveChatPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("ticket");
  const [openOrder, setOpenOrder] = useState<string | null>(null);
  const ticket = useTicket(selected);
  const header = useTickets({ status: "PENDING", limit: 1 });

  return (
    <>
      <PageHeader title="Live Chat" subtitle={header.data?.meta.counts ? `${count(header.data.meta.counts.pending)} pending tickets · ${count(header.data.meta.counts.open)} waiting on support` : " "} />
      <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)] min-[87.5rem]:h-[calc(100vh-13.5rem)] min-[87.5rem]:min-h-[560px] min-[87.5rem]:grid-cols-[300px_minmax(0,1fr)_270px]">
        <TicketList selected={selected} onSelect={(id) => setParams({ ticket: id }, { replace: true })} />
        {!selected ? (
          <Card className="flex items-center justify-center lg:h-[640px] min-[87.5rem]:col-span-2 min-[87.5rem]:h-full">
            <EmptyState icon={<MessagesSquare className="size-5" />}>Choose a ticket to read the conversation.</EmptyState>
          </Card>
        ) : ticket.isPending ? (
          <Card className="flex items-center justify-center lg:h-[640px] min-[87.5rem]:col-span-2 min-[87.5rem]:h-full">
            <Spinner />
          </Card>
        ) : ticket.isError ? (
          <Card className="lg:h-[640px] min-[87.5rem]:col-span-2 min-[87.5rem]:h-full">
            <ErrorState error={ticket.error} onRetry={() => ticket.refetch()} />
          </Card>
        ) : (
          <>
            <Conversation ticket={ticket.data} />
            <div className="scrollbar-thin lg:col-span-2 min-[87.5rem]:col-span-1 min-[87.5rem]:overflow-y-auto">
              <TicketDetails ticket={ticket.data} onOpenOrder={setOpenOrder} />
            </div>
          </>
        )}
      </div>
      <OrderDrawer orderId={openOrder} onClose={() => setOpenOrder(null)} />
    </>
  );
}
