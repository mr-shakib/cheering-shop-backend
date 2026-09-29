/* Riders: roster, profile, earnings, withdrawals, live map, applications
 * (app/schemas/admin/riders.py). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, get, patch, post, type Query } from "@/lib/api";

export interface AdminRiderRow {
  id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  vehicle_type: string | null;
  license_number: string | null;
  is_online: boolean;
  is_verified: boolean;
  orders_in_flight: number;
  total_deliveries: number;
  created_at: string;
  avatar_url: string | null;
  rating_avg: number;
  rating_count: number;
  live_status: "ONLINE" | "OFFLINE";
}

export interface RiderEarnings {
  rider_id: string;
  today: number;
  this_week: number;
  this_month: number;
  totals: { delivery_earning: number; tips: number; incentives: number; total: number };
  available_balance: number;
  total_withdrawn: number;
  processing_payouts: number;
  min_payout_amount: number;
}

export interface AdminRiderDetail extends AdminRiderRow {
  date_of_birth: string | null;
  national_id: string | null;
  documents: Record<string, string>;
  payout: Record<string, string | null>;
  delivered_orders: number;
  cancelled_orders: number;
  earnings: RiderEarnings;
}

export interface RiderEarningsDay {
  date: string;
  orders: number;
  delivery_earning: number;
  tips: number;
  incentives: number;
  total: number;
}

export interface AdminRiderPayoutRow {
  id: string;
  rider_id: string;
  reference: string;
  amount: number;
  method: string;
  account_number: string;
  account_name: string;
  bank_name: string | null;
  branch_name: string | null;
  status: "PROCESSING" | "COMPLETED" | "FAILED";
  failure_reason: string | null;
  requested_at: string;
  processed_at: string | null;
  rider_name: string | null;
  rider_avatar_url: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;
}

export interface LiveRider {
  id: string;
  full_name: string | null;
  phone: string | null;
  avatar_url: string | null;
  vehicle_type: string | null;
  status: "AVAILABLE" | "HEADING_TO_PICKUP" | "DELIVERING";
  latitude: number | null;
  longitude: number | null;
  location_updated_at: string | null;
  has_live_location: boolean;
  orders: {
    order_id: string;
    order_number: number;
    status: string;
    customer_name: string | null;
    restaurant_name: string;
    distance_to_dropoff_km: number | null;
  }[];
}

export interface RiderApplication {
  id: string;
  application_no: string;
  full_name: string;
  email: string;
  phone: string;
  vehicle_type: string;
  license_number: string | null;
  date_of_birth: string;
  national_id: string;
  documents: Record<string, string>;
  payout: Record<string, string | null>;
  status: "PENDING" | "APPROVED" | "REJECTED";
  review_note: string | null;
  reviewed_at: string | null;
  rider_id: string | null;
  submitted_at: string;
}

export interface RiderUpdate {
  is_online?: boolean;
  is_verified?: boolean;
  password?: string;
  full_name?: string;
  vehicle_type?: string;
  license_number?: string;
  date_of_birth?: string;
  national_id?: string;
  documents?: Record<string, string>;
}

export function useRiders(query: Query, enabled = true) {
  return useQuery({
    queryKey: ["riders", query],
    queryFn: ({ signal }) => apiPage<AdminRiderRow>("/admin/riders", query, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useRider(id: string | undefined) {
  return useQuery({
    queryKey: ["rider", id],
    queryFn: ({ signal }) => get<AdminRiderDetail>(`/admin/riders/${id}`, undefined, signal),
    enabled: !!id,
  });
}

export function useRiderEarnings(id: string, query: Query) {
  return useQuery({
    queryKey: ["rider-earnings", id, query],
    queryFn: async ({ signal }) => {
      // The endpoint pages `days` but wraps them with a summary, so read meta by hand.
      const res = await apiPage<never>(`/admin/riders/${id}/earnings`, query, signal);
      const data = res.items as unknown as { summary: RiderEarnings; days: RiderEarningsDay[] };
      return { ...data, meta: res.meta };
    },
    placeholderData: keepPreviousData,
  });
}

export function useRiderPayouts(query: Query) {
  return useQuery({
    queryKey: ["rider-payouts", query],
    queryFn: ({ signal }) => apiPage<AdminRiderPayoutRow>("/admin/rider-payouts", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useLiveRiders(status: string) {
  return useQuery({
    queryKey: ["riders-live", status],
    queryFn: ({ signal }) => get<LiveRider[]>("/admin/riders/live", status ? { status } : undefined, signal),
    refetchInterval: 12_000,
    placeholderData: keepPreviousData,
  });
}

export function useRiderApplications(query: Query) {
  return useQuery({
    queryKey: ["rider-applications", query],
    queryFn: ({ signal }) => apiPage<RiderApplication>("/admin/rider-applications", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useRiderApplication(id: string | undefined) {
  return useQuery({
    queryKey: ["rider-application", id],
    queryFn: ({ signal }) => get<RiderApplication>(`/admin/rider-applications/${id}`, undefined, signal),
    enabled: !!id,
  });
}

function useRiderMutation<V, R = unknown>(fn: (vars: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      for (const key of ["riders", "rider", "rider-payouts", "rider-earnings", "rider-applications", "rider-application", "dashboard"]) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}

export const useUpdateRider = () =>
  useRiderMutation(({ id, body }: { id: string; body: RiderUpdate }) => patch<AdminRiderDetail>(`/admin/riders/${id}`, body));

export const useGrantIncentive = () =>
  useRiderMutation(({ id, amount, reason }: { id: string; amount: number; reason: string }) =>
    post(`/admin/riders/${id}/incentives`, { amount, reason }),
  );

export const useRiderPayoutAction = () =>
  useRiderMutation(
    ({ id, action, reason }: { id: string; action: "complete" | "fail" | "reopen"; reason?: string }) =>
      post(`/admin/rider-payouts/${id}/${action}`, action === "complete" ? {} : { reason: reason || null }),
  );

export const useApproveRiderApplication = () =>
  useRiderMutation(({ id, password, note }: { id: string; password?: string; note?: string }) =>
    post(`/admin/rider-applications/${id}/approve`, { password: password || undefined, note: note || undefined }),
  );

export const useRejectRiderApplication = () =>
  useRiderMutation(({ id, note }: { id: string; note: string }) => post(`/admin/rider-applications/${id}/reject`, { note }));
