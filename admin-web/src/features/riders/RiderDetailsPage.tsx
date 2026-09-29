import { useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { Ban, Gift, KeyRound, MoreVertical, Pencil, PhoneCall, Power, ShieldCheck } from "lucide-react";

import { useSetAccountActive } from "@/api/customers";
import { useGrantIncentive, useRider, useRiderEarnings, useRiderPayoutAction, useRiderPayouts, useUpdateRider, type AdminRiderDetail } from "@/api/riders";
import { PageHeader } from "@/components/layout/Page";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Avatar, DocumentCard, InfoList, Rating, Tile } from "@/components/ui/Display";
import { ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Field, Input, PasswordInput, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Overlay";
import { Pagination } from "@/components/ui/Pagination";
import { Popover } from "@/components/ui/Popover";
import { DataTable } from "@/components/ui/Table";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api";
import { count, dateOnly, money } from "@/lib/format";
import { PAGE_SIZE } from "@/lib/hooks";
import { documentLabel, paymentMethod, vehicleLabel } from "@/lib/vocab";

import { PayoutsTable } from "../payouts/PayoutsTable";
import { PartyOrders } from "../vendors/VendorOrdersTab";
import { VEHICLE_OPTIONS, riderState } from "./RidersPage";

type Tab = "info" | "earning" | "orders" | "withdrawal";
const TABS: { key: Tab; label: string }[] = [
  { key: "info", label: "Personal Info" },
  { key: "earning", label: "Earning" },
  { key: "orders", label: "Order" },
  { key: "withdrawal", label: "Withdrawal" },
];

function EditRiderDialog({ rider, onClose }: { rider: AdminRiderDetail; onClose: () => void }) {
  const [f, setF] = useState({
    full_name: rider.full_name ?? "",
    vehicle_type: rider.vehicle_type ?? "",
    license_number: rider.license_number ?? "",
    date_of_birth: rider.date_of_birth ?? "",
    national_id: rider.national_id ?? "",
  });
  const update = useUpdateRider();
  const toast = useToast();
  const save = () => {
    const body: Record<string, string> = {};
    if (f.full_name.trim() !== (rider.full_name ?? "")) body.full_name = f.full_name.trim();
    if (f.vehicle_type !== (rider.vehicle_type ?? "")) body.vehicle_type = f.vehicle_type;
    if (f.license_number.trim() !== (rider.license_number ?? "")) body.license_number = f.license_number.trim();
    if (f.date_of_birth !== (rider.date_of_birth ?? "")) body.date_of_birth = f.date_of_birth;
    if (f.national_id.trim() !== (rider.national_id ?? "")) body.national_id = f.national_id.trim();
    if (!Object.keys(body).length) return onClose();
    update.mutate({ id: rider.id, body }, { onSuccess: () => {
  toast("Rider saved");
  onClose();
} });
  };
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  return (
    <Modal
      open
      onClose={onClose}
      title="Edit personal info"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={update.isPending}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Full name">{(id) => <Input id={id} value={f.full_name} onChange={(e) => set("full_name", e.target.value)} />}</Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Vehicle">
            {(id) => <Select id={id} look="filled" placeholder="Not set" options={VEHICLE_OPTIONS} value={f.vehicle_type} onChange={(e) => set("vehicle_type", e.target.value)} />}
          </Field>
          <Field label="License number">{(id) => <Input id={id} value={f.license_number} onChange={(e) => set("license_number", e.target.value)} />}</Field>
          <Field label="Date of birth">{(id) => <Input id={id} type="date" value={f.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} />}</Field>
          <Field label="National ID / Passport">{(id) => <Input id={id} value={f.national_id} onChange={(e) => set("national_id", e.target.value)} />}</Field>
        </div>
        <InlineError error={update.error} />
      </div>
    </Modal>
  );
}

function PasswordDialog({ rider, onClose }: { rider: AdminRiderDetail; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const update = useUpdateRider();
  const toast = useToast();
  return (
    <Modal
      open
      onClose={onClose}
      title="Set sign-in password"
      description={`Issues or resets ${rider.full_name ?? "the rider"}'s password for the rider app. Tell them the new one yourself.`}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={password.length < 8}
            loading={update.isPending}
            onClick={() => update.mutate({ id: rider.id, body: { password } }, { onSuccess: () => {
  toast("Password set");
  onClose();
} })}
          >
            Set password
          </Button>
        </>
      }
    >
      <Field label="New password" hint="At least 8 characters">
        {(id) => <PasswordInput id={id} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" autoFocus />}
      </Field>
      <div className="mt-3">
        <InlineError error={update.error} />
      </div>
    </Modal>
  );
}

function IncentiveDialog({ rider, onClose }: { rider: AdminRiderDetail; onClose: () => void }) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const grant = useGrantIncentive();
  const toast = useToast();
  const n = Number(amount);
  return (
    <Modal
      open
      onClose={onClose}
      title="Grant an incentive"
      description="Added to the rider's balance at once. They see the reason."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!(n > 0) || reason.trim().length < 3}
            loading={grant.isPending}
            onClick={() =>
              grant.mutate({ id: rider.id, amount: n, reason: reason.trim() }, { onSuccess: () => {
  toast(`${money(n)} incentive granted`);
  onClose();
} })
            }
          >
            Grant {n > 0 ? money(n) : ""}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Amount (৳)">{(id) => <Input id={id} type="number" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} autoFocus />}</Field>
        <Field label="Reason">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Rain bonus, 12 deliveries on Friday" maxLength={255} />}</Field>
        <InlineError error={grant.error} />
      </div>
    </Modal>
  );
}

