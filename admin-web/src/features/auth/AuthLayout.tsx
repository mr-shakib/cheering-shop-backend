import type { ReactNode } from "react";
import { Link } from "react-router";
import { ChevronLeft, Mail } from "lucide-react";

import { usePageTitle } from "@/components/layout/Page";

/** Sign in / Sign up: white page with the faint tile pattern in two corners. */
export function AuthScreen({ title, children }: { title: string; children: ReactNode }) {
  usePageTitle(title);
  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden bg-white px-4 py-12">
      <div className="auth-tiles pointer-events-none absolute -top-10 -left-10 size-[520px]" aria-hidden />
      <div className="auth-tiles pointer-events-none absolute -right-10 -bottom-10 size-[520px]" aria-hidden />
      <div className="relative w-full max-w-[510px]">{children}</div>
    </div>
  );
}

/** Password reset steps: grey page, a white card, a Back button top-left. */
export function AuthCard({
  title,
  description,
  back,
  onBack,
  children,
}: {
  title: string;
  description: ReactNode;
  back?: string;
  onBack?: () => void;
  children: ReactNode;
}) {
  usePageTitle(title);
  const backButton =
    "inline-flex h-10 items-center gap-2 rounded-xl border border-gray-200 bg-white px-3.5 text-[15px] text-gray-900 hover:bg-gray-50";
  return (
    <div className="relative flex min-h-full items-center justify-center bg-page px-4 py-20">
      <div className="absolute top-6 left-6 sm:top-6 sm:left-8">
        {onBack ? (
          <button type="button" onClick={onBack} className={backButton}>
            <ChevronLeft className="size-4" /> Back
          </button>
        ) : (
          <Link to={back ?? "/login"} className={backButton}>
            <ChevronLeft className="size-4" /> Back
          </Link>
        )}
      </div>
      <div className="w-full max-w-[510px] rounded-2xl border border-gray-200 bg-white px-6 py-10 shadow-sm sm:px-10">
        <div className="mx-auto flex size-[76px] items-center justify-center rounded-full border border-gray-200">
          <span className="flex size-11 items-center justify-center rounded-full bg-gradient-to-b from-brand-400 to-brand-500 text-white shadow-md shadow-brand-200">
            <Mail className="size-5" />
          </span>
        </div>
        <h1 className="mt-6 text-center text-[30px] font-semibold tracking-tight text-gray-950">{title}</h1>
        <div className="mt-3 text-center text-[15px] text-gray-500">{description}</div>
        <div className="mt-8">{children}</div>
      </div>
    </div>
  );
}
