import { LoaderCircle, type LucideIcon, X } from "lucide-react";
import {
  type ButtonHTMLAttributes,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type { StatusStyle } from "../../lib/status";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** Status badge: icon + text + color. Optional pulse for fresh, actionable states. */
export function StatusBadge({
  status,
  size = "sm",
  pulse = false,
  title,
  className,
}: {
  status: StatusStyle;
  size?: "xs" | "sm";
  pulse?: boolean;
  title?: string;
  className?: string;
}) {
  const Icon = status.icon;
  return (
    <span
      title={title ?? status.description}
      className={cx(
        "inline-flex max-w-full items-center gap-1 rounded-md border font-medium whitespace-nowrap",
        size === "xs" ? "px-1.5 py-px text-[11px]" : "px-2 py-0.5 text-xs",
        className,
      )}
      style={{ color: status.color, borderColor: `${status.color}55`, backgroundColor: `${status.color}14` }}
    >
      <Icon aria-hidden className={cx("shrink-0", size === "xs" ? "size-3" : "size-3.5", pulse && "animate-pulse-ring rounded-full")} />
      <span className="truncate">{status.label}</span>
    </span>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "secondary",
  icon: Icon,
  loading = false,
  size = "md",
  children,
  className,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  icon?: LucideIcon;
  loading?: boolean;
  size?: "sm" | "md";
}) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-canvas hover:bg-accent-strong border-transparent font-semibold",
    secondary: "bg-surface-2 text-ink hover:bg-surface-3 border-line-strong",
    ghost: "bg-transparent text-ink-muted hover:text-ink hover:bg-surface-2 border-transparent",
    danger: "bg-crit/15 text-crit hover:bg-crit/25 border-crit/40 font-semibold",
  };
  return (
    <button
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-md border transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-45",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        styles[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle aria-hidden className="size-4 animate-spin" /> : Icon ? <Icon aria-hidden className="size-4" /> : null}
      {children}
    </button>
  );
}

export function Panel({
  title,
  icon: Icon,
  actions,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  const headingId = useId();
  return (
    <section
      id={id}
      aria-labelledby={title ? headingId : undefined}
      className={cx("flex min-h-0 flex-col rounded-lg border border-line bg-surface", className)}
    >
      {title ? (
        <header className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
          <h2 id={headingId} className="flex min-w-0 items-center gap-2 text-[13px] font-semibold tracking-wide text-ink">
            {Icon ? <Icon aria-hidden className="size-4 shrink-0 text-accent" /> : null}
            <span className="truncate">{title}</span>
          </h2>
          {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cx("min-h-0 flex-1", bodyClassName ?? "p-3")}>{children}</div>
    </section>
  );
}

export function KeyValue({ label, children, mono = false }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[minmax(7rem,38%)_1fr] gap-2 py-1 text-[13px]">
      <dt className="text-ink-muted">{label}</dt>
      <dd className={cx("min-w-0 wrap-anywhere text-ink", mono && "font-mono text-[12px]")}>{children}</dd>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-8 text-center">
      <Icon aria-hidden className="size-6 text-ink-faint" />
      <p className="text-sm font-medium text-ink">{title}</p>
      {children ? <div className="max-w-sm text-[13px] text-ink-muted">{children}</div> : null}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-4 text-[13px] text-ink-muted">
      <LoaderCircle aria-hidden className="size-4 animate-spin text-accent" />
      {label}…
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-3 flex items-start justify-between gap-3 rounded-md border border-crit/40 bg-crit/10 p-3 text-[13px] text-ink">
      <span>{error}</span>
      {onRetry ? (
        <Button size="sm" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export interface TabItem {
  id: string;
  label: string;
  count?: number;
}

/** Accessible tabs (WAI-ARIA tablist with arrow-key navigation). */
export function Tabs({ items, value, onChange, label }: { items: TabItem[]; value: string; onChange: (id: string) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (event: React.KeyboardEvent, index: number) => {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = (index + delta + items.length) % items.length;
    onChange(items[next].id);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="flex gap-0.5 overflow-x-auto border-b border-line px-2">
      {items.map((item, index) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[index] = el;
            }}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.id)}
            onKeyDown={(e) => onKey(e, index)}
            className={cx(
              "relative -mb-px cursor-pointer border-b-2 px-2.5 py-2 text-[13px] whitespace-nowrap transition-colors",
              active ? "border-accent text-ink" : "border-transparent text-ink-muted hover:text-ink",
            )}
          >
            {item.label}
            {item.count !== undefined ? <span className="ml-1.5 rounded bg-surface-3 px-1 text-[11px] tabular text-ink-muted">{item.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

/** Modal confirmation for significant actions. Requires a typed justification. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  danger = false,
  requireJustification = true,
  loading = false,
  error,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  requireJustification?: boolean;
  loading?: boolean;
  error?: string | null;
  onConfirm: (justification: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState("");
  const fieldId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setText("");
      dialog.showModal();
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);
  const valid = !requireJustification || text.trim().length >= 3;
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-[min(92vw,34rem)] rounded-lg border border-line-strong bg-surface p-0 text-ink shadow-2xl backdrop:bg-black/60"
    >
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) onConfirm(text.trim());
        }}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button type="button" aria-label="Close dialog" onClick={onClose} className="cursor-pointer rounded p-1 text-ink-muted hover:bg-surface-2 hover:text-ink">
            <X aria-hidden className="size-4" />
          </button>
        </header>
        <div className="space-y-3 px-4 py-3 text-[13px] text-ink-muted">
          {children}
          {requireJustification ? (
            <div className="space-y-1">
              <label htmlFor={fieldId} className="block text-xs font-medium text-ink">
                Justification (recorded in the audit trail) <span aria-hidden className="text-crit">*</span>
              </label>
              <textarea
                id={fieldId}
                required
                minLength={3}
                rows={3}
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="w-full resize-none rounded-md border border-line-strong bg-canvas px-2.5 py-2 text-[13px] text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
                placeholder="Why is this action necessary?"
              />
            </div>
          ) : null}
          {error ? (
            <p role="alert" className="rounded-md border border-crit/40 bg-crit/10 px-2.5 py-2 text-ink">
              {error}
            </p>
          ) : null}
        </div>
        <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant={danger ? "danger" : "primary"} disabled={!valid} loading={loading}>
            {confirmLabel}
          </Button>
        </footer>
      </form>
    </dialog>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-1.5 mt-3 text-[11px] font-semibold tracking-wider text-ink-muted uppercase first:mt-0">{children}</h3>;
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[12px]", className)}>{children}</span>;
}
