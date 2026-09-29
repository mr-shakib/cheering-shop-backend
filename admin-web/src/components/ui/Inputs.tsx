/* Composite inputs: date range filter, searchable picker, file upload. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { format, parseISO } from "date-fns";
import { CalendarDays, Check, ChevronDown, ImagePlus, Loader2, Search, UploadCloud, X } from "lucide-react";

import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useDebounced } from "@/lib/hooks";
import { uploadFile } from "@/lib/upload";

import { Button } from "./Button";
import { Popover } from "./Popover";

/** "15 Aug 2026 - 26 Aug 2026". Values are yyyy-MM-dd strings, inclusive. */
export function DateRangeFilter({
  from,
  to,
  onChange,
  className,
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  className?: string;
}) {
  const [draftFrom, setDraftFrom] = useState(from);
  const [draftTo, setDraftTo] = useState(to);
  const label = (d: string) => format(parseISO(d), "d MMM yyyy");
  const text = from && to ? `${label(from)} - ${label(to)}` : from ? `From ${label(from)}` : to ? `Until ${label(to)}` : "Any date";

  return (
    <Popover
      className={className}
      align="right"
      onOpenChange={(open) => {
        if (open) {
          setDraftFrom(from);
          setDraftTo(to);
        }
      }}
      trigger={({ toggle }) => (
        <button
          type="button"
          onClick={toggle}
          className="inline-flex h-10 w-full items-center gap-2.5 rounded-lg border border-gray-300 bg-white px-3 text-sm font-medium whitespace-nowrap text-gray-900 hover:bg-gray-50"
        >
          <CalendarDays className="size-[18px] text-gray-700" />
          {text}
          {(from || to) && (
            <span
              role="button"
              tabIndex={0}
              aria-label="Clear dates"
              onClick={(e) => {
                e.stopPropagation();
                onChange("", "");
              }}
              className="-mr-1 ml-auto rounded p-0.5 text-gray-400 hover:text-gray-700"
            >
              <X className="size-3.5" />
            </span>
          )}
        </button>
      )}
      panelClassName="w-72 p-4"
    >
      {(close) => (
        <div className="space-y-3">
          <label className="block text-xs font-medium text-gray-700">
            From
            <input
              type="date"
              value={draftFrom}
              max={draftTo || undefined}
              onChange={(e) => setDraftFrom(e.target.value)}
              className="mt-1 h-10 w-full rounded-lg border border-gray-200 px-3 text-sm"
            />
          </label>
          <label className="block text-xs font-medium text-gray-700">
            To
            <input
              type="date"
              value={draftTo}
              min={draftFrom || undefined}
              onChange={(e) => setDraftTo(e.target.value)}
              className="mt-1 h-10 w-full rounded-lg border border-gray-200 px-3 text-sm"
            />
          </label>
          <div className="flex justify-end gap-2 pt-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                onChange("", "");
                close();
              }}
            >
              Clear
            </Button>
            <Button
              size="sm"
              onClick={() => {
                onChange(draftFrom, draftTo);
                close();
              }}
            >
              Apply
            </Button>
          </div>
        </div>
      )}
    </Popover>
  );
}

export interface PickerOption {
  value: string;
  label: string;
  sub?: string;
  icon?: ReactNode;
}

