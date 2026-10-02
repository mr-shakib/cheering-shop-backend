/* Orders (app/schemas/admin/orders.py). */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiPage, get, post, type Query } from "@/lib/api";

export interface AdminOrderRow {
  id: string;
  order_number: number;
  status: string;
  payment_method: string;
  payment_status: string;
  customer_id: string;
  customer_name: string | null;
  restaurant_id: string;
  restaurant_name: string;
  business_type: string | null;
  rider_id: string | null;
  rider_name: string | null;
  delivery_type: "STANDARD" | "PRIORITY";
  grand_total: number;
  commission_amount: number;
  placed_at: string;
  delivered_at: string | null;
  cancelled_at: string | null;
}

export interface OrderItem {
  id: string;
  menu_item_id: string | null;
  item_name: string;
  variant_name: string | null;
  quantity: number;
  unit_price: number;
  add_ons_total: number;
  line_total: number;
  notes: string | null;
  add_ons: { name: string; price: number; quantity?: number }[];
}

export interface AdminOrderDetail extends AdminOrderRow {
  timeline: { status: string; at: string; actor: string; note: string | null }[];
  customer: {
    id: string;
    full_name: string | null;
    email: string | null;
    phone: string | null;
    delivery_contact_phone: string | null;
    delivery_address_text: string;
    delivery_latitude: number;
    delivery_longitude: number;
  };
  vendor: {
    id: string;
    name: string;
    phone: string | null;
    logo_url: string | null;
    address_line: string | null;
    business_type: string | null;
  };
  rider: {
    id: string;
    full_name: string | null;
    phone: string | null;
    vehicle_type: string | null;
    rating_avg: number | null;
  } | null;
  rider_location: {
    latitude: number;
    longitude: number;
    updated_at: string | null;
    distance_to_dropoff_km: number;
  } | null;
  money: {
    item_total: number;
    delivery_fee: number;
    priority_fee: number;
    packaging_fee: number;
    tax_amount: number;
    platform_fee: number;
    tip: number;
    discount: number;
    grand_total: number;
    commission_amount: number;
    vendor_payout: number;
  };
  payment: {
    method: string;
    status: string;
    reference: string | null;
    refunded_at: string | null;
    refunded_by: string | null;
    refund_reason: string | null;
  };
  items: OrderItem[];
  special_instructions: string | null;
  scheduled_for: string | null;
  estimated_delivery_at: string | null;
  cancelled_by: string | null;
  cancellation_reason: string | null;
  actions: {
    can_assign_rider: boolean;
    can_cancel: boolean;
    can_refund: boolean;
    can_force_deliver: boolean;
  };
}

export function useOrders(query: Query, enabled = true) {
  return useQuery({
    queryKey: ["orders", query],
    queryFn: ({ signal }) => apiPage<AdminOrderRow>("/admin/orders", query, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useOrder(id: string | null) {
  return useQuery({
    queryKey: ["order", id],
    queryFn: ({ signal }) => get<AdminOrderDetail>(`/admin/orders/${id}`, undefined, signal),
    enabled: !!id,
    // The drawer shows live rider distance; keep it fresh while open.
    refetchInterval: 15_000,
  });
}

/** Every mutation on an order refreshes the lists, the drawer and the dashboard. */
function useOrderMutation<V, R = unknown>(fn: (vars: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["order"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useCancelOrder() {
  return useOrderMutation(({ id, reason }: { id: string; reason: string }) =>
    post(`/admin/orders/${id}/cancel`, { reason }),
  );
}

export function useRefundOrder() {
  return useOrderMutation(({ id, reason }: { id: string; reason: string }) =>
    post(`/admin/orders/${id}/refund`, { reason }),
  );
}

export function useAssignRider() {
  return useOrderMutation(({ id, riderId }: { id: string; riderId: string | null }) =>
    post<{ message: string; chosen_by: string }>(`/admin/orders/${id}/assign-rider`, riderId ? { rider_id: riderId } : {}),
  );
}

export function useForceDeliver() {
  return useOrderMutation(({ id }: { id: string }) => post(`/admin/orders/${id}/deliver`));
}
