import type { AdminVendorDetail, BusinessHours, DayHours } from "@/api/vendors";
import { WEEK } from "@/api/vendors";
import { DocumentCard, InfoList } from "@/components/ui/Display";
import { money, pct } from "@/lib/format";
import { businessTypeLabel, documentLabel, paymentMethod } from "@/lib/vocab";

const DAY_NAMES: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

function to12h(t: string | null | undefined) {
  if (!t) return "—";
  const [h, m] = t.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  return `${String(h % 12 || 12).padStart(2, "0")}:${String(m).padStart(2, "0")} ${suffix}`;
}

/** One opening and closing time when every open day agrees; otherwise per day. */
export function hoursRows(hours: Partial<BusinessHours> | null) {
  if (!hours || !Object.keys(hours).length) return [{ label: "Business hours", value: "Not set" }];
  const days = WEEK.map((d) => [d, hours[d]] as [string, DayHours | undefined]);
  const open = days.filter(([, h]) => h?.is_open);
  if (!open.length) return [{ label: "Business hours", value: "Closed every day" }];
  const same = open.every(([, h]) => h!.opens_at === open[0][1]!.opens_at && h!.closes_at === open[0][1]!.closes_at);
  if (same) {
    const closedDays = days.filter(([, h]) => !h?.is_open).map(([d]) => DAY_NAMES[d]);
    return [
      { label: "Opening Time", value: to12h(open[0][1]!.opens_at) },
      { label: "Closing Time", value: to12h(open[0][1]!.closes_at) },
      ...(closedDays.length ? [{ label: "Closed on", value: closedDays.join(", ") }] : []),
    ];
  }
  return days.map(([d, h]) => ({
    label: DAY_NAMES[d],
    value: h?.is_open ? `${to12h(h.opens_at)} – ${to12h(h.closes_at)}` : "Closed",
  }));
}

export function VendorStoreInfo({ v }: { v: AdminVendorDetail }) {
  const docs = Object.entries(v.documents);
  const payout = v.payout;
  return (
    <div className="space-y-6">
      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-line p-5">
          <h3 className="mb-5 text-lg font-medium text-gray-900">Store Information</h3>
          <InfoList
            rows={[
              { label: "Owner name", value: v.owner.full_name },
              { label: "Email", value: v.owner.email },
              { label: "Phone", value: v.phone || v.owner.phone },
              { label: "Store Address", value: [v.address_line, v.area].filter(Boolean).join(", ") },
              { label: "Business Type", value: v.business_type ? businessTypeLabel(v.business_type) : null },
              { label: "Business Category", value: v.business_category },
              { label: "Cuisine Type", value: v.cuisine_types.join(", ") },
              { label: "National ID/ Passport", value: v.owner.national_id },
              { label: "Application", value: v.application_no ? `${v.application_no}${v.onboarding_source === "ADMIN" ? " (added by an admin)" : ""}` : "Registered without a partner application" },
            ]}
          />
        </section>
        <div className="space-y-5">
          <section className="rounded-xl border border-line p-5">
            <h3 className="mb-5 text-lg font-medium text-gray-900">Business Information</h3>
            <InfoList
              labelWidth="sm:w-44"
              rows={[
                ...hoursRows(v.business_hours),
                { label: "Preparation Time", value: `${v.avg_prep_time_mins} Min` },
                { label: "Minimum Order", value: money(v.min_order_amount) },
                { label: "Delivery Fee", value: `${money(v.delivery_fee_base)} base` },
                { label: "Commission", value: pct(v.commission_rate) },
              ]}
            />
          </section>
          <section className="rounded-xl border border-line p-5">
            <h3 className="mb-5 text-lg font-medium text-gray-900">Payout Account</h3>
            {payout.method ? (
              <InfoList
                labelWidth="sm:w-44"
                rows={[
                  { label: "Method", value: paymentMethod(payout.method) },
                  { label: "Account name", value: payout.account_name },
                  { label: "Account number", value: payout.account_number },
                  { label: "Bank", value: payout.bank_name, hidden: !payout.bank_name },
                  { label: "Branch", value: payout.branch_name, hidden: !payout.branch_name },
                ]}
              />
            ) : (
              <p className="text-sm text-gray-500">No payout account on file.</p>
            )}
          </section>
        </div>
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
          <p className="text-sm text-gray-500">No documents uploaded.</p>
        )}
      </section>
    </div>
  );
}
