import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2, RotateCw } from "lucide-react";

import { ApiError, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-5 animate-spin text-brand-500", className)} />;
}

export function PageSpinner() {
  return (
    <div className="flex min-h-64 items-center justify-center">
      <Spinner className="size-7" />
    </div>
  );
}

export function EmptyState({ children, icon, className }: { children: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 py-14 text-center text-sm text-gray-500", className)}>
      <span className="flex size-11 items-center justify-center rounded-full bg-gray-100 text-gray-400">
        {icon ?? <Inbox className="size-5" />}
      </span>
      {children}
    </div>
  );
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 py-14 text-center", className)}>
      <span className="flex size-11 items-center justify-center rounded-full bg-red-50 text-red-500">
        <AlertTriangle className="size-5" />
      </span>
      <p className="max-w-md text-sm text-gray-700">{errorMessage(error)}</p>
      {requestId && <p className="text-xs text-gray-400">Request ID: {requestId}</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-brand-500 hover:bg-brand-50"
        >
          <RotateCw className="size-3.5" /> Try again
        </button>
      )}
    </div>
  );
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600" role="alert">
      {errorMessage(error)}
    </p>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-gray-100", className)} />;
}
