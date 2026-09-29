import { useState } from "react";
import { useNavigate } from "react-router";
import { Plus } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useRiders, type AdminRiderRow } from "@/api/riders";
import { ListCard, PageHeader } from "@/components/layout/Page";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Identity, Rating } from "@/components/ui/Display";
import { InlineError } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, PasswordInput, SearchInput, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Overlay";
import { Pagination } from "@/components/ui/Pagination";
import { DataTable, type Column } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";
import { opt, post } from "@/lib/api";
import { count } from "@/lib/format";
import { useListParams, useSearchParam } from "@/lib/hooks";
import { VEHICLE_TYPES, vehicleLabel } from "@/lib/vocab";

import { RATING_OPTIONS } from "../vendors/VendorsPage";

export const VEHICLE_OPTIONS = VEHICLE_TYPES.map((v) => ({ value: v, label: vehicleLabel(v) }));

export function riderState(r: { is_active: boolean; is_verified: boolean }) {
  if (!r.is_active) return { label: "Blocked", tone: "red" as const };
  if (!r.is_verified) return { label: "Suspended", tone: "orange" as const };
  return { label: "Active", tone: "green" as const };
}

const columns: Column<AdminRiderRow>[] = [
  {
    key: "rider",
    header: "Rider",
    cell: (r) => {
      const state = riderState(r);
      return (
        <Identity
          src={r.avatar_url}
          name={r.full_name ?? r.phone}
          sub={state.label !== "Active" ? <span className={state.tone === "red" ? "text-red-500" : "text-orange-500"}>{state.label}</span> : r.email}
        />
      );
    },
  },
  {
    key: "live",
    header: "Live Status",
    cell: (r) => <StatusBadge label={r.live_status === "ONLINE" ? "Online" : "Offline"} tone={r.live_status === "ONLINE" ? "green" : "orange"} />,
  },
  { key: "phone", header: "Phone Number", cell: (r) => r.phone ?? "—" },
  { key: "vehicle", header: "Vehicle Type", cell: (r) => vehicleLabel(r.vehicle_type) },
  { key: "in", header: "In Hand", cell: (r) => (r.orders_in_flight ? <Badge tone="blue">{r.orders_in_flight}</Badge> : <span className="text-gray-400">0</span>) },
  { key: "deliveries", header: "Deliveries", cell: (r) => count(r.total_deliveries) },
  { key: "rating", header: "Rating", cell: (r) => (r.rating_count ? <Rating value={r.rating_avg} /> : <span className="text-xs text-gray-400">No ratings</span>) },
];

/** Enrol a rider directly, without an application. */
function AddRiderDialog({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "", vehicle_type: "BIKE", license_number: "", is_online: false });
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () =>
      post<{ id: string; full_name: string }>("/admin/riders", {
        full_name: form.full_name.trim(),
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        password: form.password || null,
        vehicle_type: form.vehicle_type,
        license_number: form.license_number.trim() || null,
        is_online: form.is_online,
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["riders"] });
      toast(`${r.full_name} enrolled`);
      onClose();
      navigate(`/riders/${r.id}`);
    },
  });
  const set = (k: keyof typeof form, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));
  return (
    <Modal
      open
      onClose={onClose}
      title="Add rider"
      description="Enrols a rider directly, cleared to ride. Riders who apply from the app come through Rider → Application instead."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!form.full_name.trim() || (!form.email.trim() && !form.phone.trim())}>
            Add rider
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Full name">{(id) => <Input id={id} value={form.full_name} onChange={(e) => set("full_name", e.target.value)} autoFocus />}</Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Email">{(id) => <Input id={id} type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />}</Field>
          <Field label="Phone">{(id) => <Input id={id} value={form.phone} onChange={(e) => set("phone", e.target.value)} />}</Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Vehicle">
            {(id) => <Select id={id} look="filled" options={VEHICLE_OPTIONS} value={form.vehicle_type} onChange={(e) => set("vehicle_type", e.target.value)} />}
          </Field>
          <Field label="License number">{(id) => <Input id={id} value={form.license_number} onChange={(e) => set("license_number", e.target.value)} />}</Field>
        </div>
        <Field label="Password" hint="Optional. Without one the rider cannot sign in until you set it on their profile.">
          {(id) => <PasswordInput id={id} value={form.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" minLength={8} />}
        </Field>
        <Checkbox checked={form.is_online} onChange={(v) => set("is_online", v)} label="Start on shift" />
        <InlineError error={create.error} />
      </div>
    </Modal>
  );
}

export function RidersPage() {
  const navigate = useNavigate();
  const list = useListParams(["q", "vehicle_type", "min_rating", "status", "online"] as const);
  const { values: v } = list;
  const [search, setSearch] = useSearchParam(v.q, (q) => list.set({ q }));
  const [adding, setAdding] = useState(false);
  const riders = useRiders({
    q: opt(v.q),
    vehicle_type: opt(v.vehicle_type),
    min_rating: opt(v.min_rating),
    status: opt(v.status),
    online_only: v.online === "true" ? true : undefined,
    limit: list.limit,
    offset: list.offset,
  });

  return (
    <>
      <PageHeader
        title="Active Rider"
        subtitle={riders.data ? `${count(riders.data.meta.total)} rider${riders.data.meta.total === 1 ? "" : "s"}` : " "}
        actions={
          <Button size="sm" className="h-10 rounded-full px-4" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
            Add Rider
          </Button>
        }
      />
      <ListCard
        toolbar={
          <>
            <SearchInput value={search} onChange={setSearch} placeholder="Search name, phone or email..." />
            <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
              <Select
                aria-label="Shift"
                options={[
                  { value: "", label: "On & off shift" },
                  { value: "true", label: "On shift" },
                ]}
                value={v.online}
                onChange={(e) => list.set({ online: e.target.value })}
              />
              <Select aria-label="Vehicle" placeholder="Vehicle" options={VEHICLE_OPTIONS} value={v.vehicle_type} onChange={(e) => list.set({ vehicle_type: e.target.value })} />
              <Select aria-label="Rating" placeholder="Rating" options={RATING_OPTIONS} value={v.min_rating} onChange={(e) => list.set({ min_rating: e.target.value })} />
              <Select
                aria-label="Status"
                placeholder="All Status"
                options={[
                  { value: "ACTIVE", label: "Active" },
                  { value: "SUSPENDED", label: "Suspended" },
                  { value: "BLOCKED", label: "Blocked" },
                ]}
                value={v.status}
                onChange={(e) => list.set({ status: e.target.value })}
              />
            </div>
          </>
        }
      >
        <DataTable
          columns={columns}
          rows={riders.data?.items}
          rowKey={(r) => r.id}
          loading={riders.isPending}
          error={riders.error}
          onRetry={() => riders.refetch()}
          onRowClick={(r) => navigate(`/riders/${r.id}`)}
          empty="No riders match."
        />
        <Pagination meta={riders.data?.meta} onPage={(p) => list.set({ page: String(p) })} />
      </ListCard>
      {adding && <AddRiderDialog onClose={() => setAdding(false)} />}
    </>
  );
}
