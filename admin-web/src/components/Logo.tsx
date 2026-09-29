import { cn } from "@/lib/cn";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 34" className={cn("h-8 w-auto", className)} aria-hidden>
      <g fill="currentColor">
        <path d="M2.5 1.5h4.2a2 2 0 0 1 2 1.7L9.4 8H6.2l-.6-3.5H2.5a1.5 1.5 0 0 1 0-3Z" />
        <rect x="6" y="8" width="31" height="4.2" rx="2.1" />
        <rect x="8.5" y="14.2" width="26" height="4.2" rx="2.1" />
        <rect x="11" y="20.4" width="21" height="4.2" rx="2.1" />
        <circle cx="15" cy="30" r="2.6" />
        <circle cx="27.5" cy="30" r="2.6" />
      </g>
    </svg>
  );
}

/** Sidebar logo: mark, wordmark and tagline. */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark className="h-8 text-brand-500" />
      <span className="leading-none">
        <span className="block text-[13px] font-bold tracking-tight text-gray-900">CHEERING</span>
        <span className="block text-[10px] text-brand-500">Order everything</span>
      </span>
    </span>
  );
}

/** Sign-in screens: mark plus the slanted "Admin" tag. */
export function AdminLogo() {
  return (
    <span className="inline-flex items-center gap-2">
      <LogoMark className="h-10 text-brand-500" />
      <span className="leading-none">
        <span className="block text-[13px] font-bold tracking-tight text-gray-900">CHEERING</span>
        <span className="mt-1 inline-block -skew-x-12 bg-brand-500 px-3 py-0.5 text-sm font-semibold text-white">
          <span className="inline-block skew-x-12">Admin</span>
        </span>
      </span>
    </span>
  );
}
