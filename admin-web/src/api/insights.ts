/* Overview, Finance and the top search bar (app/schemas/admin/insights.py). */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiPage, get, type Query } from "@/lib/api";

import type { AdminOrderRow } from "./orders";

export interface Kpi {
  value: number;
  previous: number;
  change_pct: number | null;
}

export interface AdminDashboard {
  revenue_today: Kpi;
  orders_today: Kpi;
  active_riders: number;
  online_vendors: number;
  pending_approvals: { total: number; vendors: number; riders: number };
  live_orders: {
    new: number;
    preparing: number;
    on_delivery: number;
    awaiting_rider: number;
    cancelled_today: number;
    avg_delivery_minutes: number | null;
  };
  support_tickets: { open: number; urgent: number };
  recent_orders: AdminOrderRow[];
  generated_at: string;
}

export type RevenueRange = "7d" | "30d" | "12m";

export interface RevenueSeries {
  range: RevenueRange;
  granularity: "day" | "month";
  total_gmv: number;
  points: { period_start: string; label: string; gmv: number; orders: number }[];
}

export interface FinanceSummary {
  days: number;
  gmv: Kpi;
  net_revenue: Kpi;
  commission_revenue: Kpi;
  delivery_revenue: Kpi;
  revenue_by_service: { business_type: string; gmv: number; share_pct: number }[];
}

export interface FinanceTransaction {
  order_id: string;
  order_number: number;
  payment_reference: string | null;
  payment_method: string;
  payment_status: string;
  restaurant_id: string;
  restaurant_name: string;
  customer_id: string;
  customer_name: string | null;
  amount: number;
  commission_amount: number;
  delivered_at: string;
}

export interface SearchHit {
  id: string;
  title: string;
  subtitle: string | null;
}

export interface AdminSearchResults {
  query: string;
  orders: SearchHit[];
  customers: SearchHit[];
  vendors: SearchHit[];
  riders: SearchHit[];
}

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => get<AdminDashboard>("/admin/dashboard", undefined, signal),
    refetchInterval: 30_000,
  });
}

export function useRevenue(range: RevenueRange) {
  return useQuery({
    queryKey: ["revenue", range],
    queryFn: ({ signal }) => get<RevenueSeries>("/admin/analytics/revenue", { range }, signal),
    placeholderData: keepPreviousData,
  });
}

export function useFinanceSummary(days: number) {
  return useQuery({
    queryKey: ["finance-summary", days],
    queryFn: ({ signal }) => get<FinanceSummary>("/admin/finance/summary", { days }, signal),
    placeholderData: keepPreviousData,
  });
}

export function useTransactions(query: Query) {
  return useQuery({
    queryKey: ["transactions", query],
    queryFn: ({ signal }) => apiPage<FinanceTransaction>("/admin/finance/transactions", query, signal),
    placeholderData: keepPreviousData,
  });
}

export function useSearch(q: string) {
  return useQuery({
    queryKey: ["search", q],
    queryFn: ({ signal }) => get<AdminSearchResults>("/admin/search", { q }, signal),
    enabled: q.trim().length >= 2,
    staleTime: 10_000,
  });
}
