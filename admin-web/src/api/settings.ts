/* Platform settings and administrator invitations (docs/ADMIN-API.md §17–18). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, get, patch, post } from "@/lib/api";

export interface Surcharge {
  amount: number;
  active: boolean;
}

export interface PlatformSettings {
  app_name: string;
  support_email: string | null;
  support_phone: string | null;
  delivery_base_fee: number;
  delivery_per_km_fee: number;
  delivery_min_fee: number;
  delivery_free_km: number;
  restaurant_commission_rate: number;
  grocery_commission_rate: number;
  pharmacy_commission_rate: number;
  rain_surcharge: Surcharge;
  heatwave_fee: Surcharge;
  high_demand_fee: Surcharge;
  active_surcharge_total: number;
  using_server_defaults: string[];
  updated_at: string;
  updated_by: string | null;
}

export type SettingsPatch = Partial<{
  app_name: string | null;
  support_email: string | null;
  support_phone: string | null;
  delivery_base_fee: number | null;
  delivery_per_km_fee: number | null;
  delivery_min_fee: number | null;
  restaurant_commission_rate: number | null;
  grocery_commission_rate: number | null;
  pharmacy_commission_rate: number | null;
  rain_surcharge: Partial<Surcharge>;
  heatwave_fee: Partial<Surcharge>;
  high_demand_fee: Partial<Surcharge>;
}>;

export interface AdminInvitation {
  id: string;
  email: string;
  full_name: string | null;
  status: "PENDING" | "ACCEPTED" | "EXPIRED" | "REVOKED";
  invited_by: string | null;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
  debug_token: string | null;
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: ({ signal }) => get<PlatformSettings>("/admin/settings", undefined, signal) });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SettingsPatch) => patch<PlatformSettings>("/admin/settings", body),
    onSuccess: (s) => qc.setQueryData(["settings"], s),
  });
}

export function useInvitations() {
  return useQuery({
    queryKey: ["invitations"],
    queryFn: async ({ signal }) => (await apiPage<AdminInvitation>("/admin/invitations", { limit: 50 }, signal)).items,
  });
}

export function useInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; full_name?: string }) => post<AdminInvitation>("/admin/invitations", body),
    onSettled: () => qc.invalidateQueries({ queryKey: ["invitations"] }),
  });
}

export function useRevokeInvitation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => post<AdminInvitation>(`/admin/invitations/${id}/revoke`),
    onSettled: () => qc.invalidateQueries({ queryKey: ["invitations"] }),
  });
}
