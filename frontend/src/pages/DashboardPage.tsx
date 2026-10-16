import {
  Activity,
  Ban,
  Fingerprint,
  Lock,
  Siren,
  Waypoints,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { errorMessage } from "../api/client";
import { useMetrics, useTimeseries } from "../api/queries";
import type { MetricsSummary, Severity, TrustState } from "../api/types";
import { ErrorNote, Panel, Spinner, StatusBadge } from "../components/ui/primitives";
import { time, titleCase } from "../lib/format";
import { CLASSIFICATION, SEVERITY, TRUST } from "../lib/status";

// Chart colors (validated with the dataviz palette checker against #111b2e):
// status trio passes CVD (ΔE 9.0) and normal-vision (ΔE 20.4) floors; dash patterns give a
// second, non-color channel. Single-series bars use one validated blue.
const STATUS_SERIES = [
  { key: "ACCEPTED", label: "Accepted", color: "#34d399", dash: undefined, width: 2 },
  { key: "HELD", label: "Held for review", color: "#f5b945", dash: "6 4", width: 2 },
  { key: "REJECTED", label: "Rejected", color: "#f04452", dash: "2 3", width: 2.5 },
] as const;
const DATA_BLUE = "#3987e5";
const AXIS = { fill: "#9aabc2", fontSize: 11 };
const GRID = "rgba(148,163,184,0.12)";
const tooltipStyle = {
  backgroundColor: "#16233a",
  border: "1px solid rgba(148,163,184,0.28)",
  borderRadius: 6,
  color: "#e2e8f0",
  fontSize: 12,
};

function StatTile({ label, value, icon: Icon, children, to }: { label: string; value: ReactNode; icon: typeof Activity; children?: ReactNode; to?: string }) {
  const body = (
    <div className="flex h-full flex-col gap-1.5 rounded-lg border border-line bg-surface p-3 transition-colors hover:border-line-strong">
      <div className="flex items-center gap-1.5 text-[12px] text-ink-muted">
        <Icon aria-hidden className="size-3.5 text-accent" />
        {label}
      </div>
      <div className="text-2xl leading-none font-semibold tabular">{value}</div>
      {children ? <div className="mt-auto flex flex-wrap gap-1 text-[11.5px] text-ink-muted">{children}</div> : null}
    </div>
  );
  return to ? (
    <Link to={to} className="block rounded-lg">
      {body}
    </Link>
  ) : (
    body
  );
}

function DataTable({ caption, columns, rows }: { caption: string; columns: string[]; rows: (string | number)[][] }) {
  return (
    <details className="mt-2 text-[12px]">
      <summary className="cursor-pointer text-ink-muted">Data table</summary>
      <table className="mt-1.5 w-full">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="text-left text-ink-muted">
            {columns.map((c) => (
              <th key={c} scope="col" className="py-1 pr-3 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-line">
              {row.map((cell, j) => (
                <td key={j} className="py-1 pr-3 tabular">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function DecisionsChart() {
  const { data = [], isPending } = useTimeseries(30);
  const points = data.map((p) => ({ ...p, label: time(p.minute).slice(0, 5) }));
  if (isPending) return <Spinner label="Loading telemetry" />;
  if (!points.length) return <p className="py-10 text-center text-[13px] text-ink-muted">No messages in the last 30 minutes. Is the generator paused?</p>;
  return (
    <>
      <div role="img" aria-label="Line chart of accepted, held and rejected device messages per minute over the last 30 minutes" className="h-60">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} minTickGap={24} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "rgba(148,163,184,0.4)" }} />
            <Legend wrapperStyle={{ fontSize: 12, color: "#9aabc2" }} />
            {STATUS_SERIES.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={s.width} strokeDasharray={s.dash} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DataTable
        caption="Messages per minute by decision"
        columns={["Minute", "Accepted", "Held", "Rejected"]}
        rows={points.map((p) => [p.label, p.ACCEPTED, p.HELD, p.REJECTED])}
      />
    </>
  );
}

function TrustChart({ metrics }: { metrics: MetricsSummary }) {
  const order: TrustState[] = ["AUTHENTICATED", "REGISTERED", "SUSPICIOUS", "QUARANTINED", "REVOKED", "OFFLINE", "UNREGISTERED"];
  const rows = order.map((state) => ({ state, label: TRUST[state].label, count: metrics.trust_distribution[state] ?? 0, color: TRUST[state].color }));
  return (
    <>
      <ul className="space-y-1.5" aria-label="Device identities by trust state">
        {rows.map((row) => {
          const s = TRUST[row.state];
          const max = Math.max(1, ...rows.map((r) => r.count));
          return (
            <li key={row.state} className="grid grid-cols-[8.5rem_1fr_2rem] items-center gap-2 text-[12.5px]">
              <span className="flex items-center gap-1.5 text-ink-muted">
                <s.icon aria-hidden className="size-3.5" style={{ color: s.color }} />
                {s.label}
              </span>
              <span className="h-3 rounded-sm bg-surface-2" aria-hidden>
                <span className="block h-full rounded-sm" style={{ width: `${(row.count / max) * 100}%`, backgroundColor: s.color, minWidth: row.count ? 4 : 0 }} />
              </span>
              <span className="text-right tabular">{row.count}</span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[11.5px] text-ink-faint">Registered is not trusted: a device must prove key possession to become authenticated.</p>
    </>
  );
}

function HorizontalBars({ title, rows, labelWidth = 150 }: { title: string; rows: { name: string; value: number }[]; labelWidth?: number }) {
  if (!rows.length) return <p className="py-8 text-center text-[13px] text-ink-muted">Nothing recorded in this baseline yet.</p>;
  return (
    <>
      <div role="img" aria-label={title} style={{ height: Math.max(120, rows.length * 30 + 24) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 36, bottom: 4, left: 0 }} barCategoryGap={6}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
            <YAxis type="category" dataKey="name" width={labelWidth} tick={{ ...AXIS, fill: "#c8d3e1" }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(148,163,184,0.08)" }} />
            <Bar dataKey="value" name="Count" fill={DATA_BLUE} radius={[0, 4, 4, 0]} isAnimationActive={false} maxBarSize={18}>
              {rows.map((r) => (
                <Cell key={r.name} fill={DATA_BLUE} />
              ))}
              <LabelList dataKey="value" position="right" style={{ fill: "#e2e8f0", fontSize: 11 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <DataTable caption={title} columns={["Category", "Count"]} rows={rows.map((r) => [r.name, r.value])} />
    </>
  );
}

export default function DashboardPage() {
  const { data: metrics, isPending, error, refetch } = useMetrics();
  if (isPending) return <Spinner label="Loading metrics" />;
  if (error || !metrics) return <ErrorNote error={errorMessage(error)} onRetry={() => void refetch()} />;
  const severities: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
  const last = metrics.telemetry.last_hour;
  const reasons = Object.entries(metrics.rejections_by_reason)
    .map(([name, value]) => ({ name: titleCase(name), value }))
    .sort((a, b) => b.value - a.value);
  const classes = Object.entries(metrics.alerts.by_classification)
    .map(([name, value]) => ({ name: CLASSIFICATION[name as keyof typeof CLASSIFICATION]?.label ?? name, value: value ?? 0 }))
    .sort((a, b) => b.value - a.value);
  const denials = Object.values(metrics.policy_denials).reduce((a, b) => a + b, 0);

  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto max-w-[1500px] space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-lg font-semibold">Security dashboard</h1>
          <p className="text-[12px] text-ink-muted">
            Baseline #{metrics.epoch} · computed from backend records at {time(metrics.generated_at)}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          <StatTile label="Device identities" value={metrics.inventory.device_identities} icon={Fingerprint} to="/">
            <span className="text-ok">{metrics.trust_distribution.AUTHENTICATED ?? 0} authenticated</span>
            {metrics.trust_distribution.SUSPICIOUS ? <span className="text-warn">· {metrics.trust_distribution.SUSPICIOUS} suspicious</span> : null}
            {metrics.inventory.discovered_unregistered ? <span className="text-violet">· {metrics.inventory.discovered_unregistered} unregistered</span> : null}
          </StatTile>
          <StatTile label="Open incidents" value={metrics.incidents.open} icon={Siren} to="/incidents">
            {severities
              .filter((s) => metrics.incidents.open_by_severity[s])
              .map((s) => (
                <StatusBadge key={s} size="xs" status={{ ...SEVERITY[s], label: `${metrics.incidents.open_by_severity[s]} ${SEVERITY[s].label}` }} />
              ))}
          </StatTile>
          <StatTile label="Messages (last hour)" value={last.ACCEPTED + last.HELD + last.REJECTED} icon={Activity}>
            <span className="text-ok">{last.ACCEPTED} accepted</span>
            <span className="text-warn">· {last.HELD} held</span>
            <span className="text-crit">· {last.REJECTED} rejected</span>
          </StatTile>
          <StatTile label="Policy denials" value={denials} icon={Ban} to="/policies">
            <span>{metrics.policy_denials.NETWORK_FLOW ?? 0} flows · {metrics.policy_denials.DEVICE_COMMAND ?? 0} commands</span>
          </StatTile>
          <StatTile label="Communication anomalies" value={metrics.communication_anomalies} icon={Waypoints}>
            <span>{metrics.blocked_flows} flows blocked</span>
          </StatTile>
          <StatTile label="Containment" value={metrics.containment.assets_contained.length} icon={Lock}>
            <span>{metrics.containment.active_containment_policies} active containment policies</span>
          </StatTile>
        </div>
        <div className="grid gap-3 xl:grid-cols-3">
          <Panel title="Message decisions per minute (last 30 min)" icon={Activity} className="xl:col-span-2">
            <DecisionsChart />
          </Panel>
          <Panel title="Trust state of device identities" icon={Fingerprint}>
            <TrustChart metrics={metrics} />
          </Panel>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <Panel title="Why messages were rejected or held" icon={Ban}>
            <HorizontalBars title="Rejected or held messages by reason code" rows={reasons} labelWidth={160} />
          </Panel>
          <Panel title="Alerts by classification" icon={Siren}>
            <HorizontalBars title="Alerts by classification" rows={classes} labelWidth={190} />
            <p className="mt-1 text-[11.5px] text-ink-faint">Confirmed violations are evaluated against explicit policy; suspected anomalies have benign explanations.</p>
          </Panel>
        </div>
        <Panel title="Recent security events" icon={Siren} bodyClassName="overflow-x-auto p-0">
          {metrics.recent_alerts.length ? (
            <table className="w-full text-[12.5px]">
              <caption className="sr-only">Most recent alerts</caption>
              <thead className="text-left text-[11px] tracking-wide text-ink-muted uppercase">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Time</th>
                  <th scope="col" className="px-3 py-2 font-medium">Rule</th>
                  <th scope="col" className="px-3 py-2 font-medium">Detection</th>
                  <th scope="col" className="px-3 py-2 font-medium">Classification</th>
                  <th scope="col" className="px-3 py-2 font-medium">Severity</th>
                  <th scope="col" className="px-3 py-2 font-medium">Subject</th>
                  <th scope="col" className="px-3 py-2 font-medium">Incident</th>
                </tr>
              </thead>
              <tbody>
                {metrics.recent_alerts.map((a) => (
                  <tr key={a.id} className="border-t border-line">
                    <td className="px-3 py-1.5 whitespace-nowrap tabular text-ink-muted">{time(a.created_at)}</td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{a.rule_id}</td>
                    <td className="px-3 py-1.5">{a.title}</td>
                    <td className="px-3 py-1.5">
                      <StatusBadge size="xs" status={{ ...CLASSIFICATION[a.classification], label: CLASSIFICATION[a.classification].short }} />
                    </td>
                    <td className="px-3 py-1.5">
                      <StatusBadge size="xs" status={SEVERITY[a.severity]} />
                    </td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{a.subject_ref}</td>
                    <td className="px-3 py-1.5">
                      {a.incident_id ? (
                        <Link className="text-accent-strong hover:underline" to={`/incidents/${a.incident_id}`}>
                          Open
                        </Link>
                      ) : (
                        <span className="text-ink-faint">–</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="p-4 text-[13px] text-ink-muted">No alerts in this baseline. Run a scenario to exercise the detections.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
