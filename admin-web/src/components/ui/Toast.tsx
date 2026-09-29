import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";

import { cn } from "@/lib/cn";

type ToastTone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: ToastTone;
  message: ReactNode;
}

const ToastContext = createContext<(message: ReactNode, tone?: ToastTone) => void>(() => {});

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (message: ReactNode, tone: ToastTone = "success") => {
      const id = nextId++;
      setItems((all) => [...all.slice(-3), { id, tone, message }]);
      setTimeout(() => dismiss(id), tone === "error" ? 7000 : 4000);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={push}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-full max-w-sm flex-col gap-2">
          {items.map((t) => (
            <div
              key={t.id}
              role="status"
              className="pointer-events-auto flex animate-pop-in items-start gap-3 rounded-xl border border-line bg-white p-3.5 shadow-lg"
            >
              {t.tone === "success" ? (
                <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-green-600" />
              ) : t.tone === "error" ? (
                <XCircle className="mt-0.5 size-5 shrink-0 text-red-500" />
              ) : (
                <Info className="mt-0.5 size-5 shrink-0 text-blue-500" />
              )}
              <div className={cn("flex-1 text-sm", t.tone === "error" ? "text-red-700" : "text-gray-800")}>
                {t.message}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="text-gray-400 hover:text-gray-700"
                aria-label="Dismiss"
              >
                <X className="size-4" />
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
