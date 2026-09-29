import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Lock, Mail, User } from "lucide-react";

import { acceptInvitation, readInvitation } from "@/api/auth";
import { AdminLogo } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { InlineError, PageSpinner } from "@/components/ui/Feedback";
import { Field, Input, PasswordInput } from "@/components/ui/Field";

import { AuthScreen } from "./AuthLayout";

/** Sign up for admin: opened from the emailed invitation link. */
export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const invitation = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => readInvitation(token),
    enabled: token.length >= 20,
    retry: false,
  });

  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError(new Error("The two passwords do not match."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await acceptInvitation(token, name.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  const unusable = token.length < 20 || invitation.isError;

  return (
    <AuthScreen title="Sign up for admin">
      <div className="flex flex-col items-center text-center">
        <AdminLogo />
        <h1 className="mt-8 text-[32px] font-semibold tracking-tight text-gray-950">Sign up for admin</h1>
        <p className="mt-2 text-[15px] text-gray-500">Please sign up to continue to your dashboard.</p>
      </div>

      {invitation.isLoading ? (
        <PageSpinner />
      ) : unusable ? (
        <div className="mt-10 rounded-xl border border-orange-200 bg-orange-50 p-5 text-center text-sm text-orange-800">
          This invitation link is not valid. It may have been used, revoked or have expired. Ask an administrator to
          send a new one.
          <div className="mt-4">
            <Link to="/login" className="font-semibold text-brand-500 hover:underline">
              Go to sign in
            </Link>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-10 space-y-5">
          <Field label="Full Name">
            {(id) => (
              <Input
                id={id}
                inputSize="lg"
                icon={<User />}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={invitation.data?.full_name ?? "Your name"}
                autoComplete="name"
                minLength={2}
                autoFocus
                required
              />
            )}
          </Field>
          <Field label="Email">
            {(id) => (
              <Input id={id} inputSize="lg" icon={<Mail />} value={invitation.data?.email ?? ""} readOnly disabled />
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
                placeholder="At least 8 characters"
                autoComplete="new-password"
                minLength={8}
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
                placeholder="Enter your password again"
                autoComplete="new-password"
                minLength={8}
                required
              />
            )}
          </Field>
          <InlineError error={error} />
          <Button type="submit" size="lg" className="mt-2 h-14 w-full" loading={busy}>
            Create account
          </Button>
        </form>
      )}
    </AuthScreen>
  );
}
