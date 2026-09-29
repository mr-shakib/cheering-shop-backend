/* Community moderation, reels and app banners (app/schemas/community.py,
 * app/schemas/content.py). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, del, patch, post, type Query } from "@/lib/api";

export interface ModeratedPost {
  id: string;
  author: { id: string; full_name: string | null; avatar_url: string | null };
  body: string;
  image_urls: string[];
  restaurant: { id: string; name: string } | null;
  created_at: string;
  report_count: number;
  author_is_active: boolean;
  is_removed: boolean;
  removed_at: string | null;
  removal_reason: string | null;
}

export interface Reel {
  id: string;
  restaurant_id: string;
  restaurant_name: string;
  video_url: string;
  thumbnail_url: string | null;
  caption: string | null;
  duration_seconds: number | null;
  menu_item_id: string | null;
  menu_item_name: string | null;
  is_hidden: boolean;
  hidden_reason: string | null;
  uploaded_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Banner {
  id: string;
  title: string;
  media_url: string;
  media_type: "IMAGE" | "GIF" | "LOTTIE";
  placement: string;
  action_type: "NONE" | "RESTAURANT" | "CATEGORY" | "URL";
  action_value: string | null;
  sort_order: number;
  is_active: boolean;
  starts_at: string | null;
  ends_at: string | null;
  status: "LIVE" | "SCHEDULED" | "EXPIRED" | "INACTIVE";
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export type BannerWrite = Partial<Omit<Banner, "id" | "status" | "created_by" | "created_at" | "updated_at">>;

export function usePosts(query: Query) {
  return useQuery({
    queryKey: ["community-posts", query],
    queryFn: ({ signal }) => apiPage<ModeratedPost>("/admin/community/posts", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useRemovePost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => post(`/admin/community/posts/${id}/remove`, { reason }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["community-posts"] }),
  });
}

export function useReels(query: Query) {
  return useQuery({
    queryKey: ["reels", query],
    queryFn: ({ signal }) => apiPage<Reel>("/admin/reels", query, signal),
    placeholderData: keepPreviousData,
  });
}

function useContentMutation<V, R = unknown>(key: string, fn: (vars: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: [key] }) });
}

export const useCreateReel = () =>
  useContentMutation(
    "reels",
    (body: { restaurant_id: string; video_url: string; thumbnail_url?: string | null; caption?: string | null; duration_seconds?: number | null; menu_item_id?: string | null }) =>
      post<Reel>("/admin/reels", body),
  );

export const useUpdateReel = () =>
  useContentMutation("reels", ({ id, body }: { id: string; body: Partial<Pick<Reel, "caption" | "thumbnail_url" | "menu_item_id" | "is_hidden" | "hidden_reason">> }) =>
    patch<Reel>(`/admin/reels/${id}`, body),
  );

export const useDeleteReel = () => useContentMutation("reels", (id: string) => del(`/admin/reels/${id}`));

export function useBanners(query: Query) {
  return useQuery({
    queryKey: ["banners", query],
    queryFn: ({ signal }) => apiPage<Banner>("/admin/banners", query, signal),
    placeholderData: keepPreviousData,
  });
}

export const useCreateBanner = () => useContentMutation("banners", (body: BannerWrite) => post<Banner>("/admin/banners", body));

export const useUpdateBanner = () =>
  useContentMutation("banners", ({ id, body }: { id: string; body: BannerWrite }) => patch<Banner>(`/admin/banners/${id}`, body));

export const useDeleteBanner = () => useContentMutation("banners", (id: string) => del(`/admin/banners/${id}`));
