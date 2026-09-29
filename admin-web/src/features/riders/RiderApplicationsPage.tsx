import { useNavigate } from "react-router";
import { Eye } from "lucide-react";

import { useRiderApplications, type RiderApplication } from "@/api/riders";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Identity } from "@/components/ui/Display";
import { SearchInput, Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { opt } from "@/lib/api";
import { count, dateTime } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";
import { applicationStatus, vehicleLabel } from "@/lib/vocab";

import { VEHICLE_OPTIONS } from "./RidersPage";

const columns: Column<RiderApplication>[] = [
  { key: "name", header: "Full Name", cell: (a) => <Identity src={a.documents.profile_photo} name={a.full_name} sub={a.application_no} /> },
  { key: "email", header: "Email", cell: (a) => <span className="text-gray-600">{a.email}</span> },
  { key: "phone", header: "Phone Number", cell: (a) => a.phone },
  { key: "vehicle", header: "Vehicle Type", cell: (a) => vehicleLabel(a.vehicle_type) },
  { key: "status", header: "Status", cell: (a) => <StatusBadge {...applicationStatus(a.status)} dot={false} /> },
  { key: "date", header: "Submitted Date", cell: (a) => <span className="whitespace-nowrap text-gray-600">{dateTime(a.submitted_at)}</span> },
  { key: "action", header: "Action", align: "center", cell: () => <Eye className="mx-auto size-5 text-gray-600" /> },
];

export function RiderApplicationsPage() {
  const navigate = useNavigate();
  const list = useListParams(["q", "status", "vehicle_type"] as const, { status: "PENDING" });
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const apps = useRiderApplications({
    q: opt(v.q),
    status: v.status === "ALL" ? "" : v.status,
    vehicle_type: opt(v.vehicle_type),
    limit: list.limit,
    offset: list.offset,
  });
  const total = apps.data?.meta.total;
  const label = { PENDING: "pending ", APPROVED: "approved ", REJECTED: "rejected ", ALL: "" }[v.status] ?? "";

  return (
    <>
      <PageHeader title="Rider Application" subtitle={total !== undefined ? `${count(total)} ${label}application${total === 1 ? "" : "s"}` : " "} />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search name, phone, email or number..." />
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
              <Select aria-label="Vehicle" placeholder="All Vehicles" options={VEHICLE_OPTIONS} value={v.vehicle_type} onChange={(e) => list.set({ vehicle_type: e.target.value })} />
            </div>
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={apps.data?.items}
          rowKey={(a) => a.id}
          loading={apps.isPending}
          error={apps.error}
          onRetry={() => apps.refetch()}
          onRowClick={(a) => navigate(`/rider-applications/${a.id}`)}
          empty={v.status === "PENDING" ? "No rider applications are waiting." : "No applications match."}
        />
        <Pagination meta={apps.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
    </>
  );
}
