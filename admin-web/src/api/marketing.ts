/* Advertisement campaigns and push notification campaigns
 * (app/schemas/admin/ads.py, app/schemas/notifications.py). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, patch, post, type Page, type PageMeta, type Query } from "@/lib/api";

export interface AdCampaign {
  id: string;
  restaurant_id: string;
  restaurant_name: string;
  campaign: string;
  code: string;
  budget: number | null;
  spent: number;
  impressions: number;
  clicks: number;
  redemptions: number;
  revenue: number;
  status: "SCHEDULED" | "ACTIVE" | "PAUSED" | "ENDED";
  valid_from: string;
  valid_until: string;
  created_at: string;
}

export interface NotificationCampaign {
  id: string;
  title: string;
  message: string;
  type: "PROMOTION" | "ALERT" | "UPDATE";
  audience: "CUSTOMER" | "VENDOR" | "RIDER" | "ALL";
  status: "SCHEDULED" | "SENT" | "FAILED" | "CANCELLED";
  scheduled_for: string;
  sent_at: string | null;
  recipient_count: number;
  push_sent_count: number;
  push_enabled: boolean;
  failure_reason: string | null;
  created_by: string | null;
  created_at: string;
}

export function useAds(query: Query) {
  return useQuery({
    queryKey: ["ads", query],
    queryFn: ({ signal }) => apiPage<AdCampaign>("/admin/advertisements", query, signal) as Promise<Page<AdCampaign> & { meta: PageMeta & { active?: number } }>,
    placeholderData: keepPreviousData,
  });
}

export function useSetAdStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: "ACTIVE" | "PAUSED" | "ENDED" }) => patch<AdCampaign>(`/admin/advertisements/${id}`, { status }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["ads"] }),
  });
}

export function useCampaigns(query: Query) {
  return useQuery({
    queryKey: ["campaigns", query],
    queryFn: ({ signal }) => apiPage<NotificationCampaign>("/admin/notifications", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useSendCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; message: string; type: string; audience: string; scheduled_for?: string }) =>
      post<NotificationCampaign>("/admin/notifications", body),
    onSettled: () => qc.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}

export function useCancelCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => post<NotificationCampaign>(`/admin/notifications/${id}/cancel`),
    onSettled: () => qc.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}
