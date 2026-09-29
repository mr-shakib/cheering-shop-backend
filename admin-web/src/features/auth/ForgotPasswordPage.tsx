/* Forgot Password → OTP Authentication → New password.
 *
 * The API has no separate "verify code" call: the code is checked when the
 * new password is submitted. So step two only collects it, and a wrong code
 * surfaces on step three with a way back. */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { Lock, Mail } from "lucide-react";

import { requestPasswordReset, resetPassword } from "@/api/auth";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/Feedback";
import { Field, Input, PasswordInput } from "@/components/ui/Field";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

import { AuthCard } from "./AuthLayout";

const CODE_LENGTH = 4;
const RESEND_SECONDS = 60;

function maskEmail(email: string) {
  const [user, domain] = email.split("@");
  if (!domain) return email;
  return `${user.slice(0, Math.min(5, Math.max(1, user.length - 2)))}******@${domain}`;
}

function useCountdown() {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  return [left, () => setLeft(RESEND_SECONDS)] as const;
}

function ResendLine({ left, onResend, busy }: { left: number; onResend: () => void; busy: boolean }) {
  return (
    <p className="mt-6 text-center text-[15px] text-gray-500">
      {left > 0 ? (
        <>
          Resend code in{" "}
          <span className="font-semibold text-brand-500">
            {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
          </span>
        </>
      ) : (
        <button type="button" onClick={onResend} disabled={busy} className="font-semibold text-brand-500 hover:underline">
          Resend code
        </button>
      )}
    </p>
  );
}

function CodeBoxes({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length: CODE_LENGTH }, (_, i) => value[i] ?? "");
  return (
    <div className="flex justify-center gap-4 sm:gap-6">
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current[i] = el;
          }}
          value={d}
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          aria-label={`Digit ${i + 1}`}
          autoFocus={i === 0}
          maxLength={CODE_LENGTH}
          onChange={(e) => {
            const typed = e.target.value.replace(/\D/g, "");
            if (!typed) return;
            // Pasting the whole code into one box fills them all.
            const next = (value.slice(0, i) + typed).slice(0, CODE_LENGTH);
            onChange(next);
            refs.current[Math.min(next.length, CODE_LENGTH - 1)]?.focus();
          }}
          onKeyDown={(e) => {
            if (e.key === "Backspace") {
              e.preventDefault();
              const cut = d ? i : Math.max(0, i - 1);
              onChange(value.slice(0, cut));
              refs.current[cut]?.focus();
            }
          }}
          className={cn(
            "size-14 rounded-xl border text-center text-2xl font-semibold text-gray-900 outline-none focus:border-brand-500 focus:ring-3 focus:ring-brand-100",
            d ? "border-gray-300" : "border-gray-200",
          )}
        />
      ))}
    </div>
  );
}

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState<"email" | "code" | "password">("email");
  const [email, setEmail] = useState((location.state as { email?: string } | null)?.email ?? "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [left, restart] = useCountdown();

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await requestPasswordReset(email.trim());
      restart();
      setStep("code");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const reset = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError(new Error("The two passwords do not match."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await resetPassword(email.trim(), code, password);
      navigate("/login", {
        replace: true,
        state: { notice: "Password updated. Sign in with your new password." },
      });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  if (step === "email") {
    return (
      <AuthCard title="Reset your password" description="Enter your work email and we'll send you a reset code.">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
          className="space-y-6"
        >
          <Field label="Email">
            {(id) => (
              <Input
                id={id}
                type="email"
                inputSize="lg"
                icon={<Mail />}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                autoFocus
                required
              />
            )}
          </Field>
          <InlineError error={error} />
          <Button type="submit" size="lg" className="h-14 w-full" loading={busy}>
            Send Code
          </Button>
        </form>
      </AuthCard>
    );
  }

  if (step === "code") {
    return (
      <AuthCard
        title="Verify your email"
        onBack={() => setStep("email")}
        description={
          <>
            We have sent a code to your email
            <br />
            <span className="text-gray-900">{maskEmail(email)}</span>
          </>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            setStep("password");
          }}
        >
          <CodeBoxes value={code} onChange={setCode} />
          <InlineError error={error} />
          <Button type="submit" size="lg" className="mt-8 h-14 w-full" disabled={code.length !== CODE_LENGTH}>
            Verify Account
          </Button>
        </form>
        <ResendLine left={left} onResend={send} busy={busy} />
      </AuthCard>
    );
  }

  const wrongCode = error instanceof ApiError && error.code === "INVALID_OTP";
  return (
    <AuthCard
      title="Set new password"
      onBack={() => setStep("code")}
      description="Choose a new password of at least 8 characters. You will be signed out everywhere else."
    >
      <form onSubmit={reset} className="space-y-5">
        <Field label="New Password">
          {(id) => (
            <PasswordInput
              id={id}
              inputSize="lg"
              icon={<Lock />}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="new-password"
              minLength={8}
              autoFocus
              required
            />
          )}
        </Field>
        <Field label="Confirm Password">
          {(id) => (
            <PasswordInput
              id={id}
              inputSize="lg"
              icon={<Lock />}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Enter your password"
              autoComplete="new-password"
              minLength={8}
              required
            />
          )}
        </Field>
        <InlineError error={error} />
        {wrongCode && (
          <button
            type="button"
            onClick={() => {
              setCode("");
              setError(null);
              setStep("code");
            }}
            className="text-sm font-medium text-brand-500 hover:underline"
          >
            Re-enter the code
          </button>
        )}
        <Button type="submit" size="lg" className="h-14 w-full" loading={busy}>
          Reset Password
        </Button>
      </form>
    </AuthCard>
  );
}
