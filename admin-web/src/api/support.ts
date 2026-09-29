/* Support tickets and Live Chat (app/schemas/support.py). There is no push
 * channel for the console, so an open conversation polls. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, get, patch, post, type Page, type PageMeta, type Query } from "@/lib/api";

export interface TicketParty {
  id: string;
  full_name: string | null;
  role: string;
  phone: string | null;
  avatar_url: string | null;
}

export interface Attachment {
  url: string;
  name: string;
}

export interface SupportMessage {
  id: string;
  kind: "MESSAGE" | "EVENT";
  sender_id: string | null;
  sender_role: string | null;
  sender_name: string | null;
  body: string;
  attachments: Attachment[];
  created_at: string;
}

export interface SupportTicket {
  id: string;
  ticket_number: number;
  code: string;
  subject: string;
  type: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "URGENT";
  status: "OPEN" | "PENDING" | "RESOLVED" | "CLOSED";
  order_id: string | null;
  order_number: number | null;
  user: TicketParty;
  assigned_to: TicketParty | null;
  unread: boolean;
  last_message_preview: string | null;
  last_message_at: string;
  created_at: string;
  resolved_at: string | null;
  closed_at: string | null;
}

export interface SupportTicketDetail extends SupportTicket {
  messages: SupportMessage[];
}

export interface QueueCounts {
  open: number;
  pending: number;
  resolved: number;
  closed: number;
  unread: number;
  urgent: number;
}

export type TicketPage = Page<SupportTicket> & { meta: PageMeta & { counts?: QueueCounts } };

export const TICKET_TYPES = ["ORDER_ISSUE", "RIDER_COMPLAINT", "VENDOR_COMPLAINT", "PAYMENT", "REFUND", "ACCOUNT", "OTHER"] as const;

export function useTickets(query: Query, poll = false) {
  return useQuery({
    queryKey: ["tickets", query],
    queryFn: ({ signal }) => apiPage<SupportTicket>("/admin/support/tickets", query, signal) as Promise<TicketPage>,
    placeholderData: keepPreviousData,
    refetchInterval: poll ? 15_000 : false,
  });
}

export function useTicket(id: string | null) {
  return useQuery({
    queryKey: ["ticket", id],
    queryFn: ({ signal }) => get<SupportTicketDetail>(`/admin/support/tickets/${id}`, undefined, signal),
    enabled: !!id,
    refetchInterval: 5_000,
  });
}

function useTicketMutation<V>(fn: (vars: V) => Promise<SupportTicketDetail>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (ticket) => qc.setQueryData(["ticket", ticket.id], ticket),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useReply = () =>
  useTicketMutation(({ id, body, attachments }: { id: string; body: string; attachments: Attachment[] }) =>
    post<SupportTicketDetail>(`/admin/support/tickets/${id}/messages`, { body, attachments }),
  );

export const useUpdateTicket = () =>
  useTicketMutation(({ id, body }: { id: string; body: { status?: string; priority?: string; assigned_to?: string | null } }) =>
    patch<SupportTicketDetail>(`/admin/support/tickets/${id}`, body),
  );
