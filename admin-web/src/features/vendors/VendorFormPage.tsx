/* Add Vendor and Edit Vendor. Add is one call that creates the owner's
 * account, the store and its partner record; Edit sends only what changed
 * (PATCH semantics, docs/ADMIN-API.md §5). */
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router";

import {
  WEEK,
  useCreateVendor,
  useUpdateVendor,
  useVendor,
  type AdminVendorDetail,
  type BusinessHours,
  type VendorPayout,
  type VendorWrite,
} from "@/api/vendors";
import { LocationPicker } from "@/components/map/Map";
import { PageHeader } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, PasswordInput, Select, TextArea } from "@/components/ui/Field";
import { FileDrop } from "@/components/ui/Inputs";
import { useToast } from "@/components/ui/Toast";
import { ACCEPT } from "@/lib/upload";

import { percentFromRate, rateFromPercent } from "../products/ProductEditors";
import { BUSINESS_TYPE_OPTIONS } from "./VendorsPage";

const DOC_KINDS = [
  { kind: "shop_image", label: "Shop image", accept: ACCEPT.image },
  { kind: "owner_nid", label: "Owner NID", accept: ACCEPT.document },
  { kind: "trade_license", label: "Trade license", accept: ACCEPT.document },
  { kind: "menu_list", label: "Menu list", accept: ACCEPT.document },
] as const;

const DAY_LABEL: Record<string, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

interface Form {
  name: string;
  description: string;
  phone: string;
  address_line: string;
  area: string;
  latitude: number | null;
  longitude: number | null;
  cuisine: string;
  logo_url: string | null;
  cover_image_url: string | null;
  min_order_amount: string;
  avg_prep_time_mins: string;
  status: "OPEN" | "CLOSED";
  is_verified: boolean;
  business_type: string;
  business_category: string;
  branch_count: string;
  commission: string;
  national_id: string;
  owner_full_name: string;
  owner_email: string;
  owner_phone: string;
  owner_password: string;
  documents: Record<string, string | null>;
  payout_method: string;
  account_name: string;
  account_number: string;
  bank_name: string;
  branch_name: string;
  hours: BusinessHours;
}

const defaultHours = (): BusinessHours =>
  Object.fromEntries(WEEK.map((d) => [d, { is_open: true, opens_at: "10:00", closes_at: "22:00" }])) as BusinessHours;

function blank(): Form {
  return {
    name: "",
    description: "",
    phone: "",
    address_line: "",
    area: "",
    latitude: null,
    longitude: null,
    cuisine: "",
    logo_url: null,
    cover_image_url: null,
    min_order_amount: "",
    avg_prep_time_mins: "",
    status: "CLOSED",
    is_verified: true,
    business_type: "RESTAURANT",
    business_category: "",
    branch_count: "1",
    commission: "",
    national_id: "",
    owner_full_name: "",
    owner_email: "",
    owner_phone: "",
    owner_password: "",
    documents: {},
    payout_method: "",
    account_name: "",
    account_number: "",
    bank_name: "",
    branch_name: "",
    hours: defaultHours(),
  };
}

function fromVendor(v: AdminVendorDetail): Form {
  const hours = defaultHours();
  for (const d of WEEK) {
    const h = v.business_hours?.[d];
    if (h) hours[d] = { is_open: h.is_open, opens_at: h.opens_at, closes_at: h.closes_at };
  }
  return {
    name: v.name,
    description: v.description ?? "",
    phone: v.phone ?? "",
    address_line: v.address_line ?? "",
    area: v.area ?? "",
    latitude: v.latitude,
    longitude: v.longitude,
    cuisine: v.cuisine_types.join(", "),
    logo_url: v.logo_url,
    cover_image_url: v.cover_image_url,
    min_order_amount: String(v.min_order_amount ?? ""),
    avg_prep_time_mins: String(v.avg_prep_time_mins ?? ""),
    status: v.status,
    is_verified: v.is_verified,
    business_type: v.business_type ?? "RESTAURANT",
    business_category: v.business_category ?? "",
    branch_count: "1",
    commission: percentFromRate(v.commission_rate),
    national_id: v.owner.national_id ?? "",
    owner_full_name: v.owner.full_name ?? "",
    owner_email: v.owner.email ?? "",
    owner_phone: v.owner.phone ?? "",
    owner_password: "",
    documents: { ...v.documents },
    payout_method: v.payout.method ?? "",
    account_name: v.payout.account_name ?? "",
    account_number: v.payout.account_number ?? "",
    bank_name: v.payout.bank_name ?? "",
    branch_name: v.payout.branch_name ?? "",
    hours,
  };
}

