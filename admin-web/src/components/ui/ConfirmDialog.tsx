import { useEffect, useState, type ReactNode } from "react";

import { Button } from "./Button";
import { InlineError } from "./Feedback";
import { Field, TextArea } from "./Field";
import { Modal } from "./Overlay";

export interface ConfirmOptions {
  title: ReactNode;
  description?: ReactNode;
  confirmLabel: string;
  tone?: "primary" | "danger" | "success";
  /** Ask for a reason. `required` refuses an empty one (rejections are emailed). */
  reason?: { label: string; placeholder?: string; required?: boolean; minLength?: number; hint?: string };
  onConfirm: (reason: string) => Promise<unknown>;
}

/** A confirmation step for anything that changes money or reaches a user. */
export function ConfirmDialog({ options, onClose }: { options: ConfirmOptions | null; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (options) {
      setReason("");
      setError(null);
      setBusy(false);
    }
  }, [options]);

  if (!options) return null;
  const needsReason = !!options.reason?.required && reason.trim().length < (options.reason.minLength ?? 1);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await options.onConfirm(reason.trim());
      onClose();
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={busy ? () => {} : onClose}
      title={options.title}
      description={options.description}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant={options.tone === "danger" ? "danger" : options.tone === "success" ? "success" : "primary"}
            onClick={confirm}
            loading={busy}
            disabled={needsReason}
          >
            {options.confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {options.reason && (
          <Field label={options.reason.label} hint={options.reason.hint}>
            {(id) => (
              <TextArea
                id={id}
                autoFocus
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={options.reason?.placeholder}
                maxLength={500}
                look="outline"
              />
            )}
          </Field>
        )}
        <InlineError error={error} />
      </div>
    </Modal>
  );
}

/** `const [confirm, dialog] = useConfirm();` then render `{dialog}` and call `confirm({...})`. */
export function useConfirm(): [(options: ConfirmOptions) => void, ReactNode] {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  return [setOptions, <ConfirmDialog key="confirm" options={options} onClose={() => setOptions(null)} />];
}