function RiderHeader({ r }: { r: AdminRiderDetail }) {
  const update = useUpdateRider();
  const setActive = useSetAccountActive();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [modal, setModal] = useState<"password" | "incentive" | null>(null);
  const state = riderState(r);
  const fail = (e: unknown) => toast(errorMessage(e), "error");

  return (
    <Card className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center">
      <Avatar src={r.avatar_url} name={r.full_name} size={80} rounded="lg" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-2xl font-semibold text-gray-900">{r.full_name ?? r.phone ?? "Rider"}</h2>
          <Badge tone={state.tone}>{state.label}</Badge>
          <Badge tone={r.live_status === "ONLINE" ? "green" : "gray"} dot>
            {r.live_status === "ONLINE" ? "On shift" : "Off shift"}
          </Badge>
        </div>
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-gray-600">
          <Rating value={r.rating_avg} className="text-sm" /> ({r.rating_count} review{r.rating_count === 1 ? "" : "s"})
          <span aria-hidden>·</span> {vehicleLabel(r.vehicle_type)}
          {r.orders_in_flight > 0 && (
            <>
              <span aria-hidden>·</span> <span className="text-blue-600">{r.orders_in_flight} order{r.orders_in_flight === 1 ? "" : "s"} in hand</span>
            </>
          )}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {r.phone && (
          <a href={`tel:${r.phone}`} className="inline-flex h-11 items-center gap-2 rounded-full border border-gray-300 px-5 text-sm font-medium text-gray-800 hover:bg-gray-50">
            <PhoneCall className="size-4" /> Call
          </a>
        )}
        {r.is_verified ? (
          <Button
            variant="danger-soft"
            size="lg"
            className="h-11"
            onClick={() =>
              confirm({
                title: `Suspend ${r.full_name ?? "this rider"}?`,
                description: "They stop receiving order offers. Orders already in their hands are not taken away. They can still sign in.",
                confirmLabel: "Suspend Rider",
                tone: "danger",
                onConfirm: () => update.mutateAsync({ id: r.id, body: { is_verified: false } }).then(() => toast("Rider suspended")),
              })
            }
          >
            Suspend Rider
          </Button>
        ) : (
          <Button
            variant="success-soft"
            size="lg"
            className="h-11"
            icon={<ShieldCheck className="size-4" />}
            loading={update.isPending}
            onClick={() => update.mutate({ id: r.id, body: { is_verified: true } }, { onSuccess: () => toast("Rider cleared to ride"), onError: fail })}
          >
            Clear to ride
          </Button>
        )}
        <Popover
          align="right"
          panelClassName="w-56 p-1.5"
          trigger={({ toggle }) => (
            <button type="button" onClick={toggle} aria-label="More actions" className="flex size-11 items-center justify-center rounded-full border border-gray-300 text-gray-700 hover:bg-gray-50">
              <MoreVertical className="size-5" />
            </button>
          )}
        >
          {(close) => (
            <div className="text-sm">
              <button type="button" className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-gray-700 hover:bg-gray-50" onClick={() => {
  close();
  setModal("incentive");
}}>
                <Gift className="size-4" /> Grant incentive
              </button>
              <button type="button" className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-gray-700 hover:bg-gray-50" onClick={() => {
  close();
  setModal("password");
}}>
                <KeyRound className="size-4" /> Set password
              </button>
              {r.is_online && (
                <button
                  type="button"
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-gray-700 hover:bg-gray-50"
                  onClick={() => {
                    close();
                    update.mutate({ id: r.id, body: { is_online: false } }, { onSuccess: () => toast("Rider taken off shift"), onError: fail });
                  }}
                >
                  <Power className="size-4" /> Take off shift
                </button>
              )}
              {r.is_active ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-red-600 hover:bg-red-50"
                  onClick={() => {
                    close();
                    confirm({
                      title: `Block ${r.full_name ?? "this rider"}'s account?`,
                      description: "They are signed out everywhere, taken off shift, and cannot sign in until you unblock them.",
                      confirmLabel: "Block account",
                      tone: "danger",
                      onConfirm: () => setActive.mutateAsync({ id: r.id, isActive: false }).then(() => toast("Rider blocked")),
                    });
                  }}
                >
                  <Ban className="size-4" /> Block account
                </button>
              ) : (
                <button
                  type="button"
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-green-700 hover:bg-green-50"
                  onClick={() => {
                    close();
                    setActive.mutate({ id: r.id, isActive: true }, { onSuccess: () => toast("Rider unblocked"), onError: fail });
                  }}
                >
                  <ShieldCheck className="size-4" /> Unblock account
                </button>
              )}
            </div>
          )}
        </Popover>
      </div>
      {dialog}
      {modal === "password" && <PasswordDialog rider={r} onClose={() => setModal(null)} />}
      {modal === "incentive" && <IncentiveDialog rider={r} onClose={() => setModal(null)} />}
    </Card>
  );
}