const num = (s: string, what: string): number | null => {
  if (!s.trim()) return null;
  const n = Number(s);
  if (!Number.isFinite(n) || n < 0) throw new Error(`${what} must be a positive number.`);
  return n;
};

function payoutOf(f: Form): VendorPayout | null {
  if (!f.payout_method) return null;
  if (f.account_name.trim().length < 2 || f.account_number.trim().length < 4) {
    throw new Error("A payout account needs the account name and number.");
  }
  return {
    method: f.payout_method as VendorPayout["method"],
    account_name: f.account_name.trim(),
    account_number: f.account_number.trim(),
    bank_name: f.bank_name.trim() || null,
    branch_name: f.branch_name.trim() || null,
  };
}

/** Everything the create call takes. */
function createBody(f: Form): VendorWrite {
  if (f.name.trim().length < 2) throw new Error("Enter the store name.");
  if (f.address_line.trim().length < 5) throw new Error("Enter the store address.");
  if (f.latitude === null || f.longitude === null) throw new Error("Place the store on the map: it decides which customers can see it.");
  if (f.owner_full_name.trim().length < 2) throw new Error("Enter the owner's name.");
  if (!f.owner_email.trim()) throw new Error("Enter the owner's email.");
  if (f.owner_phone.trim().length < 6) throw new Error("Enter the owner's phone.");
  const documents = Object.fromEntries(Object.entries(f.documents).filter(([, url]) => url)) as Record<string, string>;
  return {
    name: f.name.trim(),
    description: f.description.trim() || undefined,
    phone: f.phone.trim() || undefined,
    address_line: f.address_line.trim(),
    area: f.area.trim() || undefined,
    latitude: f.latitude,
    longitude: f.longitude,
    cuisine_types: f.cuisine.split(",").map((c) => c.trim()).filter(Boolean),
    logo_url: f.logo_url ?? undefined,
    cover_image_url: f.cover_image_url ?? undefined,
    min_order_amount: num(f.min_order_amount, "Minimum order") ?? undefined,
    avg_prep_time_mins: num(f.avg_prep_time_mins, "Preparation time") ?? undefined,
    status: f.status,
    is_verified: f.is_verified,
    business_type: f.business_type,
    business_category: f.business_category.trim() || undefined,
    branch_count: num(f.branch_count, "Branches") ?? undefined,
    commission_rate: rateFromPercent(f.commission) ?? undefined,
    national_id: f.national_id.trim() || undefined,
    owner_full_name: f.owner_full_name.trim(),
    owner_email: f.owner_email.trim(),
    owner_phone: f.owner_phone.trim(),
    owner_password: f.owner_password || undefined,
    documents,
    payout: payoutOf(f) ?? undefined,
  };
}

