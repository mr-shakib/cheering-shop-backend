import { useNavigate } from "react-router";
import { BadgeCheck, Eye } from "lucide-react";

import { usePendingRestaurants, useVendorApplications, useVerifyRestaurant, type PendingRestaurant, type VendorApplication } from "@/api/vendors";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { StatusBadge, TypeBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { opt } from "@/lib/api";
import { count, dateTime } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";
import { applicationStatus } from "@/lib/vocab";

import { BUSINESS_TYPE_OPTIONS } from "./VendorsPage";

const applicationColumns: Column<VendorApplication>[] = [
  { key: "store", header: "Store Name", cell: (a) => <Identity src={a.documents.shop_image} name={a.business_name} sub={a.application_no} /> },
  { key: "owner", header: "Owner", cell: (a) => a.owner_full_name },
  { key: "phone", header: "Phone Number", cell: (a) => a.owner_phone },
  { key: "type", header: "Type", cell: (a) => <TypeBadge type={a.business_type} /> },
  { key: "status", header: "Status", cell: (a) => <StatusBadge {...applicationStatus(a.status)} dot={false} /> },
  { key: "date", header: "Submitted Date", cell: (a) => <span className="whitespace-nowrap text-gray-600">{dateTime(a.created_at)}</span> },
  { key: "action", header: "Action", align: "center", cell: () => <Eye className="mx-auto size-5 text-gray-600" /> },
];

function ApplicationsTab() {
  const navigate = useNavigate();
  const list = useListParams(["q", "status", "business_type"] as const, { status: "PENDING" });
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const apps = useVendorApplications({
    q: opt(v.q),
    status: v.status === "ALL" ? "" : v.status,
    business_type: opt(v.business_type),
    limit: list.limit,
    offset: list.offset,
  });

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SearchInput value={search} onChange={setSearch} placeholder="Search store, owner, phone or application no..." />
        <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
          <Select
            aria-label="Status"
            options={[
              { value: "PENDING", label: "Pending" },
              { value: "APPROVED", label: "Approved" },
              { value: "REJECTED", label: "Rejected" },
              { value: "ALL", label: "All Status" },
            ]}
            value={v.status}
            onChange={(e) => list.set({ status: e.target.value })}
          />
          <Select aria-label="Type" placeholder="All Type" options={BUSINESS_TYPE_OPTIONS} value={v.business_type} onChange={(e) => list.set({ business_type: e.target.value })} />
        </div>
      </div>
      <DataTable
        columns={applicationColumns}
        rows={apps.data?.items}
        rowKey={(a) => a.id}
        loading={apps.isPending}
        error={apps.error}
        onRetry={() => apps.refetch()}
        onRowClick={(a) => navigate(`/vendor-applications/${a.id}`)}
        empty={v.status === "PENDING" ? "No applications are waiting. You are all caught up." : "No applications match."}
      />
      <Pagination meta={apps.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
    </>
  );
}

/** Stores that are not live: fast-path sign-ups waiting for approval, stores
 * behind a pending application, and suspended ones. */
function UnverifiedTab() {
  const navigate = useNavigate();
  const list = useListParams([] as const);
  const stores = usePendingRestaurants({ limit: list.limit, offset: list.offset });
  const verify = useVerifyRestaurant();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();

  const columns: Column<PendingRestaurant>[] = [
    { key: "name", header: "Store Name", cell: (r) => <Identity name={r.name} rounded="lg" sub={r.slug} /> },
    { key: "address", header: "Address", cell: (r) => <span className="line-clamp-1 text-gray-600">{r.address_line ?? "—"}</span> },
    { key: "cuisine", header: "Cuisine", cell: (r) => r.cuisine_types.join(", ") || "—" },
    {
      key: "action",
      header: "Action",
      align: "center",
      cell: (r) => (
        <Button
          size="xs"
          variant="success-soft"
          className="h-8 px-3 text-sm"
          icon={<BadgeCheck className="size-4" />}
          onClick={(e) => {
            e.stopPropagation();
            confirm({
              title: `Approve ${r.name}?`,
              description:
                "Customers can find it as soon as the vendor opens it. If it has a pending partner application, review that instead so the owner is emailed.",
              confirmLabel: "Approve store",
              tone: "success",
              onConfirm: () => verify.mutateAsync({ id: r.id, isVerified: true }).then((res) => toast(res.message)),
            });
          }}
        >
          Approve
        </Button>
      ),
    },
  ];

  return (
    <>
      <p className="mb-4 text-sm text-gray-500">
        Every store customers cannot see: registered in the vendor app without a partner application, waiting on an application, or
        suspended.
      </p>
      <DataTable
        columns={columns}
        rows={stores.data?.items}
        rowKey={(r) => r.id}
        loading={stores.isPending}
        error={stores.error}
        onRetry={() => stores.refetch()}
        onRowClick={(r) => navigate(`/vendors/${r.id}`)}
        empty="Every store is approved."
      />
      <Pagination meta={stores.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      {dialog}
    </>
  );
}

export function VendorApplicationsPage() {
  const list = useListParams(["view"] as const);
  const view = list.values.view === "stores" ? "stores" : "applications";
  const pending = useVendorApplications({ status: "PENDING", limit: 1 });
  const unverified = usePendingRestaurants({ limit: 1 });

  return (
    <>
      <PageHeader
        title="Vendor Application"
        subtitle={pending.data ? `${count(pending.data.meta.total)} pending application${pending.data.meta.total === 1 ? "" : "s"}` : " "}
      />
      <ListCard>
        <Tabs
          className="mb-5"
          tabs={[
            { key: "applications", label: "Applications" },
            { key: "stores", label: `Unverified stores${unverified.data ? ` (${unverified.data.meta.total})` : ""}` },
          ]}
          active={view}
          onChange={(k) => list.set({ view: k === "stores" ? "stores" : "" })}
        />
        {view === "applications" ? <ApplicationsTab /> : <UnverifiedTab />}
      </ListCard>
    </>
  );
}