function PersonalInfo({ r }: { r: AdminRiderDetail }) {
  const [editing, setEditing] = useState(false);
  const docs = Object.entries(r.documents);
  return (
    <div className="space-y-6">
      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-line p-5">
          <div className="mb-5 flex items-center justify-between">
            <h3 className="text-lg font-medium text-gray-900">Personal Information</h3>
            <Button size="xs" variant="outline" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>
              Edit
            </Button>
          </div>
          <InfoList
            rows={[
              { label: "Full Name", value: r.full_name },
              { label: "Email", value: r.email },
              { label: "Phone", value: r.phone },
              { label: "Date of Birth", value: r.date_of_birth ? dateOnly(r.date_of_birth) : null },
              { label: "National ID/ Passport", value: r.national_id },
              { label: "Vehicle", value: vehicleLabel(r.vehicle_type) },
              { label: "License number", value: r.license_number },
            ]}
          />
        </section>
        <div className="space-y-5">
          <section className="rounded-xl border border-line p-5">
            <h3 className="mb-5 text-lg font-medium text-gray-900">Account Information</h3>
            <InfoList
              labelWidth="sm:w-44"
              rows={[
                { label: "Rider ID", value: <span className="font-mono text-xs">{r.id}</span> },
                { label: "Joined Date", value: dateOnly(r.created_at) },
                { label: "Delivered", value: count(r.delivered_orders) },
                { label: "Cancelled", value: count(r.cancelled_orders) },
                { label: "Rating", value: r.rating_count ? `${r.rating_avg.toFixed(1)} (${r.rating_count})` : "No ratings" },
              ]}
            />
          </section>
          <section className="rounded-xl border border-line p-5">
            <h3 className="mb-5 text-lg font-medium text-gray-900">Payout Account</h3>
            {r.payout.method ? (
              <InfoList
                labelWidth="sm:w-44"
                rows={[
                  { label: "Method", value: paymentMethod(r.payout.method) },
                  { label: "Account name", value: r.payout.account_name },
                  { label: "Account number", value: r.payout.account_number },
                  { label: "Bank", value: r.payout.bank_name, hidden: !r.payout.bank_name },
                ]}
              />
            ) : (
              <p className="text-sm text-gray-500">No payout account on file.</p>
            )}
          </section>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile label="Today's Earning" value={money(r.earnings.today)} />
        <Tile label="This Week's Earning" value={money(r.earnings.this_week)} />
        <Tile label="This Month's Earning" value={money(r.earnings.this_month)} />
        <Tile label="Total Earning" value={money(r.earnings.totals.total)} />
      </div>
      <section>
        <h3 className="mb-3 text-lg font-medium text-gray-900">Document</h3>
        {docs.length ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {docs.map(([kind, url]) => (
              <DocumentCard key={kind} label={documentLabel(kind)} url={url} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No documents on file.</p>
        )}
      </section>
      {editing && <EditRiderDialog rider={r} onClose={() => setEditing(false)} />}
    </div>
  );
}

function EarningTab({ r }: { r: AdminRiderDetail }) {
  const [page, setPage] = useState(1);
  const earnings = useRiderEarnings(r.id, { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const s = earnings.data?.summary ?? r.earnings;
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile label="Total Earning" value={money(s.totals.total)} />
        <Tile label="Delivery Earning" value={money(s.totals.delivery_earning)} />
        <Tile label="Tips" value={money(s.totals.tips)} />
        <Tile label="Incentives" value={money(s.totals.incentives)} />
      </div>
      <p className="text-sm text-gray-600">
        Available balance <span className="font-semibold text-gray-900">{money(s.available_balance)}</span> · Withdrawn{" "}
        <span className="font-semibold text-gray-900">{money(s.total_withdrawn)}</span> · Pending withdrawals{" "}
        <span className="font-semibold text-gray-900">{money(s.processing_payouts)}</span>
      </p>
      <div className="rounded-xl border border-line p-4 sm:p-5">
        <DataTable
          columns={[
            { key: "date", header: "Date", cell: (d) => dateOnly(d.date) },
            { key: "orders", header: "Order", cell: (d) => count(d.orders) },
            { key: "delivery", header: "Delivery Earning", cell: (d) => money(d.delivery_earning) },
            { key: "tips", header: "Tips", cell: (d) => money(d.tips) },
            { key: "incentives", header: "Incentives", cell: (d) => money(d.incentives) },
            { key: "total", header: "Total", cell: (d) => <span className="font-medium text-gray-900">{money(d.total)}</span> },
          ]}
          rows={earnings.data?.days}
          rowKey={(d) => d.date}
          loading={earnings.isPending}
          error={earnings.error}
          onRetry={() => earnings.refetch()}
          empty="No earnings yet."
        />
        <Pagination meta={earnings.data?.meta} onPage={setPage} />
      </div>
    </div>
  );
}

function WithdrawalTab({ riderId }: { riderId: string }) {
  const [page, setPage] = useState(1);
  const payouts = useRiderPayouts({ rider_id: riderId, status: "", limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const action = useRiderPayoutAction();
  return (
    <div className="rounded-xl border border-line p-4 sm:p-5">
      <PayoutsTable
        rows={payouts.data?.items}
        loading={payouts.isPending}
        error={payouts.error}
        onRetry={() => payouts.refetch()}
        showParty={false}
        party={{ header: "Rider", cell: (p) => p.rider_name, name: (p) => p.rider_name ?? "the rider" }}
        act={(vars) => action.mutateAsync(vars)}
      />
      <Pagination meta={payouts.data?.meta} onPage={setPage} />
    </div>
  );
}

export function RiderDetailsPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.key === params.get("tab"))?.key ?? "info") as Tab;
  const rider = useRider(id);
  const back = { to: "/riders", label: "Back to riders" };

  if (rider.isPending) return <PageSpinner />;
  if (rider.isError) {
    return (
      <>
        <PageHeader title="Rider Details" back={back} />
        <Card>
          <ErrorState error={rider.error} onRetry={() => rider.refetch()} />
        </Card>
      </>
    );
  }
  const r = rider.data;
  return (
    <>
      <PageHeader title="Rider Details" back={back} />
      <Card className="space-y-5 p-4 sm:p-5">
        <RiderHeader r={r} />
        <Card className="p-4 sm:p-5">
          <Tabs tabs={TABS} active={tab} onChange={(t) => setParams(t === "info" ? {} : { tab: t }, { replace: true })} className="mb-6" />
          {tab === "info" && <PersonalInfo r={r} />}
          {tab === "earning" && <EarningTab r={r} />}
          {tab === "orders" && <PartyOrders filter={{ rider_id: r.id }} columns={["id", "customer", "vendor", "amount", "payment", "status", "date"]} />}
          {tab === "withdrawal" && <WithdrawalTab riderId={r.id} />}
        </Card>
      </Card>
    </>
  );
}