/** Only the fields that differ from what was loaded. */
function patchBody(f: Form, was: Form): VendorWrite {
  const body: VendorWrite = {};
  const text = (k: keyof Form & keyof VendorWrite, nullable = false) => {
    const now = String(f[k] ?? "").trim();
    if (now !== String(was[k] ?? "").trim()) (body as Record<string, unknown>)[k] = now || (nullable ? null : undefined);
  };
  text("name");
  text("description", true);
  text("phone", true);
  text("address_line");
  text("area", true);
  text("business_category");
  text("national_id");
  text("owner_full_name");
  text("owner_email");
  text("owner_phone");
  if (f.latitude !== was.latitude || f.longitude !== was.longitude) {
    body.latitude = f.latitude!;
    body.longitude = f.longitude!;
  }
  if (f.cuisine !== was.cuisine) body.cuisine_types = f.cuisine.split(",").map((c) => c.trim()).filter(Boolean);
  if (f.logo_url !== was.logo_url) body.logo_url = f.logo_url;
  if (f.cover_image_url !== was.cover_image_url) body.cover_image_url = f.cover_image_url;
  if (f.min_order_amount !== was.min_order_amount) body.min_order_amount = num(f.min_order_amount, "Minimum order");
  if (f.avg_prep_time_mins !== was.avg_prep_time_mins) body.avg_prep_time_mins = num(f.avg_prep_time_mins, "Preparation time");
  if (f.status !== was.status) body.status = f.status;
  if (f.business_type !== was.business_type) body.business_type = f.business_type;
  if (f.commission !== was.commission) {
    const rate = rateFromPercent(f.commission);
    if (rate === null) throw new Error("A vendor always has a commission rate; enter one.");
    body.commission_rate = rate;
  }
  if (f.owner_password) body.owner_password = f.owner_password;
  const docs: Record<string, string | null> = {};
  for (const { kind } of DOC_KINDS) {
    if ((f.documents[kind] ?? null) !== (was.documents[kind] ?? null)) docs[kind] = f.documents[kind] ?? null;
  }
  if (Object.keys(docs).length) body.documents = docs;
  const payoutKeys = ["payout_method", "account_name", "account_number", "bank_name", "branch_name"] as const;
  if (payoutKeys.some((k) => f[k] !== was[k])) {
    const payout = payoutOf(f);
    if (payout) body.payout = payout;
  }
  if (JSON.stringify(f.hours) !== JSON.stringify(was.hours)) {
    for (const d of WEEK) {
      const h = f.hours[d];
      if (h.is_open && (!h.opens_at || !h.closes_at)) throw new Error(`${DAY_LABEL[d]} is open, so it needs both times.`);
    }
    body.business_hours = Object.fromEntries(
      WEEK.map((d) => [d, f.hours[d].is_open ? f.hours[d] : { is_open: false, opens_at: null, closes_at: null }]),
    ) as BusinessHours;
  }
  return body;
}

function Section({ title, hint, children, className }: { title: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <Card className={className ?? "p-5"}>
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-gray-500">{hint}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </Card>
  );
}

