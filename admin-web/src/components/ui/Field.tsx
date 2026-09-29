import {
  forwardRef,
  useId,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { ChevronDown, Eye, EyeOff, Search, X } from "lucide-react";

import { cn } from "@/lib/cn";

type Look = "filled" | "outline";

const looks: Record<Look, string> = {
  filled: "bg-field border border-transparent focus:border-brand-300 focus:bg-white",
  outline: "bg-white border border-gray-200 focus:border-brand-400",
};

const base =
  "w-full rounded-lg text-sm text-gray-900 placeholder:text-gray-400 outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus:ring-3 focus:ring-brand-100";

export function Label({ htmlFor, children, className }: { htmlFor?: string; children: ReactNode; className?: string }) {
  return (
    <label htmlFor={htmlFor} className={cn("mb-1.5 block text-xs font-medium text-gray-700", className)}>
      {children}
    </label>
  );
}

/** Label + control + hint/error. Pass a render function to get the generated id. */
export function Field({
  label,
  hint,
  error,
  className,
  children,
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  className?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className={className}>
      {label && <Label htmlFor={id}>{label}</Label>}
      {children(id)}
      {error ? (
        <p className="mt-1 text-xs text-red-600">{error}</p>
      ) : hint ? (
        <p className="mt-1 text-xs text-gray-500">{hint}</p>
      ) : null}
    </div>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  look?: Look;
  icon?: ReactNode;
  suffix?: ReactNode;
  inputSize?: "md" | "lg";
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { look = "filled", icon, suffix, inputSize = "md", className, ...rest },
  ref,
) {
  return (
    <div className={cn("relative", className)}>
      {icon && (
        <span className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-gray-500 [&>svg]:size-[18px]">
          {icon}
        </span>
      )}
      <input
        ref={ref}
        className={cn(
          base,
          looks[look],
          inputSize === "lg" ? "h-12 text-[15px]" : "h-10",
          icon ? "pl-11" : "pl-3.5",
          suffix ? "pr-11" : "pr-3.5",
        )}
        {...rest}
      />
      {suffix && <span className="absolute top-1/2 right-3 -translate-y-1/2">{suffix}</span>}
    </div>
  );
});

export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputProps, "type" | "suffix">>(function PasswordInput(
  props,
  ref,
) {
  const [shown, setShown] = useState(false);
  return (
    <Input
      ref={ref}
      type={shown ? "text" : "password"}
      suffix={
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          className="flex text-gray-500 hover:text-gray-800"
          aria-label={shown ? "Hide password" : "Show password"}
        >
          {shown ? <Eye className="size-[18px]" /> : <EyeOff className="size-[18px]" />}
        </button>
      }
      {...props}
    />
  );
});

export const TextArea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement> & { look?: Look; counter?: boolean }
>(function TextArea({ look = "filled", className, counter, maxLength, value, ...rest }, ref) {
  return (
    <div className="relative">
      <textarea
        ref={ref}
        maxLength={maxLength}
        value={value}
        className={cn(base, looks[look], "min-h-24 resize-y px-3.5 py-2.5", counter && "pb-6", className)}
        {...rest}
      />
      {counter && maxLength && (
        <span className="pointer-events-none absolute right-3 bottom-2 text-xs text-gray-400">
          {String(value ?? "").length}/{maxLength}
        </span>
      )}
    </div>
  );
});

export interface SelectOption {
  value: string;
  label: string;
}

/** A native select dressed like the mockups' "All Status ⌄" buttons. */
export const Select = forwardRef<
  HTMLSelectElement,
  Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> & {
    options: SelectOption[];
    placeholder?: string;
    look?: Look | "button";
  }
>(function Select({ options, placeholder, look = "button", className, ...rest }, ref) {
  return (
    <div className={cn("relative", className)}>
      <select
        ref={ref}
        className={cn(
          "h-10 w-full appearance-none rounded-lg pr-9 pl-3 text-sm text-gray-900 outline-none focus:ring-3 focus:ring-brand-100",
          look === "button"
            ? "border border-gray-300 bg-white font-medium hover:bg-gray-50"
            : look === "filled"
              ? "border border-transparent bg-field"
              : "border border-gray-200 bg-white",
        )}
        {...rest}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-gray-600" />
    </div>
  );
});

export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={cn("relative w-full sm:max-w-[335px]", className)}>
      <Search className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-gray-500" />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn(base, "h-10 border border-gray-300 bg-white pr-9 pl-10 [&::-webkit-search-cancel-button]:hidden")}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute top-1/2 right-2.5 -translate-y-1/2 rounded p-0.5 text-gray-400 hover:text-gray-700"
          aria-label="Clear search"
        >
          <X className="size-4" />
        </button>
      )}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50",
        checked ? "bg-brand-500" : "bg-gray-300",
      )}
    >
      <span
        className={cn(
          "inline-block size-5 rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5.5" : "translate-x-0.5",
        )}
      />
    </button>
  );
}

export function Radio({
  checked,
  onChange,
  label,
  name,
}: {
  checked: boolean;
  onChange: () => void;
  label: ReactNode;
  name: string;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2.5 text-sm text-gray-800">
      <input type="radio" name={name} checked={checked} onChange={onChange} className="peer sr-only" />
      <span
        className={cn(
          "flex size-5 items-center justify-center rounded-full border-2 transition-colors peer-focus-visible:ring-3 peer-focus-visible:ring-brand-100",
          checked ? "border-brand-500" : "border-gray-300",
        )}
      >
        {checked && <span className="size-2.5 rounded-full bg-brand-500" />}
      </span>
      {label}
    </label>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2.5 text-sm text-gray-800">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 rounded border-gray-300 accent-brand-500"
      />
      {label}
    </label>
  );
}
