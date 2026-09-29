/* Vendors: active list, profile tabs, add/edit, applications, withdrawals
 * (app/schemas/admin/vendors.py, app/schemas/vendor/applications.py). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, get, patch, post, type Query } from "@/lib/api";

export interface AdminVendorRow {
  id: string;
  name: string;
  logo_url: string | null;
  business_type: string | null;
  phone: string | null;
  order_count: number;
  revenue: number;
  rating_avg: number;
  rating_count: number;
  product_count: number;
  status: "OPEN" | "CLOSED";
  is_verified: boolean;
  is_active: boolean;
  created_at: string;
}

export interface DayHours {
  is_open: boolean;
  opens_at: string | null;
  closes_at: string | null;
}
export const WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Weekday = (typeof WEEK)[number];
export type BusinessHours = Record<Weekday, DayHours>;

export interface VendorPayout {
  method: "BANK" | "BKASH" | "NAGAD" | "ROCKET";
  account_name: string;
  account_number: string;
  bank_name?: string | null;
  branch_name?: string | null;
}

export interface AdminVendorDetail extends AdminVendorRow {
  slug: string;
  description: string | null;
  cover_image_url: string | null;
  cuisine_types: string[];
  business_category: string | null;
  address_line: string | null;
  latitude: number;
  longitude: number;
  owner: { id: string; full_name: string | null; email: string | null; phone: string | null; national_id: string | null };
  business_hours: Partial<BusinessHours> | null;
  avg_prep_time_mins: number;
  min_order_amount: number;
  delivery_fee_base: number;
  commission_rate: number;
  application_id: string | null;
  application_no: string | null;
  onboarding_source: "APPLICATION" | "ADMIN" | null;
  area: string | null;
  documents: Record<string, string>;
  payout: Partial<VendorPayout>;
}

export interface VendorReview {
  id: string;
  order_id: string;
  order_number: number | null;
  restaurant_rating: number;
  comment: string | null;
  customer_name: string | null;
  created_at: string;
}

export interface VendorReviews {
  summary: { restaurant_id: string; rating_avg: number; rating_count: number; histogram: Record<string, number> };
  reviews: VendorReview[];
}

export interface VendorFinance {
  restaurant_id: string;
  total_earning: number;
  total_commission: number;
  total_payout: number;
  pending_amount: number;
  available_balance: number;
}

export interface AdminPayoutRow {
  id: string;
  restaurant_id: string;
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
  restaurant_name: string;
  reopened_at: string | null;
  reopen_reason: string | null;
}

export interface VendorApplication {
  id: string;
  application_no: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  user_id: string;
  restaurant_id: string;
  business_name: string;
  business_type: string;
  business_category: string;
  branch_count: number;
  cuisine_types: string[];
  address_line: string;
  area: string | null;
  latitude: number;
  longitude: number;
  owner_full_name: string;
  owner_email: string;
  owner_phone: string;
  national_id: string | null;
  documents: Record<string, string>;
  payout: Partial<VendorPayout>;
  source: "APPLICATION" | "ADMIN";
  review_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PendingRestaurant {
  id: string;
  name: string;
  slug: string;
  status: string;
  is_verified: boolean;
  latitude: number;
  longitude: number;
  address_line: string | null;
  cuisine_types: string[];
}

/** Every field POST/PATCH /admin/vendors takes. */
export interface VendorWrite {
  name?: string;
  description?: string | null;
  phone?: string | null;
  address_line?: string;
  area?: string | null;
  latitude?: number;
  longitude?: number;
  cuisine_types?: string[];
  logo_url?: string | null;
  cover_image_url?: string | null;
  min_order_amount?: number | null;
  avg_prep_time_mins?: number | null;
  business_hours?: BusinessHours;
  status?: "OPEN" | "CLOSED";
  is_verified?: boolean;
  is_active?: boolean;
  commission_rate?: number | null;
  business_type?: string;
  business_category?: string;
  branch_count?: number;
  national_id?: string | null;
  documents?: Record<string, string | null>;
  payout?: VendorPayout | null;
  owner_full_name?: string;
  owner_email?: string;
  owner_phone?: string;
  owner_password?: string;
}

