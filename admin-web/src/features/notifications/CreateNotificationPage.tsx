import { useState } from "react";
import { useNavigate } from "react-router";
import { format } from "date-fns";

import { useSendCampaign } from "@/api/marketing";
import { useSettings } from "@/api/settings";
import { LogoMark } from "@/components/Logo";
import { PageHeader } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { InlineError } from "@/components/ui/Feedback";
import { Field, Input, Radio, Select, TextArea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { dateTimeLong } from "@/lib/format";

import { AUDIENCE_OPTIONS } from "./NotificationsPage";

export function CreateNotificationPage() {
  const navigate = useNavigate();
  const send = useSendCampaign();
  const settings = useSettings();
  const toast = useToast();
  const [confirm, dialog] = useConfirm();
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [type, setType] = useState("PROMOTION");
  const [audience, setAudience] = useState("CUSTOMER");
  const [later, setLater] = useState(false);
  const [when, setWhen] = useState("");
  const [error, setError] = useState<unknown>(null);
  const appName = settings.data?.app_name ?? "Cheering";

  const submit = () => {
    setError(null);
    if (!title.trim() || !message.trim()) {
      setError(new Error("A notification needs a title and a message."));
      return;
    }
    let scheduled: string | undefined;
    if (later) {
      const at = when ? new Date(when) : null;
      if (!at || at.getTime() <= Date.now() + 30_000) {
        setError(new Error("Choose a time in the future."));
        return;
      }
      scheduled = at.toISOString();
    }
    const who = AUDIENCE_OPTIONS.find((a) => a.value === audience)?.label.toLowerCase() ?? audience;
    confirm({
      title: later ? "Schedule this notification?" : "Send this notification now?",
      description: later
        ? `It goes to every ${who === "everyone" ? "user" : who} at ${dateTimeLong(scheduled!)}. You can cancel it until then.`
        : `It lands in every ${who === "everyone" ? "user's" : `${who}'s`} inbox and is pushed to their phones straight away. This cannot be undone.`,
      confirmLabel: later ? "Schedule" : "Send now",
      onConfirm: () =>
        send.mutateAsync({ title: title.trim(), message: message.trim(), type, audience, scheduled_for: scheduled }).then((c) => {
          toast(c.status === "SENT" ? `Sent to ${c.recipient_count} inboxes` : "Notification scheduled");
          navigate("/notifications");
        }),
    });
  };

  return (
    <>
      <PageHeader title="Create New notification" back={{ to: "/notifications", label: "Back" }} />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card className="space-y-5 p-5">
          <Field label="Title">{(id) => <Input id={id} look="outline" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="Your title here" />}</Field>
          <Field label="Message">
            {(id) => (
              <TextArea
                id={id}
                look="outline"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                maxLength={500}
                counter
                placeholder="Enter notification description"
                className="min-h-24"
              />
            )}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Notification Type">
              {(id) => (
                <Select
                  id={id}
                  look="outline"
                  options={[
                    { value: "PROMOTION", label: "Promotion" },
                    { value: "ALERT", label: "Alert" },
                    { value: "UPDATE", label: "Update" },
                  ]}
                  value={type}
                  onChange={(e) => setType(e.target.value)}
                />
              )}
            </Field>
            <Field label="Audience">{(id) => <Select id={id} look="outline" options={AUDIENCE_OPTIONS} value={audience} onChange={(e) => setAudience(e.target.value)} />}</Field>
          </div>
          <div>
            <p className="mb-2.5 text-sm font-medium text-gray-900">Send Time</p>
            <div className="flex flex-wrap gap-6">
              <Radio name="when" checked={!later} onChange={() => setLater(false)} label="Send Now" />
              <Radio name="when" checked={later} onChange={() => setLater(true)} label="Scheduled for later" />
            </div>
          </div>
          {later && (
            <Field label="Select Date and Time" hint="Sent within a minute of this time. Your local time zone.">
              {(id) => (
                <Input
                  id={id}
                  look="outline"
                  type="datetime-local"
                  value={when}
                  min={format(new Date(), "yyyy-MM-dd'T'HH:mm")}
                  onChange={(e) => setWhen(e.target.value)}
                  className="max-w-xs"
                />
              )}
            </Field>
          )}
        </Card>

        <div className="rounded-2xl bg-gray-100 p-5">
          <p className="text-sm text-gray-800">Preview</p>
          <div className="mx-auto mt-4 max-w-[320px] rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2.5">
              <span className="flex size-10 items-center justify-center rounded-full bg-brand-50">
                <LogoMark className="h-5 text-brand-500" />
              </span>
              <span className="flex-1 text-sm font-medium tracking-tight text-gray-900 uppercase">{appName}</span>
              <span className="text-[11px] text-gray-500">{later && when ? format(new Date(when), "h:mm a") : "now"}</span>
            </div>
            <p className="mt-3 text-base font-semibold break-words text-gray-900">{title || "50% off all order"}</p>
            <p className="mt-1 text-sm break-words whitespace-pre-wrap text-gray-600">{message || "Order your favorite food and get 50% off delivery. Limited time deal!"}</p>
          </div>
          <div className="mt-8 grid grid-cols-2 gap-3">
            <Button variant="outline" onClick={() => navigate("/notifications")}>
              Cancel
            </Button>
            <Button onClick={submit} loading={send.isPending}>
              {later ? "Schedule" : "Send Notification"}
            </Button>
          </div>
          <div className="mt-3">
            <InlineError error={error} />
          </div>
        </div>
      </div>
      {dialog}
    </>
  );
}
