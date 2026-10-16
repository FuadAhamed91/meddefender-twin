import {
  Activity,
  Boxes,
  Cable,
  Eye,
  Layers,
  Map as MapIcon,
  Search,
  ShieldAlert,
  Tags,
  TriangleAlert,
  Waypoints,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useIncidents, useZones } from "../api/queries";
import type { LiveEvent, Severity } from "../api/types";
import { cx, EmptyState, Panel, StatusBadge } from "../components/ui/primitives";
import { AssetInspector } from "../features/inspector/AssetInspector";
import { time } from "../lib/format";
import { INCIDENT_STATUS, OUTCOME, PATH_CLASS, SEVERITY, TRUST, trustStyle } from "../lib/status";
import { type Overlays, useTwinStore } from "../state/twin";
import { Minimap } from "../twin/Minimap";
import { TwinCanvas } from "../twin/TwinCanvas";

const OVERLAY_ITEMS: { key: keyof Overlays; label: string; icon: typeof Layers; hint: string }[] = [
  { key: "network", label: "Network flows", icon: Waypoints, hint: "Modeled paths, colored by current policy decision" },
  { key: "dependencies", label: "Dependencies", icon: Boxes, hint: "What relies on what (separate from connectivity)" },
  { key: "topology", label: "L2 topology", icon: Cable, hint: "Physical attachment only; not a permission" },
  { key: "zones", label: "Zones", icon: MapIcon, hint: "Security zones and network segments" },
  { key: "labels", label: "Asset labels", icon: Tags, hint: "Show asset IDs on markers" },
];

function ZoneNav() {
  const { data: zones = [] } = useZones();
  const requestFocus = useTwinStore((s) => s.requestFocus);
  return (
    <div className="flex flex-wrap gap-1">
      <button type="button" onClick={() => requestFocus("overview")} className="cursor-pointer rounded-md border border-line-strong px-2 py-1 text-[12px] hover:bg-surface-2">
        Whole floor
      </button>
      {zones.map((zone) => (
        <button
          key={zone.id}
          type="button"
          onClick={() => requestFocus("zone", [zone.id])}
          className="flex cursor-pointer items-center gap-1.5 rounded-md border border-line-strong px-2 py-1 text-[12px] hover:bg-surface-2"
        >
          <span aria-hidden className="size-2 rounded-sm" style={{ backgroundColor: zone.color }} />
          {zone.name}
        </button>
      ))}
    </div>
  );
}

