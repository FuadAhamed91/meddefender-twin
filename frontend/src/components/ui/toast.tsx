import { CircleCheck, CircleX, Info, X } from "lucide-react";
import { create } from "zustand";
import { cx } from "./primitives";

export interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
}

interface ToastStore {
  toasts: Toast[];
  push: (kind: Toast["kind"], message: string) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToasts = create<ToastStore>((set) => ({
  toasts: [],
  push: (kind, message) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { id, kind, message }].slice(-4) }));
    window.setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), kind === "error" ? 8000 : 4500);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  success: (message: string) => useToasts.getState().push("success", message),
  error: (message: string) => useToasts.getState().push("error", message),
  info: (message: string) => useToasts.getState().push("info", message),
};

const ICONS = { success: CircleCheck, error: CircleX, info: Info };
const COLORS = { success: "text-ok", error: "text-crit", info: "text-accent" };

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div aria-live="polite" role="status" className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(92vw,24rem)] flex-col gap-2">
      {toasts.map((t) => {
        const Icon = ICONS[t.kind];
        return (
          <div key={t.id} className="pointer-events-auto flex items-start gap-2 rounded-md border border-line-strong bg-surface-2 p-3 text-[13px] text-ink shadow-xl animate-fade-in">
            <Icon aria-hidden className={cx("mt-0.5 size-4 shrink-0", COLORS[t.kind])} />
            <p className="min-w-0 flex-1 wrap-anywhere">{t.message}</p>
            <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(t.id)} className="cursor-pointer rounded p-0.5 text-ink-muted hover:text-ink">
              <X aria-hidden className="size-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
