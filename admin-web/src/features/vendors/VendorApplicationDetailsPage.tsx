import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Store } from "lucide-react";

import { useDecideApplication, useVendorApplication } from "@/api/vendors";
import { PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Avatar, DocumentChip, InfoList } from "@/components/ui/Display";
import { ErrorState, PageSpinner } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";
import { dateTimeLong } from "@/lib/format";
import { applicationStatus, businessTypeLabel, documentLabel, paymentMethod } from "@/lib/vocab";

export function HeaderFact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <p className="text-xs text-gray-600">{label}</p>
      <p className="mt-1 text-base text-gray-900">{value}</p>
    </div>
  );
}

export function VendorApplicationDetailsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const app = useVendorApplication(id);
  const decide = useDecideApplication();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const back = { to: "/vendor-applications", label: "Back to Application" };

  if (app.isPending) return <PageSpinner />;
  if (app.isError) {
    return (
      <>
        <PageHeader title="Application Details" back={back} />
        <Card>
          <ErrorState error={app.error} onRetry={() => app.refetch()} />
        </Card>
      </>
    );
  }
  const a = app.data;
  const shopImage = a.documents.shop_image;
  const otherDocs = Object.entries(a.documents).filter(([k]) => k !== "shop_image");

  return (
    <>
      <PageHeader title="Application Details" back={back} />
      <Card className="space-y-5 p-4 sm:p-5">
        <Card className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center">
          {shopImage ? (
            <Avatar src={shopImage} name={a.business_name} size={108} rounded="lg" />
          ) : (
            <span className="flex size-27 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-500">
              <Store className="size-10" />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <h2 className="text-2xl font-semibold text-gray-900">{a.business_name}</h2>
            <div className="mt-3 flex flex-wrap gap-x-8 gap-y-3">
              <HeaderFact label="Category" value={businessTypeLabel(a.business_type)} />
              <HeaderFact label="Application date" value={dateTimeLong(a.created_at)} />
              <HeaderFact label="Status" value={<StatusBadge {...applicationStatus(a.status)} dot={false} />} />
              <HeaderFact label="Application no" value={a.application_no} />
            </div>
          </div>
          {a.status === "PENDING" ? (
            <div className="flex shrink-0 gap-3">
              <Button
                variant="outline"
                size="lg"
                className="h-12 border-red-500 px-7 text-red-600 hover:bg-red-50"
                onClick={() =>
                  confirm({
                    title: `Reject ${a.business_name}?`,
                    description: "The note is emailed to the applicant as the reason, so write it for them.",
                    confirmLabel: "Reject application",
                    tone: "danger",
                    reason: { label: "Note to the applicant", required: true, minLength: 3, placeholder: "e.g. The trade license is unreadable. Please apply again with a clear photo." },
                    onConfirm: (note) =>
                      decide.mutateAsync({ id: a.id, decision: "reject", note }).then((r) => {
                        toast(r.message);
                        navigate("/vendor-applications");
                      }),
                  })
                }
              >
                Reject
              </Button>
              <Button
                variant="success"
                size="lg"
                className="h-12 px-9"
                onClick={() =>
                  confirm({
                    title: `Approve ${a.business_name}?`,
                    description: "The store is approved and the owner is emailed how to sign in. It stays closed until they open it.",
                    confirmLabel: "Approve",
                    tone: "success",
                    reason: { label: "Note (optional)", placeholder: "Kept with the decision" },
                    onConfirm: (note) =>
                      decide.mutateAsync({ id: a.id, decision: "approve", note }).then((r) => {
                        toast(r.message);
                        navigate(`/vendors/${a.restaurant_id}`);
                      }),
                  })
                }
              >
                Approve
              </Button>
            </div>
          ) : (
            <Link to={`/vendors/${a.restaurant_id}`}>
              <Button variant="outline">View vendor</Button>
            </Link>
          )}
        </Card>

        {a.status !== "PENDING" && (
          <div className={a.status === "APPROVED" ? "rounded-xl bg-green-50 px-4 py-3 text-sm text-green-800" : "rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800"}>
            {a.status === "APPROVED" ? "Approved" : "Rejected"} {a.reviewed_at && dateTimeLong(a.reviewed_at)}
            {a.source === "ADMIN" && " · added by an administrator"}
            {a.review_note && <span className="mt-1 block">Note: “{a.review_note}”</span>}
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-2">
          <section className="rounded-xl border border-line p-5">
            <h3 className="mb-5 text-lg font-medium text-gray-900">Store Information</h3>
            <InfoList
              rows={[
                { label: "Owner name", value: a.owner_full_name },
                { label: "Email", value: a.owner_email },
                { label: "Phone", value: a.owner_phone },
                { label: "Store Address", value: [a.address_line, a.area].filter(Boolean).join(", ") },
                { label: "Business Type", value: businessTypeLabel(a.business_type) },
                { label: "Business Category", value: a.business_category },
                { label: "Cuisine Type", value: a.cuisine_types.join(", ") },
                { label: "Branches", value: a.branch_count },
                { label: "National ID/ Passport", value: a.national_id },
              ]}
            />
          </section>
          <div className="space-y-5">
            <section className="rounded-xl border border-line p-5">
              <h3 className="mb-5 text-lg font-medium text-gray-900">Document</h3>
              {otherDocs.length || shopImage ? (
                <dl className="space-y-4 text-sm">
                  {otherDocs.map(([kind, url]) => (
                    <div key={kind} className="flex flex-wrap items-center gap-3">
                      <dt className="w-44 text-gray-600">{documentLabel(kind)}</dt>
                      <dd className="min-w-0">
                        <DocumentChip url={url} />
                      </dd>
                    </div>
                  ))}
                  {shopImage && (
                    <div className="flex flex-wrap items-center gap-3">
                      <dt className="w-44 text-gray-600">Store Image</dt>
                      <dd>
                        <a href={shopImage} target="_blank" rel="noopener noreferrer" aria-label="Open store image">
                          <Avatar src={shopImage} name={a.business_name} size={48} rounded="lg" className="border border-line" />
                        </a>
                      </dd>
                    </div>
                  )}
                </dl>
              ) : (
                <p className="text-sm text-gray-500">No documents were uploaded.</p>
              )}
            </section>
            <section className="rounded-xl border border-line p-5">
              <h3 className="mb-5 text-lg font-medium text-gray-900">Payout</h3>
              {a.payout.method ? (
                <InfoList
                  labelWidth="sm:w-44"
                  rows={[
                    { label: "Method", value: paymentMethod(a.payout.method) },
                    { label: "Account name", value: a.payout.account_name },
                    { label: "Account number", value: a.payout.account_number },
                    { label: "Bank", value: a.payout.bank_name, hidden: !a.payout.bank_name },
                    { label: "Branch", value: a.payout.branch_name, hidden: !a.payout.branch_name },
                  ]}
                />
              ) : (
                <p className="text-sm text-gray-500">No payout details given.</p>
              )}
            </section>
          </div>
        </div>
      </Card>
      {dialog}
    </>
  );
}
