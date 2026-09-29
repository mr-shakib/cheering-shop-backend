import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { Copy, LogOut, Mail, RotateCcw, UserPlus } from "lucide-react";

import { changePassword, signOut } from "@/api/auth";
import {
  useInvitations,
  useInvite,
  useRevokeInvitation,
  useSaveSettings,
  useSettings,
  type PlatformSettings,
  type SettingsPatch,
} from "@/api/settings";
import { PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Field, Input, PasswordInput, Switch } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { BASENAME } from "@/lib/basename";
import { dateOnly, money } from "@/lib/format";
import { useSession } from "@/lib/session";
import { invitationStatus } from "@/lib/vocab";

import { percentFromRate, rateFromPercent } from "../products/ProductEditors";

type Surcharges = "rain_surcharge" | "heatwave_fee" | "high_demand_fee";

interface Form {
  app_name: string;
  support_email: string;
  support_phone: string;
  delivery_base_fee: string;
  delivery_per_km_fee: string;
  delivery_min_fee: string;
  restaurant_commission_rate: string;
  grocery_commission_rate: string;
  pharmacy_commission_rate: string;
  rain_surcharge: { amount: string; active: boolean };
  heatwave_fee: { amount: string; active: boolean };
  high_demand_fee: { amount: string; active: boolean };
}

const formOf = (s: PlatformSettings): Form => ({
  app_name: s.app_name,
  support_email: s.support_email ?? "",
  support_phone: s.support_phone ?? "",
  delivery_base_fee: String(s.delivery_base_fee),
  delivery_per_km_fee: String(s.delivery_per_km_fee),
  delivery_min_fee: String(s.delivery_min_fee),
  restaurant_commission_rate: percentFromRate(s.restaurant_commission_rate),
  grocery_commission_rate: percentFromRate(s.grocery_commission_rate),
  pharmacy_commission_rate: percentFromRate(s.pharmacy_commission_rate),
  rain_surcharge: { amount: String(s.rain_surcharge.amount), active: s.rain_surcharge.active },
  heatwave_fee: { amount: String(s.heatwave_fee.amount), active: s.heatwave_fee.active },
  high_demand_fee: { amount: String(s.high_demand_fee.amount), active: s.high_demand_fee.active },
});

const taka = (v: string, label: string) => {
  const n = Number(v);
  if (!v.trim() || !Number.isFinite(n) || n < 0) throw new Error(`${label} must be a positive amount.`);
  return n;
};

/** Only what changed, in the API's units. */
function diff(f: Form, was: Form, keys: (keyof Form)[]): SettingsPatch {
  const out: Record<string, unknown> = {};
  for (const k of keys) {
    if (JSON.stringify(f[k]) === JSON.stringify(was[k])) continue;
    if (k === "rain_surcharge" || k === "heatwave_fee" || k === "high_demand_fee") {
      out[k] = { amount: taka(f[k].amount, "A surcharge"), active: f[k].active };
    } else if (k.endsWith("_rate")) {
      const rate = rateFromPercent(f[k] as string);
      if (rate === null) throw new Error("Enter every commission rate.");
      out[k] = rate;
    } else if (k.startsWith("delivery_")) {
      out[k] = taka(f[k] as string, "A delivery fee");
    } else {
      out[k] = (f[k] as string).trim() || null;
    }
  }
  return out as SettingsPatch;
}

function SettingsCard({
  title,
  hint,
  keys,
  form,
  initial,
  children,
}: {
  title: string;
  hint?: ReactNode;
  keys: (keyof Form)[];
  form: Form;
  initial: Form;
  children: ReactNode;
}) {
  const save = useSaveSettings();
  const toast = useToast();
  const [error, setError] = useState<unknown>(null);
  const dirty = keys.some((k) => JSON.stringify(form[k]) !== JSON.stringify(initial[k]));
  return (
    <Card className="p-5">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-gray-500">{hint}</p>}
      <div className="mt-4 space-y-4">{children}</div>
      {dirty && (
        <div className="mt-5 flex items-center justify-end gap-3 border-t border-line pt-4">
          <div className="mr-auto">
            <InlineError error={error} />
          </div>
          <Button
            size="sm"
            loading={save.isPending}
            onClick={async () => {
              setError(null);
              try {
                await save.mutateAsync(diff(form, initial, keys));
                toast(`${title} saved`);
              } catch (e) {
                setError(e);
              }
            }}
          >
            Save changes
          </Button>
        </div>
      )}
    </Card>
  );
}

