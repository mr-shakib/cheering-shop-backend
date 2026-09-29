/* Products and browse categories (app/schemas/admin/products.py,
 * app/schemas/categories.py). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, del, get, patch, post, type Query } from "@/lib/api";

export interface CategoryRef {
  id: string;
  name: string;
  slug: string;
  image_url: string | null;
}

export interface ProductCommission {
  rate: number;
  source: "PRODUCT" | "CATEGORY" | "RESTAURANT";
  product_rate: number | null;
  category_rate: number | null;
  restaurant_rate: number;
}

export interface AdminProductRow {
  id: string;
  name: string;
  image_url: string | null;
  restaurant_id: string;
  restaurant_name: string;
  business_type: string | null;
  section_id: string;
  section_name: string;
  platform_category: CategoryRef | null;
  base_price: number;
  status: "ACTIVE" | "HIDDEN" | "UNAVAILABLE";
  is_available: boolean;
  is_hidden: boolean;
  is_featured: boolean;
  commission: ProductCommission;
  created_at: string;
}

export interface Variant {
  id?: string;
  name: string;
  price: number;
  is_default: boolean;
  is_available: boolean;
  sort_order: number;
}

export interface AddOn {
  id?: string;
  name: string;
  price: number;
  is_available: boolean;
  sort_order: number;
  max_quantity: number;
}

export interface AdminProductDetail extends AdminProductRow {
  description: string | null;
  is_veg: boolean;
  prep_time_mins: number | null;
  variants: Variant[];
  add_ons: AddOn[];
  commission_amount: number;
  net_amount: number;
}

export interface ProductWrite {
  name?: string;
  description?: string | null;
  image_url?: string | null;
  base_price?: number;
  is_available?: boolean;
  is_veg?: boolean;
  prep_time_mins?: number | null;
  variants?: Variant[];
  add_ons?: AddOn[];
  commission_rate?: number | null;
  is_hidden?: boolean;
  is_featured?: boolean;
  platform_category_id?: string;
  category_id?: string;
}

export interface AdminCategory extends CategoryRef {
  sort_order: number | null;
  aliases: string[];
  is_active: boolean;
  reviewed_at: string | null;
  is_pending: boolean;
  restaurant_count: number;
  section_count: number;
  product_count: number;
  commission_rate: number | null;
  kind: "RESTAURANT" | "STORE";
  created_at: string;
  updated_at: string;
}

export interface CategoryWrite {
  name?: string;
  image_url?: string | null;
  sort_order?: number | null;
  aliases?: string[];
  is_active?: boolean;
  commission_rate?: number | null;
  kind?: "RESTAURANT" | "STORE";
}

export function useProducts(query: Query, enabled = true) {
  return useQuery({
    queryKey: ["products", query],
    queryFn: ({ signal }) => apiPage<AdminProductRow>("/admin/products", query, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useProduct(id: string | null) {
  return useQuery({
    queryKey: ["product", id],
    queryFn: ({ signal }) => get<AdminProductDetail>(`/admin/products/${id}`, undefined, signal),
    enabled: !!id,
  });
}

export function useCategories(query: Query, enabled = true) {
  return useQuery({
    queryKey: ["categories", query],
    queryFn: ({ signal }) => apiPage<AdminCategory>("/admin/categories", query, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

function useCatalogMutation<V, R = unknown>(fn: (vars: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      for (const key of ["products", "product", "categories", "vendor", "vendors"]) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}

export const useUpdateProduct = () =>
  useCatalogMutation(({ id, body }: { id: string; body: ProductWrite }) => patch<AdminProductDetail>(`/admin/products/${id}`, body));

export const useDeleteProduct = () => useCatalogMutation((id: string) => del(`/admin/products/${id}`));

export const useCreateProduct = () =>
  useCatalogMutation(({ vendorId, body }: { vendorId: string; body: ProductWrite & { name: string; base_price: number } }) =>
    post<AdminProductDetail>(`/admin/vendors/${vendorId}/products`, body),
  );

export const useCreateCategory = () =>
  useCatalogMutation((body: CategoryWrite & { name: string }) => post<AdminCategory>("/admin/categories", body));

export const useUpdateCategory = () =>
  useCatalogMutation(({ id, body }: { id: string; body: CategoryWrite }) => patch<AdminCategory>(`/admin/categories/${id}`, body));

export const useDeleteCategory = () => useCatalogMutation((id: string) => del(`/admin/categories/${id}`));

export const useMergeCategory = () =>
  useCatalogMutation(({ id, intoId }: { id: string; intoId: string }) => post(`/admin/categories/${id}/merge`, { into_id: intoId }));
