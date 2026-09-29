/* Customers, and blocking any customer or rider account (app/schemas/admin/accounts.py). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, get, patch, type Query } from "@/lib/api";

export interface AdminCustomerRow {
  id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  avatar_url: string | null;
  order_count: number;
  total_spent: number;
  is_active: boolean;
  created_at: string;
}

export interface AdminCustomerDetail extends AdminCustomerRow {
  default_address: string | null;
  last_login_at: string | null;
  stats: {
    total_orders: number;
    delivered_orders: number;
    cancelled_orders: number;
    total_spent: number;
    average_order: number;
  };
}

export function useCustomers(query: Query) {
  return useQuery({
    queryKey: ["customers", query],
    queryFn: ({ signal }) => apiPage<AdminCustomerRow>("/admin/customers", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useCustomer(id: string | undefined) {
  return useQuery({
    queryKey: ["customer", id],
    queryFn: ({ signal }) => get<AdminCustomerDetail>(`/admin/customers/${id}`, undefined, signal),
    enabled: !!id,
  });
}

/** Block or unblock a customer or rider. Vendors are suspended instead (409 here). */
export function useSetAccountActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      patch<{ message: string; sessions_revoked: number }>(`/admin/users/${id}/status`, { is_active: isActive }),
    onSettled: () => {
      for (const key of ["customers", "customer", "riders", "rider", "community-posts"]) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
    },
  });
}