/** A searchable single-choice list. `load(q)` fetches the options for a query. */
export function Picker({
  value,
  valueLabel,
  onChange,
  load,
  placeholder = "Select…",
  searchPlaceholder = "Search…",
  className,
  buttonClassName,
  disabled,
  allowClear,
}: {
  value: string | null;
  valueLabel?: string | null;
  onChange: (option: PickerOption | null) => void;
  load: (q: string) => Promise<PickerOption[]>;
  placeholder?: string;
  searchPlaceholder?: string;
  className?: string;
  buttonClassName?: string;
  disabled?: boolean;
  allowClear?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 250);
  const [options, setOptions] = useState<PickerOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadRef
      .current(debounced)
      .then((o) => !cancelled && setOptions(o))
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open, debounced]);

  return (
    <Popover
      className={className}
      open={open}
      onOpenChange={setOpen}
      panelClassName="w-full min-w-64 p-0"
      trigger={({ toggle }) => (
        <button
          type="button"
          disabled={disabled}
          onClick={toggle}
          className={cn(
            "flex h-10 w-full items-center gap-2 rounded-lg border border-transparent bg-field px-3.5 text-left text-sm disabled:opacity-60",
            buttonClassName,
          )}
        >
          <span className={cn("min-w-0 flex-1 truncate", !value && "text-gray-400")}>
            {value ? (valueLabel ?? value) : placeholder}
          </span>
          {allowClear && value ? (
            <span
              role="button"
              tabIndex={0}
              aria-label="Clear"
              onClick={(e) => {
                e.stopPropagation();
                onChange(null);
              }}
              className="rounded p-0.5 text-gray-400 hover:text-gray-700"
            >
              <X className="size-3.5" />
            </span>
          ) : (
            <ChevronDown className="size-4 text-gray-500" />
          )}
        </button>
      )}
    >
      {(close) => (
        <div>
          <div className="relative border-b border-line p-2">
            <Search className="pointer-events-none absolute top-1/2 left-5 size-4 -translate-y-1/2 text-gray-400" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={searchPlaceholder}
              className="h-9 w-full rounded-lg border border-gray-200 pr-3 pl-9 text-sm outline-none focus:border-brand-300"
            />
          </div>
          <ul className="scrollbar-thin max-h-64 overflow-y-auto p-1.5" role="listbox">
            {loading && (
              <li className="flex justify-center py-4">
                <Loader2 className="size-4 animate-spin text-gray-400" />
              </li>
            )}
            {!loading && error != null && <li className="px-3 py-3 text-sm text-red-600">{errorMessage(error)}</li>}
            {!loading && !error && options.length === 0 && (
              <li className="px-3 py-3 text-sm text-gray-500">No matches.</li>
            )}
            {!loading &&
              options.map((o) => (
                <li key={o.value}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={o.value === value}
                    onClick={() => {
                      onChange(o);
                      close();
                    }}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-gray-800 hover:bg-gray-50",
                      o.value === value && "bg-gray-50",
                    )}
                  >
                    {o.icon}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{o.label}</span>
                      {o.sub && <span className="block truncate text-xs text-gray-500">{o.sub}</span>}
                    </span>
                    {o.value === value && <Check className="size-4 text-brand-500" />}
                  </button>
                </li>
              ))}
          </ul>
        </div>
      )}
    </Popover>
  );
}

/** A dashed drop zone that uploads to storage and hands back the public URL. */
export function FileDrop({
  value,
  onChange,
  accept,
  label = "Add image",
  kind = "image",
  className,
}: {
  value: string | null;
  onChange: (url: string | null) => void;
  accept: string;
  label?: string;
  kind?: "image" | "file";
  className?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      onChange(await uploadFile(file, setProgress));
    } catch (e) {
      setError(e);
    } finally {
      setProgress(null);
    }
  };

  const isImage = value && /\.(png|jpe?g|webp|gif)(\?|$)/i.test(value);

  return (
    <div className={className}>
      <div
        onClick={() => input.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          void pick(e.dataTransfer.files[0]);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        className={cn(
          "group relative flex min-h-40 items-center justify-center overflow-hidden rounded-lg border border-dashed border-gray-300 bg-white text-sm text-gray-700 transition-colors hover:border-brand-300",
          kind === "file" && "min-h-16",
        )}
      >
        {value && isImage ? (
          <>
            <img src={value} alt="" className="max-h-56 w-full object-contain" />
            <span className="absolute inset-0 flex items-center justify-center bg-gray-900/40 text-white opacity-0 transition-opacity group-hover:opacity-100">
              <ImagePlus className="size-8" />
            </span>
          </>
        ) : value ? (
          <span className="flex items-center gap-2 px-4 py-3 text-blue-600">
            <UploadCloud className="size-4" />
            <span className="truncate">{decodeURIComponent(value.split("/").pop() ?? value)}</span>
          </span>
        ) : (
          <span className="flex items-center gap-2 text-gray-700">
            <ImagePlus className="size-5" /> {label}
          </span>
        )}
        {progress !== null && (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-white/85 text-sm text-gray-700">
            <Loader2 className="size-5 animate-spin text-brand-500" />
            Uploading… {Math.round(progress * 100)}%
          </span>
        )}
      </div>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          void pick(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <div className="mt-1.5 flex items-center justify-between gap-2">
        {error != null ? <p className="text-xs text-red-600">{errorMessage(error)}</p> : <span />}
        {value && (
          <button type="button" onClick={() => onChange(null)} className="text-xs text-gray-500 hover:text-red-600">
            Remove
          </button>
        )}
      </div>
    </div>
  );
}
