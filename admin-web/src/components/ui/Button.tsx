import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";

type Variant =
  | "primary"
  | "outline"
  | "brand-outline"
  | "danger"
  | "danger-soft"
  | "success"
  | "success-soft"
  | "ghost";
type Size = "xs" | "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-brand-500 text-white hover:bg-brand-600 disabled:bg-brand-300",
  outline: "border border-gray-300 bg-white text-gray-800 hover:bg-gray-50 disabled:text-gray-400",
  "brand-outline": "border border-brand-500 bg-white text-brand-500 hover:bg-brand-50 disabled:opacity-50",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300",
  "danger-soft": "bg-red-50 text-red-600 hover:bg-red-100 disabled:opacity-50",
  success: "bg-green-600 text-white hover:bg-green-700 disabled:bg-green-300",
  "success-soft": "bg-green-50 text-green-600 hover:bg-green-100 disabled:opacity-50",
  ghost: "text-gray-700 hover:bg-gray-100 disabled:text-gray-400",
};

const sizes: Record<Size, string> = {
  xs: "h-7 gap-1 rounded-md px-2.5 text-xs",
  sm: "h-9 gap-1.5 rounded-lg px-3.5 text-sm",
  md: "h-10 gap-2 rounded-full px-5 text-sm",
  lg: "h-12 gap-2 rounded-full px-6 text-base",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({
  className,
  label,
  children,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900 disabled:opacity-40",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