export function VendorFormPage() {
  const { id } = useParams();
  const editing = !!id;
  const vendor = useVendor(id);
  const create = useCreateVendor();
  const update = useUpdateVendor();
  const navigate = useNavigate();
  const toast = useToast();
  const initial = useMemo(() => (vendor.data ? fromVendor(vendor.data) : blank()), [vendor.data]);
  const [form, setForm] = useState<Form>(initial);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => setForm(initial), [initial]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const busy = create.isPending || update.isPending;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      if (editing) {
        const body = patchBody(form, initial);
        if (!Object.keys(body).length) {
          toast("Nothing has changed.", "info");
          return;
        }
        await update.mutateAsync({ id: id!, body });
        toast("Vendor saved");
        navigate(`/vendors/${id}`);
      } else {
        const created = await create.mutateAsync(createBody(form));
        toast(`${created.name} added`);
        navigate(`/vendors/${created.id}`);
      }
    } catch (err) {
      setError(err);
      window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    }
  };

  if (editing && vendor.isPending) return <PageSpinner />;
  if (editing && vendor.isError) {
    return (
      <>
        <PageHeader title="Edit Vendor" back={{ to: "/vendors", label: "Back to vendors" }} />
        <Card>
          <ErrorState error={vendor.error} onRetry={() => vendor.refetch()} />
        </Card>
      </>
    );
  }

  const input = (k: keyof Form, props: Record<string, unknown> = {}) => (id: string) => (
    <Input id={id} value={String(form[k] ?? "")} onChange={(e) => set(k, e.target.value as never)} {...props} />
  );

  return (
    <form onSubmit={submit}>
      <PageHeader
        title={editing ? `Edit ${vendor.data?.name ?? "Vendor"}` : "Add Vendor"}
        subtitle={editing ? "Only the fields you change are saved." : "Creates the owner's account, the store and its partner record."}
        back={editing ? { to: `/vendors/${id}`, label: "Back to vendor" } : { to: "/vendors", label: "Back to vendors" }}
      />
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="space-y-5">
          <Section title="Store">
            <Field label="Store name *">{input("name", { maxLength: 180, autoFocus: !editing })}</Field>
            <Field label="Description">
              {(id) => <TextArea id={id} value={form.description} onChange={(e) => set("description", e.target.value)} maxLength={2000} className="min-h-20" />}
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Store phone" hint="Defaults to the owner's phone">{input("phone", { maxLength: 20 })}</Field>
              <Field label="Cuisine types" hint="Comma separated, e.g. Burger, Fast food">{input("cuisine")}</Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Minimum order (৳)">{input("min_order_amount", { type: "number", min: 0 })}</Field>
              <Field label="Prep time (min)">{input("avg_prep_time_mins", { type: "number", min: 1, max: 240 })}</Field>
              <Field label="Store status">
                {(id) => (
                  <Select
                    id={id}
                    look="filled"
                    options={[
                      { value: "CLOSED", label: "Closed" },
                      { value: "OPEN", label: "Open" },
                    ]}
                    value={form.status}
                    onChange={(e) => set("status", e.target.value as Form["status"])}
                  />
                )}
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Logo">{() => <FileDrop value={form.logo_url} onChange={(u) => set("logo_url", u)} accept={ACCEPT.image} label="Add logo" />}</Field>
              <Field label="Cover image">
                {() => <FileDrop value={form.cover_image_url} onChange={(u) => set("cover_image_url", u)} accept={ACCEPT.image} label="Add cover" />}
              </Field>
            </div>
          </Section>

          <Section title="Location" hint="Customers within delivery range of this pin can see the store. Click the map or drag the pin.">
            <Field label="Address *">{input("address_line", { maxLength: 500 })}</Field>
            <Field label="Area">{input("area", { maxLength: 120, placeholder: "e.g. Gulshan" })}</Field>
            <LocationPicker
              lat={form.latitude}
              lng={form.longitude}
              onChange={(lat, lng) => setForm((f) => ({ ...f, latitude: lat, longitude: lng }))}
            />
            <p className="text-xs text-gray-500">
              {form.latitude !== null ? `Pinned at ${form.latitude}, ${form.longitude}` : "No pin yet — the store cannot be saved without one."}
            </p>
          </Section>

          {editing && (
            <Section title="Business hours">
              <div className="space-y-2">
                {WEEK.map((d) => {
                  const h = form.hours[d];
                  const setDay = (patch: Partial<typeof h>) => set("hours", { ...form.hours, [d]: { ...h, ...patch } });
                  return (
                    <div key={d} className="flex flex-wrap items-center gap-3">
                      <span className="w-24 text-sm text-gray-700">{DAY_LABEL[d]}</span>
                      <Checkbox checked={h.is_open} onChange={(v) => setDay({ is_open: v, opens_at: h.opens_at ?? "10:00", closes_at: h.closes_at ?? "22:00" })} label="Open" />
                      {h.is_open ? (
                        <>
                          <input type="time" aria-label={`${DAY_LABEL[d]} opens`} value={h.opens_at ?? ""} onChange={(e) => setDay({ opens_at: e.target.value })} className="h-9 rounded-lg border border-gray-200 px-2 text-sm" />
                          <span className="text-gray-400">–</span>
                          <input type="time" aria-label={`${DAY_LABEL[d]} closes`} value={h.closes_at ?? ""} onChange={(e) => setDay({ closes_at: e.target.value })} className="h-9 rounded-lg border border-gray-200 px-2 text-sm" />
                        </>
                      ) : (
                        <span className="text-sm text-gray-400">Closed</span>
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-gray-500">A closing time earlier than the opening time runs past midnight.</p>
            </Section>
          )}
        </div>

        <div className="space-y-5">
          <Section title="Owner" hint={editing ? "The account the vendor app signs in with." : "A new account is created for the owner."}>
            <Field label="Full name *">{input("owner_full_name", { maxLength: 150 })}</Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Email *">{input("owner_email", { type: "email", maxLength: 254 })}</Field>
              <Field label="Phone *">{input("owner_phone", { maxLength: 20 })}</Field>
            </div>
            <Field
              label={editing ? "New password" : "Password"}
              hint={editing ? "Leave empty to keep the current one." : "Optional. Without one, the owner is emailed how to set it."}
            >
              {(id) => (
                <PasswordInput id={id} value={form.owner_password} onChange={(e) => set("owner_password", e.target.value)} autoComplete="new-password" minLength={8} />
              )}
            </Field>
            <Field label="National ID / Passport">{input("national_id", { maxLength: 50 })}</Field>
          </Section>

          <Section title="Business">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Business type" hint={editing ? undefined : "Sets the default commission"}>
                {(id) => <Select id={id} look="filled" options={BUSINESS_TYPE_OPTIONS} value={form.business_type} onChange={(e) => set("business_type", e.target.value)} />}
              </Field>
              <Field label="Business category">{input("business_category", { maxLength: 80, placeholder: "e.g. Street food" })}</Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Commission (%)" hint={editing ? "Applies to new orders" : "Empty: the Settings rate for the type"}>
                {input("commission", { type: "number", min: 0, max: 100, step: "0.5" })}
              </Field>
              {!editing && <Field label="Branches">{input("branch_count", { type: "number", min: 1, max: 50 })}</Field>}
            </div>
            {!editing && (
              <Checkbox
                checked={form.is_verified}
                onChange={(v) => set("is_verified", v)}
                label="Approve now (customers can find it once it opens). Untick to put it in the application queue."
              />
            )}
          </Section>

          <Section title="Documents">
            <div className="grid gap-4 sm:grid-cols-2">
              {DOC_KINDS.map((d) => (
                <Field key={d.kind} label={d.label}>
                  {() => (
                    <FileDrop
                      kind="file"
                      value={form.documents[d.kind] ?? null}
                      onChange={(u) => set("documents", { ...form.documents, [d.kind]: u })}
                      accept={d.accept}
                      label="Upload"
                    />
                  )}
                </Field>
              ))}
            </div>
          </Section>

          <Section title="Payout account">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Method">
                {(id) => (
                  <Select
                    id={id}
                    look="filled"
                    placeholder="None"
                    options={[
                      { value: "BKASH", label: "bKash" },
                      { value: "NAGAD", label: "Nagad" },
                      { value: "ROCKET", label: "Rocket" },
                      { value: "BANK", label: "Bank account" },
                    ]}
                    value={form.payout_method}
                    onChange={(e) => set("payout_method", e.target.value)}
                  />
                )}
              </Field>
              <Field label="Account name">{input("account_name", { maxLength: 150, disabled: !form.payout_method })}</Field>
              <Field label="Account number">{input("account_number", { maxLength: 50, disabled: !form.payout_method })}</Field>
              {form.payout_method === "BANK" && (
                <>
                  <Field label="Bank name">{input("bank_name", { maxLength: 150 })}</Field>
                  <Field label="Branch name">{input("branch_name", { maxLength: 150 })}</Field>
                </>
              )}
            </div>
          </Section>
        </div>
      </div>

      <div className="sticky bottom-0 z-10 mt-6 -mb-6 flex flex-wrap items-center justify-end gap-3 border-t border-line bg-page/95 py-4 backdrop-blur sm:-mb-7">
        <div className="mr-auto min-w-0 flex-1">
          <InlineError error={error} />
        </div>
        <Button variant="outline" onClick={() => navigate(editing ? `/vendors/${id}` : "/vendors")} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" loading={busy} className="px-8">
          {editing ? "Save Changes" : "Add Vendor"}
        </Button>
      </div>
    </form>
  );
}
