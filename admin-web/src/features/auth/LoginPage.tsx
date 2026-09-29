import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router";
import { KeyRound, Lock, Mail } from "lucide-react";

import { login, login2fa } from "@/api/auth";
import { AdminLogo } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, PasswordInput } from "@/components/ui/Field";
import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

import { AuthScreen } from "./AuthLayout";

/** Only same-app paths: never follow a `next` to another origin. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginPage() {
  const session = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const location = useLocation();
  const notice = (location.state as { notice?: string } | null)?.notice;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [tempToken, setTempToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (session) return <Navigate to={safeNext(params.get("next"))} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (tempToken) {
        await login2fa(tempToken, code.trim(), remember);
      } else {
        const challenge = await login(email.trim(), password, remember);
        if (challenge) {
          setTempToken(challenge.tempToken);
          setBusy(false);
          return;
        }
      }
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (err) {
      setError(err);
      // A 2FA challenge lasts five minutes; once it lapses, start over.
      if (tempToken && err instanceof ApiError && err.status === 401) {
        setTempToken(null);
        setCode("");
      }
      setBusy(false);
    }
  };

  return (
    <AuthScreen title="Sign in">
      <div className="flex flex-col items-center text-center">
        <AdminLogo />
        <h1 className="mt-8 text-[32px] font-semibold tracking-tight text-gray-950">Welcome back</h1>
        <p className="mt-2 text-[15px] text-gray-500">
          {tempToken ? "Enter the 6-digit code from your authenticator app." : "Please login to continue your dashboard."}
        </p>
      </div>

      <form onSubmit={submit} className="mt-10 space-y-5">
        {notice && !error && <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">{notice}</p>}
        {tempToken ? (
          <Field label="Authentication code">
            {(id) => (
              <Input
                id={id}
                inputSize="lg"
                icon={<KeyRound />}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                autoFocus
                required
              />
            )}
          </Field>
        ) : (
          <>
            <Field label="Email">
              {(id) => (
                <Input
                  id={id}
                  type="email"
                  inputSize="lg"
                  icon={<Mail />}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="username"
                  placeholder="you@company.com"
                  autoFocus
                  required
                />
              )}
            </Field>
            <Field label="Password">
              {(id) => (
                <PasswordInput
                  id={id}
                  inputSize="lg"
                  icon={<Lock />}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  required
                />
              )}
            </Field>
            <div className="flex items-center justify-between">
              <Checkbox checked={remember} onChange={setRemember} label="Remember me" />
              <Link
                to="/forgot-password"
                state={{ email }}
                className="text-[15px] text-gray-700 underline underline-offset-4 hover:text-gray-900"
              >
                Forgot Password?
              </Link>
            </div>
          </>
        )}

        <InlineError error={error} />

        <Button type="submit" size="lg" className="mt-2 h-14 w-full" loading={busy}>
          {tempToken ? "Verify" : "Sign In"}
        </Button>
        {tempToken && (
          <button
            type="button"
            onClick={() => {
              setTempToken(null);
              setCode("");
              setError(null);
            }}
            className="block w-full text-center text-sm text-gray-600 hover:text-gray-900"
          >
            Use a different account
          </button>
        )}
      </form>

      <p className="mt-14 text-center text-sm text-gray-500">
        Don&apos;t have access? Ask an administrator for an <span className="font-semibold text-brand-500">invitation</span>.
      </p>
    </AuthScreen>
  );
}
