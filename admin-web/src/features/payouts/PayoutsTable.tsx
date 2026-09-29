/* The withdrawal queue, shared by vendors and riders: same statuses, same
 * three buttons, same rules (docs/ADMIN-API.md §5 and §8). */
import type { ReactNode } from "react";

import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { DataTable, type Column } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { dateTime, money } from "@/lib/format";
import { paymentMethod, payoutStatus } from "@/lib/vocab";

export interface PayoutLike {
  id: string;
  reference: string;
  amount: number;
  method: string;
  account_number: string;
  account_name: string;
  bank_name: string | null;
  status: "PROCESSING" | "COMPLETED" | "FAILED";
  failure_reason: string | null;
  requested_at: string;
  processed_at: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;
}

export type PayoutAction = (vars: { id: string; action: "complete" | "fail" | "reopen"; reason?: string }) => Promise<unknown>;

function destination(p: PayoutLike) {
  return `${paymentMethod(p.method)}${p.bank_name ? ` · ${p.bank_name}` : ""} · ${p.account_number}`;
}

export function PayoutsTable<T extends PayoutLike>({
  rows,
  loading,
  error,
  onRetry,
  party,
  act,
  showParty = true,
}: {
  rows: T[] | undefined;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  /** The first column: who is being paid. */
  party: { header: string; cell: (row: T) => ReactNode; name: (row: T) => string };
  act: PayoutAction;
  showParty?: boolean;
}) {
  const [confirm, dialog] = useConfirm();
  const toast = useToast();

  const columns: Column<T>[] = [
    ...(showParty ? [{ key: "party", header: party.header, cell: party.cell }] : []),
    { key: "ref", header: "Withdrawal ID", cell: (p) => <span className="font-medium whitespace-nowrap text-gray-900">{p.reference}</span> },
    { key: "amount", header: "Amount", cell: (p) => money(p.amount) },
    {
      key: "dest",
      header: "Payout Method",
      cell: (p) => (
        <span className="block max-w-56">
          <span className="block truncate">{destination(p)}</span>
          <span className="block truncate text-xs text-gray-500">{p.account_name}</span>
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (p) => (
        <span title={p.failure_reason ?? p.reopen_reason ?? undefined}>
          <StatusBadge {...payoutStatus(p.status)} dot={false} />
          {p.reopened_at && p.status === "PROCESSING" && <span className="mt-0.5 block text-[11px] text-gray-500">Reopened</span>}
        </span>
      ),
    },
    { key: "date", header: "Date", cell: (p) => <span className="whitespace-nowrap text-gray-600">{dateTime(p.requested_at)}</span> },
    {
      key: "action",
      header: "Action",
      align: "center",
      cell: (p) =>
        p.status === "PROCESSING" ? (
          <span className="inline-flex gap-2">
            <Button
              size="xs"
              variant="success-soft"
              className="h-8 px-3 text-sm"
              onClick={(e) => {
                e.stopPropagation();
                confirm({
                  title: `Mark ${money(p.amount)} as paid?`,
                  description: `Only once the transfer to ${party.name(p)} (${destination(p)}, ${p.account_name}) has gone through.`,
                  confirmLabel: "Mark Paid",
                  tone: "success",
                  onConfirm: () => act({ id: p.id, action: "complete" }).then(() => toast(`${p.reference} marked paid`)),
                });
              }}
            >
              Mark Paid
            </Button>
            <Button
              size="xs"
              variant="ghost"
              className="h-8 px-2 text-sm text-gray-500"
              onClick={(e) => {
                e.stopPropagation();
                confirm({
                  title: "The transfer failed?",
                  description: `${money(p.amount)} goes back to ${party.name(p)}'s balance, and they can request it again.`,
                  confirmLabel: "Mark failed",
                  tone: "danger",
                  reason: { label: "Reason (shown to them)", placeholder: "e.g. The account number was wrong" },
                  onConfirm: (reason) => act({ id: p.id, action: "fail", reason }).then(() => toast(`${p.reference} marked failed`)),
                });
              }}
            >
              Failed
            </Button>
          </span>
        ) : p.status === "COMPLETED" ? (
          <Button
            size="xs"
            variant="danger-soft"
            className="h-8 px-3 text-sm"
            onClick={(e) => {
              e.stopPropagation();
              confirm({
                title: `Mark ${p.reference} unpaid?`,
                description:
                  "For a transfer marked paid by mistake, or one that bounced afterwards. It goes back into the queue to be paid again; the balance does not change.",
                confirmLabel: "Mark Unpaid",
                tone: "danger",
                reason: { label: "Reason", required: true, minLength: 3, placeholder: "Kept on the payout for whoever asks what happened" },
                onConfirm: (reason) => act({ id: p.id, action: "reopen", reason }).then(() => toast(`${p.reference} is back in the queue`)),
              });
            }}
          >
            Mark Unpaid
          </Button>
        ) : (
          <span className="text-xs text-gray-400" title={p.failure_reason ?? undefined}>
            Returned to balance
          </span>
        ),
    },
  ];

  return (
    <>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(p) => p.id}
        loading={loading}
        error={error}
        onRetry={onRetry}
        empty="No withdrawals match."
        minWidth={860}
      />
      {dialog}
    </>
  );
}

export const PAYOUT_STATUS_OPTIONS = [
  { value: "PROCESSING", label: "Pending" },
  { value: "COMPLETED", label: "Paid" },
  { value: "FAILED", label: "Failed" },
  { value: "ALL", label: "All Status" },
];

/** The queues default to PROCESSING; "ALL" is sent as an empty status. */
export const payoutStatusParam = (v: string) => (v === "ALL" ? "" : v || undefined);