function InvitationsCard() {
  const invitations = useInvitations();
  const invite = useInvite();
  const revoke = useRevokeInvitation();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  const inviteLink = (token: string) => `${window.location.origin}${BASENAME}/accept-invite?token=${token}`;

  return (
    <Card className="p-5">
      <h2 className="text-base font-semibold text-gray-900">Administrators</h2>
      <p className="mt-0.5 text-xs text-gray-500">Invite someone by email. The link works once and expires after 72 hours.</p>
      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          invite.mutate(
            { email: email.trim(), full_name: name.trim() || undefined },
            {
              onSuccess: () => {
                toast(`Invitation sent to ${email.trim()}`);
                setEmail("");
                setName("");
              },
            },
          );
        }}
      >
        <Field label="Email" className="min-w-52 flex-1">
          {(id) => <Input id={id} type="email" look="outline" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="name@company.com" />}
        </Field>
        <Field label="Name (optional)" className="min-w-40 flex-1">
          {(id) => <Input id={id} look="outline" value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Button type="submit" size="sm" className="h-10" icon={<UserPlus className="size-4" />} loading={invite.isPending}>
          Send invitation
        </Button>
      </form>
      <div className="mt-2">
        <InlineError error={invite.error} />
      </div>
      <ul className="mt-4 divide-y divide-line">
        {invitations.isPending ? (
          <li className="py-3 text-sm text-gray-500">Loading…</li>
        ) : invitations.isError ? (
          <li className="py-3 text-sm text-red-600">Could not load invitations.</li>
        ) : invitations.data.length === 0 ? (
          <li className="py-3 text-sm text-gray-500">No invitations sent yet.</li>
        ) : (
          invitations.data.map((inv) => (
            <li key={inv.id} className="flex flex-wrap items-center gap-3 py-3">
              <Mail className="size-4 text-gray-400" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-gray-900">{inv.full_name ? `${inv.full_name} · ${inv.email}` : inv.email}</span>
                <span className="block text-xs text-gray-500">
                  Sent {dateOnly(inv.created_at)}
                  {inv.status === "PENDING" && ` · expires ${dateOnly(inv.expires_at)}`}
                </span>
              </span>
              <StatusBadge {...invitationStatus(inv.status)} dot={false} />
              {inv.debug_token && inv.status === "PENDING" && (
                <Button
                  size="xs"
                  variant="ghost"
                  icon={<Copy className="size-3.5" />}
                  title="Development only: the link the email carries"
                  onClick={() => void navigator.clipboard.writeText(inviteLink(inv.debug_token!)).then(() => toast("Invitation link copied"))}
                >
                  Copy link
                </Button>
              )}
              {inv.status === "PENDING" && (
                <Button
                  size="xs"
                  variant="ghost"
                  className="text-red-600 hover:bg-red-50"
                  onClick={() =>
                    confirm({
                      title: `Revoke the invitation to ${inv.email}?`,
                      description: "The link stops working at once.",
                      confirmLabel: "Revoke",
                      tone: "danger",
                      onConfirm: () => revoke.mutateAsync(inv.id).then(() => toast("Invitation revoked")),
                    })
                  }
                >
                  Revoke
                </Button>
              )}
            </li>
          ))
        )}
      </ul>
      {dialog}
    </Card>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const toast = useToast();
  return (
    <Card className="p-5">
      <h2 className="text-base font-semibold text-gray-900">Change password</h2>
      <p className="mt-0.5 text-xs text-gray-500">Signs you out on every other device.</p>
      <form
        className="mt-4 space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await changePassword(current, next);
            setCurrent("");
            setNext("");
            toast("Password changed");
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Current password">
            {(id) => <PasswordInput id={id} look="outline" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />}
          </Field>
          <Field label="New password" hint="At least 8 characters">
            {(id) => <PasswordInput id={id} look="outline" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" minLength={8} required />}
          </Field>
        </div>
        <InlineError error={error} />
        <div className="flex justify-end">
          <Button type="submit" size="sm" loading={busy}>
            Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function SettingsPage() {
  const settings = useSettings();
  const session = useSession();
  const navigate = useNavigate();
  const [form, setForm] = useState<Form | null>(null);
  const initial = settings.data ? formOf(settings.data) : null;

  useEffect(() => {
    if (settings.data) setForm(formOf(settings.data));
  }, [settings.data]);

  if (settings.isPending) return <PageSpinner />;
  if (settings.isError) {
    return (
      <>
        <PageHeader title="Settings" />
        <Card>
          <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
        </Card>
      </>
    );
  }
  if (!form || !initial) return null;

  const s = settings.data;
  const field = (k: Exclude<keyof Form, Surcharges>, label: string, props: Record<string, unknown> = {}) => (
    <Field label={label}>
      {(id) => <Input id={id} look="outline" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} {...props} />}
    </Field>
  );
  const surcharge = (k: Surcharges, label: string) => (
    <div className="flex items-end gap-3">
      <Field label={label} className="flex-1">
        {(id) => (
          <Input id={id} look="outline" type="number" min={0} value={form[k].amount} onChange={(e) => setForm({ ...form, [k]: { ...form[k], amount: e.target.value } })} />
        )}
      </Field>
      <label className="flex h-10 items-center gap-2 text-sm text-gray-700">
        <Switch checked={form[k].active} onChange={(v) => setForm({ ...form, [k]: { ...form[k], active: v } })} label={`${label} active`} />
        {form[k].active ? "On" : "Off"}
      </label>
    </div>
  );

  return (
    <>
      <PageHeader title="Settings" subtitle="Platform configuration" />
      <div className="grid gap-5 lg:grid-cols-2">
        <SettingsCard title="General" keys={["app_name", "support_email", "support_phone"]} form={form} initial={initial}>
          {field("app_name", "App name", { maxLength: 80 })}
          {field("support_email", "Support email", { type: "email" })}
          {field("support_phone", "Support Number")}
        </SettingsCard>
        <SettingsCard
          title="Delivery settings"
          hint={`The base fee covers the first ${s.delivery_free_km} km; each started km after adds the per-km fee. Applies to the next checkout.`}
          keys={["delivery_base_fee", "delivery_per_km_fee", "delivery_min_fee"]}
          form={form}
          initial={initial}
        >
          {field("delivery_base_fee", "Base fee (৳)", { type: "number", min: 0 })}
          {field("delivery_per_km_fee", "Per KM fee (৳)", { type: "number", min: 0 })}
          {field("delivery_min_fee", "Minimum fee (৳)", { type: "number", min: 0 })}
        </SettingsCard>
        <SettingsCard
          title="Commission settings"
          hint="What a new vendor of each type starts on. Existing vendors keep their rate; change one on the vendor's page."
          keys={["restaurant_commission_rate", "grocery_commission_rate", "pharmacy_commission_rate"]}
          form={form}
          initial={initial}
        >
          {field("restaurant_commission_rate", "Food commission (%)", { type: "number", min: 0, max: 100, step: "0.5" })}
          {field("grocery_commission_rate", "Shop commission (%)", { type: "number", min: 0, max: 100, step: "0.5" })}
          {field("pharmacy_commission_rate", "Medicine commission (%)", { type: "number", min: 0, max: 100, step: "0.5" })}
        </SettingsCard>
        <SettingsCard
          title="Dynamic pricing"
          hint={`Added to every delivery fee while switched on. Right now checkout adds ${money(s.active_surcharge_total)}.`}
          keys={["rain_surcharge", "heatwave_fee", "high_demand_fee"]}
          form={form}
          initial={initial}
        >
          {surcharge("rain_surcharge", "Rain surcharge (৳)")}
          {surcharge("heatwave_fee", "Heatwave fee (৳)")}
          {surcharge("high_demand_fee", "High demand fee (৳)")}
        </SettingsCard>
        <InvitationsCard />
        <PasswordCard />
        <Card className="flex items-center justify-between gap-4 p-5 lg:col-span-2">
          <p className="text-[15px] font-medium text-gray-900">
            You are signed in as {session?.user.full_name || session?.user.email}
          </p>
          <Button
            variant="danger-soft"
            size="sm"
            className="h-10"
            icon={<LogOut className="size-4" />}
            onClick={async () => {
              await signOut();
              navigate("/login", { replace: true });
            }}
          >
            Logout
          </Button>
        </Card>
      </div>
      <p className="mt-4 flex items-center gap-1.5 text-xs text-gray-400">
        <RotateCcw className="size-3" /> Platform settings last changed {dateOnly(s.updated_at)}
      </p>
    </>
  );
}
