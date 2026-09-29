/* Drawer (the right-hand panels: order, product, category) and Modal. Both
 * render into document.body, close on Escape and on a backdrop click, and
 * lock the page scroll while open. */
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { cn } from "@/lib/cn";

let openCount = 0;

function useOverlay(open: boolean, onClose: () => void) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    openCount += 1;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      openCount -= 1;
      if (openCount === 0) document.body.style.overflow = "";
      previouslyFocused?.focus?.();
    };
  }, [open]);

  return panel;
}

export function Drawer({
  open,
  onClose,
  eyebrow,
  title,
  footer,
  children,
  width = "max-w-[504px]",
}: {
  open: boolean;
  onClose: () => void;
  eyebrow?: ReactNode;
  title: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  width?: string;
}) {
  const panel = useOverlay(open, onClose);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-gray-900/45" onClick={onClose} aria-hidden />
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        className={cn("relative flex h-full w-full animate-slide-in flex-col bg-page shadow-2xl outline-none", width)}
      >
        <header className="flex items-start justify-between gap-4 px-5 pt-6 pb-4">
          <div className="min-w-0">
            {eyebrow && <p className="text-xs text-gray-500">{eyebrow}</p>}
            <h2 className="truncate text-xl font-semibold text-gray-900">{title}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
          >
            <X className="size-4" />
          </button>
        </header>
        <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto px-5 pb-5">{children}</div>
        {footer && <footer className="border-t border-line bg-page px-5 py-4">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

export function Modal({
  open,
  onClose,
  title,
  description,
  footer,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  const panel = useOverlay(open, onClose);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 animate-fade-in bg-gray-900/45" onClick={onClose} aria-hidden />
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        className={cn(
          "relative flex max-h-[90vh] w-full animate-pop-in flex-col rounded-2xl bg-white shadow-2xl outline-none",
          { sm: "max-w-sm", md: "max-w-md", lg: "max-w-2xl" }[size],
        )}
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            {description && <p className="mt-1 text-sm text-gray-500">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-2 flex size-8 shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100"
          >
            <X className="size-4" />
          </button>
        </div>
        {children && <div className="scrollbar-thin overflow-y-auto px-6 pt-4">{children}</div>}
        <div className="flex justify-end gap-3 px-6 pt-5 pb-5">{footer}</div>
      </div>
    </div>,
    document.body,
  );
}
