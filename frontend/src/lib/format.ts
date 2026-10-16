const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function time(value: string | null | undefined): string {
  return value ? timeFmt.format(new Date(value)) : "–";
}

export function dateTime(value: string | null | undefined): string {
  return value ? dateTimeFmt.format(new Date(value)) : "–";
}

export function ago(value: string | null | undefined, now = Date.now()): string {
  if (!value) return "never";
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/[_\s]+/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function formatValue(value: unknown, unit?: string | null): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "number") {
    const text = Number.isInteger(value) ? value.toString() : value.toFixed(2);
    return unit ? `${text} ${unit}` : text;
  }
  if (typeof value === "string") return unit && /^-?\d/.test(value) ? `${value} ${unit}` : value;
  return JSON.stringify(value);
}

export function shortHash(value: string | null | undefined, length = 10): string {
  return value ? value.slice(0, length) : "–";
}
