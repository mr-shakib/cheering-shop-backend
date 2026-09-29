import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useApproveRiderApplication, useRejectRiderApplication, useRiderApplication, type RiderApplication } from "@/api/riders";
import { PageHeader } from "@/components/layout/Page";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Avatar, DocumentChip, InfoList } from "@/components/ui/Display";
import { ErrorState, InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Field, PasswordInput, TextArea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Overlay";
import { useToast } from "@/components/ui/Toast";
import { dateOnly, dateTimeLong } from "@/lib/format";
import { applicationStatus, documentLabel, paymentMethod, vehicleLabel } from "@/lib/vocab";

import { HeaderFact } from "../vendors/VendorApplicationDetailsPage";

function ApproveDialog({ app, onClose }: { app: RiderApplication; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [note, setNote] = useState("");
  const approve = useApproveRiderApplication();
  const toast = useToast();
  const navigate = useNavigate();
  return (
    <Modal
      open
      onClose={onClose}
      title={`Approve ${app.full_name}?`}
      description="Creates the rider's account, cleared to ride but off shift, with this application's documents and photo. The applicant is emailed either way."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="success"
            loading={approve.isPending}
            disabled={password.length > 0 && password.length < 8}
            onClick={() =>
              approve.mutate(
                { id: app.id, password, note },
                {
                  onSuccess: () => {
                    toast(`${app.full_name} approved`);
                    onClose();
                    navigate("/rider-applications");
                  },
                },
              )
            }
          >
            Approve
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Sign-in password (optional)" hint="Lets the rider sign in straight away. Otherwise set one later from their profile.">
          {(id) => <PasswordInput id={id} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />}
        </Field>
        <Field label="Note (optional)">{(id) => <TextArea id={id} look="outline" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} className="min-h-16" />}</Field>
        <InlineError error={approve.error} />
      </div>
    </Modal>
  );
}

export function RiderApplicationDetailsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const app = useRiderApplication(id);
  const reject = useRejectRiderApplication();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [approving, setApproving] = useState(false);
  const back = { to: "/rider-applications", label: "Back to Application" };

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
  const docs = Object.entries(a.documents);

  return (
    <>
      <PageHeader title="Application Details" back={back} />
      <Card className="space-y-5 p-4 sm:p-5">
        <Card className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center">
          <Avatar src={a.documents.profile_photo} name={a.full_name} size={108} rounded="lg" />
          <div className="min-w-0 flex-1">
            <h2 className="text-2xl font-semibold text-gray-900">{a.full_name}</h2>
            <div className="mt-3 flex flex-wrap gap-x-8 gap-y-3">
              <HeaderFact label="Application date" value={dateTimeLong(a.submitted_at)} />
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
                    title: `Reject ${a.full_name}?`,
                    description: "The note is emailed to the applicant as the reason.",
                    confirmLabel: "Reject application",
                    tone: "danger",
                    reason: { label: "Note to the applicant", required: true, minLength: 3, placeholder: "e.g. The driving license photo is unreadable." },
                    onConfirm: (note) =>
                      reject.mutateAsync({ id: a.id, note }).then(() => {
                        toast("Application rejected");
                        navigate("/rider-applications");
                      }),
                  })
                }
              >
                Reject
              </Button>
              <Button variant="success" size="lg" className="h-12 px-9" onClick={() => setApproving(true)}>
                Approve
              </Button>
            </div>
          ) : a.rider_id ? (
            <Link to={`/riders/${a.rider_id}`}>
              <Button variant="outline">View rider</Button>
            </Link>
          ) : null}
        </Card>

        {a.status !== "PENDING" && (
          <div className={a.status === "APPROVED" ? "rounded-xl bg-green-50 px-4 py-3 text-sm text-green-800" : "rounded-xl bg-red-50 px-4 py-3 text-sm text-red-800"}>
            {a.status === "APPROVED" ? "Approved" : "Rejected"} {a.reviewed_at && dateTimeLong(a.reviewed_at)}
            {a.review_note && <span className="mt-1 block">Note: “{a.review_note}”</span>}
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-2">
          <section className="rounded-xl border border-line p-5">
            <h3 className="mb-5 text-lg font-medium text-gray-900">Personal Information</h3>
            <InfoList
              rows={[
                { label: "Full Name", value: a.full_name },
                { label: "Email", value: a.email },
                { label: "Phone", value: a.phone },
                { label: "Vehicle", value: vehicleLabel(a.vehicle_type) },
                { label: "License number", value: a.license_number, hidden: !a.license_number },
                { label: "Date of Birth", value: dateOnly(a.date_of_birth) },
                { label: "National ID/ Passport", value: a.national_id },
              ]}
            />
          </section>
          <div className="space-y-5">
            <section className="rounded-xl border border-line p-5">
              <h3 className="mb-5 text-lg font-medium text-gray-900">Document</h3>
              {docs.length ? (
                <dl className="space-y-4 text-sm">
                  {docs.map(([kind, url]) => (
                    <div key={kind} className="flex flex-wrap items-center gap-3">
                      <dt className="w-44 text-gray-600">{documentLabel(kind)}</dt>
                      <dd className="min-w-0">
                        <DocumentChip url={url} />
                      </dd>
                    </div>
                  ))}
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
      {approving && <ApproveDialog app={a} onClose={() => setApproving(false)} />}
    </>
  );
}
