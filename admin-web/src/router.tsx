import type { ComponentType } from "react";
import { createBrowserRouter, Link } from "react-router";

import { AppLayout } from "@/components/layout/AppLayout";
import { PageHeader } from "@/components/layout/Page";
import { Card } from "@/components/ui/Card";
import { PageSpinner } from "@/components/ui/Feedback";
import { AcceptInvitePage } from "@/features/auth/AcceptInvitePage";
import { ForgotPasswordPage } from "@/features/auth/ForgotPasswordPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { BASENAME } from "@/lib/basename";

/** Each screen is its own chunk, fetched on first visit, so the chart and map
 * libraries download only on the screens that use them. */
function page<M>(load: () => Promise<M>, name: keyof M) {
  return async () => ({ Component: (await load())[name] as ComponentType });
}

function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Card className="p-8 text-sm text-gray-600">
        There is nothing at this address.{" "}
        <Link to="/" className="font-medium text-brand-500 hover:underline">
          Back to the overview
        </Link>
      </Card>
    </>
  );
}

export const router = createBrowserRouter(
  [
    { path: "/login", element: <LoginPage /> },
    { path: "/forgot-password", element: <ForgotPasswordPage /> },
    { path: "/accept-invite", element: <AcceptInvitePage /> },
    {
      element: <AppLayout />,
      hydrateFallbackElement: <PageSpinner />,
      children: [
        { index: true, lazy: page(() => import("@/features/overview/OverviewPage"), "OverviewPage") },
        { path: "orders", lazy: page(() => import("@/features/orders/OrdersPage"), "OrdersPage") },
        { path: "customers", lazy: page(() => import("@/features/customers/CustomersPage"), "CustomersPage") },
        { path: "customers/:id", lazy: page(() => import("@/features/customers/CustomerDetailsPage"), "CustomerDetailsPage") },
        { path: "vendors", lazy: page(() => import("@/features/vendors/VendorsPage"), "VendorsPage") },
        { path: "vendors/new", lazy: page(() => import("@/features/vendors/VendorFormPage"), "VendorFormPage") },
        { path: "vendors/:id", lazy: page(() => import("@/features/vendors/VendorDetailsPage"), "VendorDetailsPage") },
        { path: "vendors/:id/edit", lazy: page(() => import("@/features/vendors/VendorFormPage"), "VendorFormPage") },
        {
          path: "vendor-applications",
          lazy: page(() => import("@/features/vendors/VendorApplicationsPage"), "VendorApplicationsPage"),
        },
        {
          path: "vendor-applications/:id",
          lazy: page(() => import("@/features/vendors/VendorApplicationDetailsPage"), "VendorApplicationDetailsPage"),
        },
        {
          path: "vendor-withdrawals",
          lazy: page(() => import("@/features/vendors/VendorWithdrawalsPage"), "VendorWithdrawalsPage"),
        },
        { path: "riders", lazy: page(() => import("@/features/riders/RidersPage"), "RidersPage") },
        { path: "riders/:id", lazy: page(() => import("@/features/riders/RiderDetailsPage"), "RiderDetailsPage") },
        {
          path: "rider-applications",
          lazy: page(() => import("@/features/riders/RiderApplicationsPage"), "RiderApplicationsPage"),
        },
        {
          path: "rider-applications/:id",
          lazy: page(() => import("@/features/riders/RiderApplicationDetailsPage"), "RiderApplicationDetailsPage"),
        },
        {
          path: "rider-withdrawals",
          lazy: page(() => import("@/features/riders/RiderWithdrawalsPage"), "RiderWithdrawalsPage"),
        },
        { path: "products", lazy: page(() => import("@/features/products/ProductsPage"), "ProductsPage") },
        { path: "categories", lazy: page(() => import("@/features/categories/CategoriesPage"), "CategoriesPage") },
        { path: "support", lazy: page(() => import("@/features/support/SupportTicketsPage"), "SupportTicketsPage") },
        { path: "live-chat", lazy: page(() => import("@/features/support/LiveChatPage"), "LiveChatPage") },
        { path: "community", lazy: page(() => import("@/features/community/CommunityPage"), "CommunityPage") },
        { path: "reels", lazy: page(() => import("@/features/community/ReelsPage"), "ReelsPage") },
        { path: "finance", lazy: page(() => import("@/features/finance/FinancePage"), "FinancePage") },
        {
          path: "advertisements",
          lazy: page(() => import("@/features/marketing/AdvertisementsPage"), "AdvertisementsPage"),
        },
        { path: "banners", lazy: page(() => import("@/features/marketing/BannersPage"), "BannersPage") },
        { path: "live-tracking", lazy: page(() => import("@/features/tracking/LiveTrackingPage"), "LiveTrackingPage") },
        {
          path: "notifications",
          lazy: page(() => import("@/features/notifications/NotificationsPage"), "NotificationsPage"),
        },
        {
          path: "notifications/new",
          lazy: page(() => import("@/features/notifications/CreateNotificationPage"), "CreateNotificationPage"),
        },
        { path: "settings", lazy: page(() => import("@/features/settings/SettingsPage"), "SettingsPage") },
        { path: "*", element: <NotFound /> },
      ],
    },
  ],
  { basename: BASENAME },
);