export function useVendors(query: Query) {
  return useQuery({
    queryKey: ["vendors", query],
    queryFn: ({ signal }) => apiPage<AdminVendorRow>("/admin/vendors", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useVendor(id: string | undefined) {
  return useQuery({
    queryKey: ["vendor", id],
    queryFn: ({ signal }) => get<AdminVendorDetail>(`/admin/vendors/${id}`, undefined, signal),
    enabled: !!id,
  });
}

export function useVendorReviews(id: string, query: Query) {
  return useQuery({
    queryKey: ["vendor-reviews", id, query],
    queryFn: async ({ signal }) => {
      const res = await apiPage<never>(`/admin/vendors/${id}/reviews`, query, signal);
      return { ...(res.items as unknown as VendorReviews), meta: res.meta };
    },
    placeholderData: keepPreviousData,
  });
}

export function useVendorFinance(id: string) {
  return useQuery({
    queryKey: ["vendor-finance", id],
    queryFn: ({ signal }) => get<VendorFinance>(`/admin/vendors/${id}/finance`, undefined, signal),
  });
}

export function usePayouts(query: Query) {
  return useQuery({
    queryKey: ["payouts", query],
    queryFn: ({ signal }) => apiPage<AdminPayoutRow>("/admin/payouts", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useVendorApplications(query: Query) {
  return useQuery({
    queryKey: ["vendor-applications", query],
    queryFn: ({ signal }) => apiPage<VendorApplication>("/admin/vendor-applications", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useVendorApplication(id: string | undefined) {
  return useQuery({
    queryKey: ["vendor-application", id],
    queryFn: ({ signal }) => get<VendorApplication>(`/admin/vendor-applications/${id}`, undefined, signal),
    enabled: !!id,
  });
}

export function usePendingRestaurants(query: Query) {
  return useQuery({
    queryKey: ["pending-restaurants", query],
    queryFn: ({ signal }) => apiPage<PendingRestaurant>("/admin/restaurants/pending", query, signal),
    placeholderData: keepPreviousData,
  });
}

const VENDOR_KEYS = [
  "vendors",
  "vendor",
  "vendor-finance",
  "payouts",
  "vendor-applications",
  "vendor-application",
  "pending-restaurants",
  "dashboard",
  "products",
];

function useVendorMutation<V, R = unknown>(fn: (vars: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      for (const key of VENDOR_KEYS) void qc.invalidateQueries({ queryKey: [key] });
    },
  });
}

export const useCreateVendor = () => useVendorMutation((body: VendorWrite) => post<AdminVendorDetail>("/admin/vendors", body));

export const useUpdateVendor = () =>
  useVendorMutation(({ id, body }: { id: string; body: VendorWrite }) => patch<AdminVendorDetail>(`/admin/vendors/${id}`, body));

export const useVerifyRestaurant = () =>
  useVendorMutation(({ id, isVerified }: { id: string; isVerified: boolean }) =>
    post<{ message: string }>(`/admin/restaurants/${id}/verify`, { is_verified: isVerified }),
  );

export const useSetVendorCommission = () =>
  useVendorMutation(({ id, rate }: { id: string; rate: number }) =>
    patch<{ message: string }>(`/admin/restaurants/${id}/commission`, { commission_rate: rate }),
  );

export const useDecideApplication = () =>
  useVendorMutation(({ id, decision, note }: { id: string; decision: "approve" | "reject"; note?: string }) =>
    post<{ message: string }>(`/admin/vendor-applications/${id}/${decision}`, { note: note || null }),
  );

export const usePayoutAction = () =>
  useVendorMutation(({ id, action, reason }: { id: string; action: "complete" | "fail" | "reopen"; reason?: string }) =>
    post(`/admin/payouts/${id}/${action}`, action === "complete" ? {} : { reason: reason || null }),
  );