function ViewStyle() {
  const mode = useTwinStore((s) => s.viewMode);
  const setMode = useTwinStore((s) => s.setViewMode);
  const options = [
    { id: "holographic" as const, label: "Holographic", hint: "Security view: translucent architecture, glowing edges" },
    { id: "realistic" as const, label: "Realistic", hint: "Architectural view: lit materials and furniture" },
  ];
  return (
    <div role="radiogroup" aria-label="View style" className="mb-2 grid grid-cols-2 gap-0.5 rounded-md border border-line-strong bg-canvas p-0.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={mode === o.id}
          title={o.hint}
          onClick={() => setMode(o.id)}
          className={cx(
            "cursor-pointer rounded px-2 py-1 text-[12px] transition-colors",
            mode === o.id ? "bg-accent-soft font-medium text-accent-strong" : "text-ink-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function AssetSearch() {
  const assets = useTwinStore((s) => s.assets);
  const select = useTwinStore((s) => s.select);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  const selectedId = useTwinStore((s) => s.selectedId);
  const [query, setQuery] = useState("");
  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return Object.values(assets)
      .filter((a) => a.is_active)
      .filter((a) => !q || a.id.toLowerCase().includes(q) || a.display_name.toLowerCase().includes(q) || (a.ip_address ?? "").includes(q))
      .sort((a, b) => Number(b.open_incident_count > 0) - Number(a.open_incident_count > 0) || a.id.localeCompare(b.id));
  }, [assets, query]);
  return (
    <div className="flex min-h-0 flex-col gap-2">
      <label className="relative block">
        <span className="sr-only">Search assets</span>
        <Search aria-hidden className="pointer-events-none absolute top-2 left-2 size-4 text-ink-faint" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ID, name or address"
          className="h-8 w-full rounded-md border border-line-strong bg-canvas pr-2 pl-8 text-[13px] placeholder:text-ink-faint focus:border-accent focus:outline-none"
        />
      </label>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1" aria-label="Assets">
        {list.map((asset) => {
          const trust = trustStyle(asset.trust_state);
          const Icon = trust.icon;
          return (
            <li key={asset.id}>
              <button
                type="button"
                aria-pressed={selectedId === asset.id}
                onClick={() => {
                  select(asset.id);
                  if (!asset.is_logical) requestFocus("asset", [asset.id]);
                }}
                className={cx(
                  "flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1 text-left text-[12.5px]",
                  selectedId === asset.id ? "bg-accent-soft text-ink" : "hover:bg-surface-2",
                )}
              >
                <Icon aria-hidden className="size-3.5 shrink-0" style={{ color: trust.color }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[11.5px]">{asset.id}</span>
                  <span className="block truncate text-[11px] text-ink-muted">
                    {trust.label}
                    {asset.containment_state !== "NONE" ? ` · ${asset.containment_state.toLowerCase()}` : ""}
                  </span>
                </span>
                {asset.open_incident_count ? (
                  <span className="rounded bg-high/20 px-1 text-[10.5px] text-high tabular" title="Open incidents">
                    {asset.open_incident_count}
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const FEED_LABELS: Record<string, string> = {
  "alert.created": "Alert",
  "incident.created": "Incident opened",
  "incident.updated": "Incident updated",
  "trust.changed": "Trust changed",
  "policy.decision": "Policy decision",
  "network.flow_observed": "Flow observed",
  "telemetry.processed": "Message",
  "asset.discovered": "Endpoint discovered",
  "containment.applied": "Containment applied",
  "command.delivered": "Command delivered",
  "simulation.reset": "Baseline reset",
  "simulation.run_started": "Scenario started",
  "simulation.run_completed": "Scenario finished",
  "asset.updated": "Asset updated",
  "enrollment.requested": "Enrollment requested",
};

function describe(event: LiveEvent): { text: string; severity?: Severity; asset?: string } {
  const p = (event.payload ?? {}) as Record<string, unknown>;
  switch (event.type) {
    case "alert.created":
      return { text: `${p.rule_id} ${p.title} · ${p.subject_ref}`, severity: p.severity as Severity, asset: (p.asset_id as string) ?? undefined };
    case "trust.changed":
      return { text: `${p.asset_id}: ${p.from} → ${p.to}`, asset: p.asset_id as string };
    case "telemetry.processed":
      return { text: `${p.claimed_device_id ?? "unknown"} ${String(p.message_type ?? "").toLowerCase()} ${String(p.decision).toLowerCase()} (${p.reason_code})`, asset: (p.asset_id as string) ?? undefined };
    case "policy.decision":
      return { text: `${p.source} → ${p.destination} (${p.service_or_action}): ${String(p.outcome).toLowerCase().replaceAll("_", " ")}` };
    case "network.flow_observed":
      return { text: `${p.source} → ${p.destination} (${p.service}) ${String(p.outcome).toLowerCase()}${p.new_path ? " · new path" : ""}` };
    case "incident.created":
    case "incident.updated":
      return { text: `${p.reference}: ${p.title} (${String(p.status).toLowerCase()})`, severity: p.severity as Severity };
    case "asset.discovered":
      return { text: `${p.asset_id} (${p.ip_address}) in ${p.network_zone_id}`, asset: p.asset_id as string };
    case "simulation.run_completed":
      return { text: `Scenario ${p.scenario_id}: ${p.expectations_met}/${p.expectations_total} expectations met` };
    default:
      return { text: JSON.stringify(p).slice(0, 120) };
  }
}

function EventFeed() {
  const feed = useTwinStore((s) => s.feed);
  const select = useTwinStore((s) => s.select);
  if (!feed.length) {
    return (
      <EmptyState icon={Activity} title="Quiet so far">
        Live security events appear here. Run a scenario to see detections.
      </EmptyState>
    );
  }
  return (
    <ol className="space-y-1" aria-label="Live security events">
      {feed.slice(0, 60).map((event, index) => {
        const d = describe(event);
        const sev = d.severity ? SEVERITY[d.severity] : null;
        const Icon = sev?.icon ?? Activity;
        return (
          <li key={`${event.id ?? index}-${event.type}`} className="animate-fade-in">
            <button
              type="button"
              disabled={!d.asset}
              onClick={() => d.asset && select(d.asset)}
              className="flex w-full cursor-pointer items-start gap-2 rounded px-1.5 py-1 text-left text-[12px] hover:bg-surface-2 disabled:cursor-default disabled:hover:bg-transparent"
            >
              <Icon aria-hidden className="mt-0.5 size-3.5 shrink-0" style={{ color: sev?.color ?? "#9aabc2" }} />
              <span className="min-w-0 flex-1">
                <span className="flex justify-between gap-2 text-[11px] text-ink-muted">
                  <span>{FEED_LABELS[event.type] ?? event.type}</span>
                  <span className="tabular">{time(event.created_at)}</span>
                </span>
                <span className="block wrap-anywhere text-ink">{d.text}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function Legend() {
  return (
    <div className="space-y-2 text-[11.5px] text-ink-muted">
      <div>
        <p className="mb-1 font-semibold tracking-wider uppercase">Trust</p>
        <ul className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          {(["AUTHENTICATED", "REGISTERED", "SUSPICIOUS", "QUARANTINED", "REVOKED", "OFFLINE", "UNREGISTERED"] as const).map((k) => {
            const s = TRUST[k];
            return (
              <li key={k} className="flex items-center gap-1">
                <s.icon aria-hidden className="size-3" style={{ color: s.color }} />
                {s.label}
              </li>
            );
          })}
        </ul>
      </div>
      <div>
        <p className="mb-1 font-semibold tracking-wider uppercase">Flows</p>
        <ul className="space-y-0.5">
          {(["PERMITTED", "BLOCKED", "ALLOWED_MONITOR_ONLY", "TOPOLOGY"] as const).map((k) => (
            <li key={k} className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-0.5 w-5" style={{ background: OUTCOME[k].color, opacity: k === "TOPOLOGY" ? 0.6 : 1 }} />
              {OUTCOME[k].label}
            </li>
          ))}
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-5 border-t-2 border-dashed border-warn" />
            Observed, not in baseline
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-5 border-t-2 border-dotted border-dep" />
            Dependency
          </li>
        </ul>
      </div>
    </div>
  );
}

function AttackPathBanner() {
  const result = useTwinStore((s) => s.attackPath);
  const plan = useTwinStore((s) => s.planPreview);
  const setAttackPath = useTwinStore((s) => s.setAttackPath);
  const setPlanPreview = useTwinStore((s) => s.setPlanPreview);
  if (!result) return null;
  const counts = { DEMONSTRATED: 0, PERMITTED: 0, HYPOTHETICAL: 0 };
  result.reachable_assets.forEach((r) => (counts[r.classification] += 1));
  return (
    <div className="pointer-events-auto max-w-md rounded-lg border border-high/50 bg-canvas/95 p-3 text-[12.5px] shadow-xl">
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold">
          {plan ? `With plan: ${plan.name}` : "Attack paths"} from <span className="font-mono text-high">{result.entry_asset_id}</span>
        </p>
        <button
          type="button"
          aria-label="Clear attack-path view"
          onClick={() => {
            setAttackPath(null);
            setPlanPreview(null);
          }}
          className="cursor-pointer rounded p-0.5 text-ink-muted hover:text-ink"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>
      <p className="mt-1 text-ink-muted">
        {result.reachable_assets.length} reachable over permitted flows · {result.blocked_edges_from_entry.length} blocked from entry ·{" "}
        {result.nearby_unreachable.length} nearby but unreachable
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {(Object.keys(counts) as (keyof typeof counts)[]).map((k) => (
          <li key={k}>
            <StatusBadge status={{ ...PATH_CLASS[k], label: `${PATH_CLASS[k].label} ${counts[k]}` }} size="xs" />
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] text-ink-faint">Assumes the entry asset is attacker-controlled. Multi-hop paths need further compromise and are not demonstrated.</p>
    </div>
  );
}

function SituationPanel() {
  const { data: open = [] } = useIncidents({ open_only: true });
  const assets = useTwinStore((s) => s.assets);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  const abnormal = Object.values(assets).filter((a) => ["SUSPICIOUS", "QUARANTINED", "REVOKED", "UNREGISTERED"].includes(a.trust_state ?? "") && a.is_active);
  return (
    <div className="space-y-4 p-3">
      <div>
        <h2 className="text-[13px] font-semibold">Situation</h2>
        <p className="text-[12.5px] text-ink-muted">Select an asset in the twin or the list to inspect its backend state.</p>
      </div>
      <section aria-labelledby="open-incidents">
        <h3 id="open-incidents" className="mb-1.5 text-[11px] font-semibold tracking-wider text-ink-muted uppercase">
          Open incidents ({open.length})
        </h3>
        {open.length === 0 ? (
          <p className="text-[12.5px] text-ink-muted">None. Run a scenario from the Scenarios page to exercise the controls.</p>
        ) : (
          <ul className="space-y-1.5">
            {open.slice(0, 8).map((incident) => (
              <li key={incident.id} className="rounded-md border border-line bg-surface-2 p-2 text-[12.5px]">
                <div className="flex items-center justify-between gap-2">
                  <Link to={`/incidents/${incident.id}`} className="font-mono text-[11.5px] text-accent-strong hover:underline">
                    {incident.reference}
                  </Link>
                  <StatusBadge status={SEVERITY[incident.severity]} size="xs" />
                </div>
                <p className="mt-0.5 leading-snug">{incident.title}</p>
                <div className="mt-1 flex items-center justify-between">
                  <StatusBadge status={INCIDENT_STATUS[incident.status]} size="xs" />
                  {incident.primary_asset_id ? (
                    <button type="button" onClick={() => requestFocus("asset", [incident.primary_asset_id!])} className="cursor-pointer text-[11.5px] text-ink-muted hover:text-ink">
                      Locate
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="abnormal-assets">
        <h3 id="abnormal-assets" className="mb-1.5 text-[11px] font-semibold tracking-wider text-ink-muted uppercase">
          Assets needing attention ({abnormal.length})
        </h3>
        {abnormal.length ? (
          <ul className="flex flex-wrap gap-1.5">
            {abnormal.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => useTwinStore.getState().select(a.id)} className="cursor-pointer">
                  <StatusBadge status={{ ...trustStyle(a.trust_state), label: a.id }} size="xs" />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[12.5px] text-ink-muted">All identities are in expected states.</p>
        )}
      </section>
    </div>
  );
}

export default function TwinPage() {
  const ready = useTwinStore((s) => s.ready);
  const selectedId = useTwinStore((s) => s.selectedId);
  const overlays = useTwinStore((s) => s.overlays);
  const toggleOverlay = useTwinStore((s) => s.toggleOverlay);
  const mappingIssues = useTwinStore((s) => s.mappingIssues);
  const counters = useTwinStore((s) => s.counters);
  const highlight = useTwinStore((s) => s.highlight);
  const setHighlight = useTwinStore((s) => s.setHighlight);
  const assets = useTwinStore((s) => s.assets);
  const [fallback, setFallback] = useState(false);
  const mapped = Object.values(assets).filter((a) => a.twin_node).length;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 grid-rows-[minmax(22rem,1fr)_auto] gap-2 overflow-y-auto p-2 lg:grid-cols-[17rem_minmax(0,1fr)_23rem] lg:grid-rows-1 lg:overflow-hidden">
      <aside className="order-2 flex min-h-0 flex-col gap-2 lg:order-1" aria-label="Twin controls">
        <Panel title="Navigate" icon={MapIcon}>
          <ZoneNav />
        </Panel>
        <Panel title="Overlays" icon={Layers}>
          <ViewStyle />
          <fieldset>
            <legend className="sr-only">Overlay visibility</legend>
            <ul className="space-y-1">
              {OVERLAY_ITEMS.map((item) => (
                <li key={item.key}>
                  <label className="flex cursor-pointer items-center gap-2 text-[12.5px]" title={item.hint}>
                    <input type="checkbox" checked={overlays[item.key]} onChange={() => toggleOverlay(item.key)} className="size-3.5 accent-[#22c3d6]" />
                    <item.icon aria-hidden className="size-3.5 text-ink-muted" />
                    {item.label}
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
          <details className="mt-2">
            <summary className="cursor-pointer text-[12px] text-ink-muted">Legend</summary>
            <div className="mt-2">
              <Legend />
            </div>
          </details>
        </Panel>
        <Panel title="Assets" icon={Eye} className="min-h-[14rem] flex-1" bodyClassName="flex min-h-0 flex-col p-2">
          <AssetSearch />
        </Panel>
      </aside>

      <section className="relative order-1 min-h-[22rem] overflow-hidden rounded-lg border border-line bg-canvas lg:order-2" aria-label="Digital twin view">
        {ready ? <TwinCanvas onModelFallback={() => setFallback(true)} /> : <div className="p-4 text-[13px] text-ink-muted">Loading twin state…</div>}
        <div className="pointer-events-none absolute inset-x-2 top-2 flex flex-wrap items-start justify-between gap-2">
          <div className="pointer-events-auto flex flex-col gap-2">
            <AttackPathBanner />
            {highlight ? (
              <div className="flex max-w-md items-center gap-2 rounded-md border border-accent/50 bg-canvas/95 px-2.5 py-1.5 text-[12.5px] shadow-lg">
                <span>{highlight.label}</span>
                <button type="button" aria-label="Clear highlight" onClick={() => setHighlight(null)} className="cursor-pointer text-ink-muted hover:text-ink">
                  <X aria-hidden className="size-3.5" />
                </button>
              </div>
            ) : null}
          </div>
          <div className="rounded-md border border-line bg-canvas/85 px-2.5 py-1.5 text-[11.5px] text-ink-muted shadow-lg" aria-label="Messages since this view opened">
            <span className="mr-2">This session:</span>
            <span className="text-ok tabular">{counters.accepted} accepted</span> · <span className="text-warn tabular">{counters.held} held</span> ·{" "}
            <span className="text-crit tabular">{counters.rejected} rejected</span>
          </div>
        </div>
        <div className="pointer-events-none absolute right-2 bottom-2 hidden md:block">
          <Minimap />
        </div>
        <div className="pointer-events-none absolute bottom-2 left-2 flex flex-col gap-1">
          {fallback ? (
            <span className="pointer-events-auto flex items-center gap-1 rounded border border-warn/50 bg-canvas/95 px-2 py-1 text-[11.5px] text-warn">
              <TriangleAlert aria-hidden className="size-3.5" /> 3D model failed to load; showing procedural fallback
            </span>
          ) : null}
          <span
            className={cx("rounded border bg-canvas/85 px-2 py-1 text-[11px]", mappingIssues.length ? "border-crit/60 text-crit" : "border-line text-ink-muted")}
            title={mappingIssues.join("\n") || "Every backend asset with a twin node is present in the model"}
          >
            {mappingIssues.length ? (
              <>
                <ShieldAlert aria-hidden className="mr-1 inline size-3" />
                Twin mapping: {mappingIssues.length} issue(s)
              </>
            ) : (
              <>Twin mapping verified · {mapped} assets</>
            )}
          </span>
        </div>
      </section>

      <aside className="order-3 flex min-h-[24rem] flex-col overflow-hidden rounded-lg border border-line bg-surface" aria-label="Asset inspector">
        {selectedId ? <AssetInspector key={selectedId} assetId={selectedId} /> : <SituationPanel />}
      </aside>

      <Panel title="Live events" icon={Activity} className="order-4 max-h-80 lg:hidden" bodyClassName="overflow-y-auto p-2">
        <EventFeed />
      </Panel>
      <div className="hidden" aria-hidden>
        <EventFeed />
      </div>
    </div>
  );
}

export { EventFeed };
