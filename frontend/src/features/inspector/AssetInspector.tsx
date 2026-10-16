import {
  Boxes,
  Crosshair,
  KeyRound,
  RefreshCw,
  Route,
  ShieldCheck,
  ShieldOff,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { errorMessage } from "../../api/client";
import { useAssetDetail, useAttackPaths, useDeviceAction, useMe } from "../../api/queries";
import type { AssetDetail, MetricComparison, Relationship, Values } from "../../api/types";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorNote,
  KeyValue,
  Mono,
  SectionTitle,
  Spinner,
  StatusBadge,
  Tabs,
} from "../../components/ui/primitives";
import { toast } from "../../components/ui/toast";
import { ago, dateTime, formatValue, titleCase } from "../../lib/format";
import { CONTAINMENT, DECISION, INCIDENT_STATUS, OUTCOME, SEVERITY, trustStyle } from "../../lib/status";
import { useTwinStore } from "../../state/twin";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "state", label: "State" },
  { id: "security", label: "Security" },
  { id: "network", label: "Network" },
  { id: "dependencies", label: "Dependencies" },
  { id: "history", label: "History" },
];

export function AssetInspector({ assetId }: { assetId: string }) {
  const { data, isPending, error, refetch } = useAssetDetail(assetId);
  const [tab, setTab] = useState("overview");
  const select = useTwinStore((s) => s.select);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  const attackPath = useTwinStore((s) => s.attackPath);
  const setAttackPath = useTwinStore((s) => s.setAttackPath);
  const [analyze, setAnalyze] = useState(false);
  const paths = useAttackPaths(analyze ? assetId : null);
  useEffect(() => {
    if (analyze && paths.data) setAttackPath(paths.data);
  }, [analyze, paths.data, setAttackPath]);

  if (isPending) return <Spinner label={`Loading ${assetId}`} />;
  if (error || !data) return <ErrorNote error={errorMessage(error)} onRetry={() => void refetch()} />;
  const asset = data.asset;
  const trust = trustStyle(data.identity?.trust_state ?? null);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-line p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-mono text-[12px] text-accent-strong">{asset.id}</p>
            <h2 className="text-[15px] leading-snug font-semibold">{asset.display_name}</h2>
            <p className="text-[12px] text-ink-muted">
              {titleCase(asset.asset_type)} · {asset.is_logical ? "Logical service" : `${asset.room_name ?? "No room"} · ${asset.zone_name ?? "No zone"}`}
            </p>
          </div>
          <button type="button" aria-label="Close inspector" onClick={() => select(null)} className="cursor-pointer rounded p-1 text-ink-muted hover:bg-surface-2 hover:text-ink">
            <X aria-hidden className="size-4" />
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <StatusBadge status={trust} />
          {asset.containment_state !== "NONE" ? <StatusBadge status={CONTAINMENT[asset.containment_state]} /> : null}
          {asset.discovered ? <span className="rounded border border-violet/40 px-1.5 py-0.5 text-[11px] text-violet">Discovered on network</span> : null}
          <span className="rounded border border-line px-1.5 py-0.5 text-[11px] text-ink-muted">Criticality {titleCase(asset.criticality)}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {!asset.is_logical ? (
            <Button size="sm" icon={Crosshair} onClick={() => requestFocus("asset", [asset.id])}>
              Focus
            </Button>
          ) : null}
          {!asset.is_logical ? (
            <Button
              size="sm"
              icon={Route}
              loading={paths.isFetching}
              variant={attackPath?.entry_asset_id === asset.id ? "primary" : "secondary"}
              onClick={() => {
                if (attackPath?.entry_asset_id === asset.id) {
                  setAttackPath(null);
                  setAnalyze(false);
                } else {
                  setAnalyze(true);
                  void paths.refetch();
                }
              }}
            >
              {attackPath?.entry_asset_id === asset.id ? "Hide attack paths" : "Attack paths from here"}
            </Button>
          ) : null}
        </div>
      </div>
      <Tabs items={TABS} value={tab} onChange={setTab} label="Asset details" />
      <div className="min-h-0 flex-1 overflow-y-auto p-3" role="tabpanel">
        {tab === "overview" ? <Overview data={data} /> : null}
        {tab === "state" ? <StateView data={data} /> : null}
        {tab === "security" ? <SecurityView data={data} /> : null}
        {tab === "network" ? <NetworkView data={data} /> : null}
        {tab === "dependencies" ? <DependencyView data={data} /> : null}
        {tab === "history" ? <HistoryView data={data} /> : null}
      </div>
    </div>
  );
}

function Overview({ data }: { data: AssetDetail }) {
  const asset = data.asset;
  const current = data.incidents.filter((i) => i.current_epoch && i.status !== "RESOLVED");
  return (
    <div className="space-y-3">
      <p className="text-[13px] leading-relaxed text-ink-muted">{asset.description}</p>
      <dl>
        <KeyValue label="Asset kind">{titleCase(asset.asset_kind)}</KeyValue>
        {asset.ip_address ? <KeyValue label="Address (synthetic)" mono>{asset.ip_address}</KeyValue> : null}
        <KeyValue label="Network zone">{asset.zone_name ?? "–"}</KeyValue>
        <KeyValue label="Physical room">{asset.room_name ?? "–"}</KeyValue>
        {asset.position?.approximate ? <KeyValue label="Location">Approximate (attached via {asset.position.attached_via})</KeyValue> : null}
        <KeyValue label="Twin node" mono>{asset.twin_node ?? (asset.is_logical ? "Logical (not in 3D model)" : "Dynamic marker")}</KeyValue>
        <KeyValue label="Last seen">{ago(asset.last_seen_at)}</KeyValue>
      </dl>
      {data.identity ? (
        <div className="rounded-md border border-line bg-surface-2 p-2.5 text-[12.5px]">
          <p className="mb-1 font-medium">Why {trustStyle(data.identity.trust_state).label.toLowerCase()}?</p>
          <p className="text-ink-muted">{data.identity.trust_reason || trustStyle(data.identity.trust_state).description}</p>
          <p className="mt-1 text-[11.5px] text-ink-faint">Since {dateTime(data.identity.trust_changed_at)}</p>
        </div>
      ) : null}
      <SectionTitle>Open incidents ({current.length})</SectionTitle>
      {current.length === 0 ? (
        <p className="text-[13px] text-ink-muted">No open incident involves this asset.</p>
      ) : (
        <ul className="space-y-1.5">
          {current.map((incident) => (
            <li key={incident.id}>
              <Link to={`/incidents/${incident.id}`} className="flex items-center justify-between gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-2 text-[13px] hover:border-line-strong">
                <span className="min-w-0">
                  <span className="font-mono text-[11.5px] text-accent-strong">{incident.reference}</span>
                  <span className="block truncate">{incident.title}</span>
                  <span className="text-[11.5px] text-ink-muted">Role: {titleCase(incident.role)}</span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  <StatusBadge status={SEVERITY[incident.severity]} size="xs" />
                  <StatusBadge status={INCIDENT_STATUS[incident.status]} size="xs" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function fieldValue(values: Values | null | undefined, key: string): unknown {
  return values ? values[key] : undefined;
}

function StateView({ data }: { data: AssetDetail }) {
  const twin = data.twin_state;
  const profile = data.telemetry_profile;
  if (!twin || (!twin.reported && !twin.trusted)) {
    return (
      <EmptyState icon={Boxes} title="No state yet">
        {data.identity ? "This device has not sent an authentic message in the current baseline." : "This asset does not send telemetry in this model."}
      </EmptyState>
    );
  }
  const fields = profile?.fields.length
    ? profile.fields
    : Object.keys({ ...(twin.trusted ?? {}), ...(twin.reported ?? {}) }).map((name) => ({ name, label: titleCase(name), unit: null, kind: "", minimum: null, maximum: null, choices: [] }));
  const comparisons = new Map<string, MetricComparison>((twin.discrepancy?.comparisons ?? []).map((c) => [c.metric, c]));
  const predicted = twin.predicted ?? null;
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-ink-muted">
        Three separate states. <b className="text-ink">Reported</b> is the latest authentic claim; <b className="text-ink">Trusted</b> is the latest
        claim that passed every check; <b className="text-ink">Predicted</b> comes from the deterministic model using trusted inputs only.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px]">
          <caption className="sr-only">Reported, trusted and predicted values</caption>
          <thead className="text-left text-[11px] tracking-wide text-ink-muted uppercase">
            <tr>
              <th scope="col" className="py-1 pr-2 font-medium">Metric</th>
              <th scope="col" className="py-1 pr-2 font-medium">Reported</th>
              <th scope="col" className="py-1 pr-2 font-medium">Trusted</th>
              <th scope="col" className="py-1 font-medium">Predicted</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => {
              const reported = fieldValue(twin.reported, f.name);
              const trusted = fieldValue(twin.trusted, f.name);
              const cmp = comparisons.get(f.name);
              const differs = JSON.stringify(reported) !== JSON.stringify(trusted);
              return (
                <tr key={f.name} className="border-t border-line align-top">
                  <th scope="row" className="py-1.5 pr-2 text-left font-normal text-ink-muted">
                    {f.label}
                    {f.minimum !== null || f.maximum !== null ? (
                      <span className="block text-[10.5px] text-ink-faint">
                        limits {f.minimum ?? "–"}…{f.maximum ?? "–"} {f.unit ?? ""}
                      </span>
                    ) : null}
                  </th>
                  <td className={`py-1.5 pr-2 tabular ${differs ? "font-semibold text-warn" : ""}`}>{formatValue(reported, f.unit)}</td>
                  <td className="py-1.5 pr-2 tabular">{formatValue(trusted, f.unit)}</td>
                  <td className="py-1.5 tabular">
                    {predicted && f.name in predicted ? formatValue(predicted[f.name], f.unit) : <span className="text-ink-faint">not modeled</span>}
                    {cmp ? (
                      <span className={`block text-[10.5px] ${cmp.within_tolerance ? "text-ink-faint" : "text-warn"}`}>
                        Δ {cmp.delta !== null ? (cmp.delta > 0 ? "+" : "") + cmp.delta : "–"} (±{cmp.tolerance})
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <dl>
        <KeyValue label="Reported at">
          {dateTime(twin.reported_at)}{" "}
          {twin.reported_decision ? <StatusBadge status={DECISION[twin.reported_decision]} size="xs" className="ml-1" /> : null}
        </KeyValue>
        <KeyValue label="Trusted at">{dateTime(twin.trusted_at)}</KeyValue>
        {twin.trusted_event_id ? <KeyValue label="Trusted from event" mono>#{twin.trusted_event_id}</KeyValue> : null}
      </dl>
      {twin.discrepancy ? (
        <div className={`rounded-md border p-2.5 text-[12.5px] ${twin.discrepancy.within_tolerance ? "border-line bg-surface-2" : "border-warn/40 bg-warn/10"}`}>
          <p className="font-medium">{twin.discrepancy.within_tolerance ? "Consistent with the model" : "Discrepancy with the model (suspected, not proven)"}</p>
          <p className="mt-0.5 text-ink-muted">{twin.discrepancy.note}</p>
          {!twin.discrepancy.within_tolerance ? (
            <p className="mt-1 text-ink-muted">
              A faulty sensor, delayed HVAC state or model error could also explain this. The reading is held, never silently trusted.
            </p>
          ) : null}
        </div>
      ) : null}
      {predicted && "_inputs" in predicted ? (
        <details className="rounded-md border border-line p-2 text-[12px]">
          <summary className="cursor-pointer text-ink-muted">Model inputs</summary>
          <pre className="mt-1 overflow-x-auto font-mono text-[11px] text-ink-muted">{JSON.stringify(predicted._inputs, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}

function SecurityView({ data }: { data: AssetDetail }) {
  const { data: me } = useMe();
  const action = useDeviceAction();
  const [pending, setPending] = useState<null | { kind: "revoke" | "rotate-key" | "clear-suspicion"; title: string }>(null);
  const canManage = me?.permissions.includes("manage_identities") ?? false;
  const identity = data.identity;
  return (
    <div className="space-y-3">
      {identity ? (
        <>
          <dl>
            <KeyValue label="Registration">{titleCase(identity.registration_status)}</KeyValue>
            <KeyValue label="Trust state">
              <StatusBadge status={trustStyle(identity.trust_state)} size="xs" />
            </KeyValue>
            <KeyValue label="Message types">{identity.allowed_message_types.length ? identity.allowed_message_types.join(", ") : "none"}</KeyValue>
            <KeyValue label="Last authenticated">{ago(identity.last_authenticated_at)}</KeyValue>
          </dl>
          <SectionTitle>Credentials (metadata only; keys are never stored or shown)</SectionTitle>
          {identity.credentials.length ? (
            <ul className="space-y-1">
              {identity.credentials.map((c) => (
                <li key={c.key_version} className="flex items-center justify-between rounded border border-line px-2 py-1.5 text-[12px]">
                  <span>
                    <KeyRound aria-hidden className="mr-1 inline size-3.5 text-ink-muted" />v{c.key_version} · {c.algorithm} · <Mono>{c.fingerprint}</Mono>
                  </span>
                  <span className={c.status === "ACTIVE" ? "text-ok" : "text-ink-muted"}>{titleCase(c.status)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-ink-muted">No credential: this identity can never authenticate.</p>
          )}
          {canManage && identity.registration_status === "REGISTERED" ? (
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button size="sm" icon={RefreshCw} onClick={() => setPending({ kind: "rotate-key", title: "Rotate device key" })}>
                Rotate key
              </Button>
              {identity.trust_state === "SUSPICIOUS" ? (
                <Button size="sm" icon={ShieldCheck} onClick={() => setPending({ kind: "clear-suspicion", title: "Clear suspicion" })}>
                  Clear suspicion
                </Button>
              ) : null}
              {identity.trust_state !== "REVOKED" ? (
                <Button size="sm" variant="danger" icon={ShieldOff} onClick={() => setPending({ kind: "revoke", title: "Revoke device credential" })}>
                  Revoke
                </Button>
              ) : null}
            </div>
          ) : null}
        </>
      ) : (
        <p className="text-[13px] text-ink-muted">This asset has no device identity in the model; it never signs messages.</p>
      )}
      <SectionTitle>Outbound permissions</SectionTitle>
      <PolicyList items={data.permissions.outbound} empty="No outbound policy names this asset or its zone." />
      <SectionTitle>Inbound permissions</SectionTitle>
      <PolicyList items={data.permissions.inbound} empty="No inbound policy names this asset or its zone." />
      {data.permissions.accepted_commands.length ? (
        <>
          <SectionTitle>Commands this device accepts</SectionTitle>
          <ul className="space-y-1 text-[12.5px]">
            {data.permissions.accepted_commands.map((c) => (
              <li key={c.action} className="rounded border border-line px-2 py-1.5">
                <span className="font-mono text-[11.5px]">{c.action}</span> from{" "}
                {c.permitted_sources.length ? c.permitted_sources.join(", ") : <span className="text-ink-muted">nobody</span>}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="text-[11.5px] text-ink-faint">Everything not explicitly allowed is denied by default.</p>
      <ConfirmDialog
        open={pending !== null}
        title={pending?.title ?? ""}
        confirmLabel="Confirm"
        danger={pending?.kind === "revoke"}
        loading={action.isPending}
        onClose={() => setPending(null)}
        onConfirm={(reason) =>
          pending &&
          action.mutate(
            { assetId: data.asset.id, action: pending.kind, reason },
            {
              onSuccess: () => {
                toast.success(`${pending.title}: done for ${data.asset.id}`);
                setPending(null);
              },
              onError: (e) => toast.error(errorMessage(e)),
            },
          )
        }
      >
        <p>
          This changes the simulated identity of <span className="font-mono text-ink">{data.asset.id}</span> and is recorded in the audit trail.
        </p>
      </ConfirmDialog>
    </div>
  );
}

function PolicyList({ items, empty }: { items: AssetDetail["permissions"]["outbound"]; empty: string }) {
  if (!items.length) return <p className="text-[12.5px] text-ink-muted">{empty}</p>;
  return (
    <ul className="space-y-1">
      {items.map((p) => (
        <li key={p.id} className="rounded border border-line px-2 py-1.5 text-[12px]">
          <div className="flex items-center justify-between gap-2">
            <span className={p.effect === "ALLOW" ? "font-semibold text-ok" : "font-semibold text-crit"}>{p.effect}</span>
            <span className="font-mono text-[10.5px] text-ink-faint">P{p.priority} · {titleCase(p.origin)}</span>
          </div>
          <div className="wrap-anywhere">
            {p.source} → {p.destination} <span className="text-ink-muted">({p.service_or_action})</span>
          </div>
          <div className="font-mono text-[10.5px] text-ink-faint">{p.id}</div>
        </li>
      ))}
    </ul>
  );
}

function RelationshipRow({ rel, assetId }: { rel: Relationship; assetId: string }) {
  const outgoing = rel.source_asset_id === assetId;
  const peer = outgoing ? rel.destination_asset_id : rel.source_asset_id;
  const select = useTwinStore((s) => s.select);
  return (
    <li className="rounded border border-line px-2 py-1.5 text-[12px]">
      <div className="flex items-center justify-between gap-2">
        <button type="button" onClick={() => select(peer)} className="cursor-pointer truncate font-mono text-[11.5px] text-accent-strong hover:underline">
          {outgoing ? "→" : "←"} {peer}
        </button>
        <StatusBadge status={OUTCOME[rel.policy_status]} size="xs" />
      </div>
      <div className="text-ink-muted">
        {rel.protocol_label}
        {rel.origin === "OBSERVED" ? <span className="ml-1 text-warn">· observed, not in baseline</span> : null}
      </div>
      <div className="text-[11px] text-ink-faint">{rel.policy_reason}</div>
    </li>
  );
}

function NetworkView({ data }: { data: AssetDetail }) {
  const flows = data.network_relationships.filter((r) => r.relationship_type !== "L2_UPLINK");
  const links = data.network_relationships.filter((r) => r.relationship_type === "L2_UPLINK");
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-ink-muted">
        Status is evaluated against current policy each time; a drawn connection never implies permission.
      </p>
      <SectionTitle>Communication paths ({flows.length})</SectionTitle>
      {flows.length ? (
        <ul className="space-y-1">{flows.map((r) => <RelationshipRow key={r.id} rel={r} assetId={data.asset.id} />)}</ul>
      ) : (
        <p className="text-[12.5px] text-ink-muted">No modeled communication paths.</p>
      )}
      <SectionTitle>Layer-2 attachment ({links.length})</SectionTitle>
      {links.length ? (
        <ul className="space-y-1">{links.map((r) => <RelationshipRow key={r.id} rel={r} assetId={data.asset.id} />)}</ul>
      ) : (
        <p className="text-[12.5px] text-ink-muted">None.</p>
      )}
    </div>
  );
}

function DependencyView({ data }: { data: AssetDetail }) {
  const select = useTwinStore((s) => s.select);
  const row = (id: string, name: string, type: string, criticality: string, description: string) => (
    <li key={`${id}-${type}`} className="rounded border border-line px-2 py-1.5 text-[12px]">
      <div className="flex items-center justify-between gap-2">
        <button type="button" onClick={() => select(id)} className="cursor-pointer truncate text-left text-accent-strong hover:underline">
          {name}
        </button>
        <span className="shrink-0 text-[11px] text-ink-muted">{titleCase(criticality)}</span>
      </div>
      <div className="text-ink-muted">{titleCase(type)}: {description}</div>
    </li>
  );
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-ink-muted">Operational dependencies describe what relies on what. They are modeled separately from network connectivity.</p>
      <SectionTitle>Relies on ({data.dependencies.relies_on.length})</SectionTitle>
      {data.dependencies.relies_on.length ? (
        <ul className="space-y-1">{data.dependencies.relies_on.map((d) => row(d.provider_asset_id, d.provider_name, d.dependency_type, d.criticality, d.description))}</ul>
      ) : (
        <p className="text-[12.5px] text-ink-muted">Nothing modeled.</p>
      )}
      <SectionTitle>Relied on by ({data.dependencies.relied_on_by.length})</SectionTitle>
      {data.dependencies.relied_on_by.length ? (
        <ul className="space-y-1">{data.dependencies.relied_on_by.map((d) => row(d.dependent_asset_id, d.dependent_name, d.dependency_type, d.criticality, d.description))}</ul>
      ) : (
        <p className="text-[12.5px] text-ink-muted">Nothing modeled.</p>
      )}
    </div>
  );
}

function HistoryView({ data }: { data: AssetDetail }) {
  return (
    <div className="space-y-3">
      <SectionTitle>Recent messages</SectionTitle>
      {data.recent_telemetry.length ? (
        <ul className="space-y-1">
          {data.recent_telemetry.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-2 rounded border border-line px-2 py-1.5 text-[12px]">
              <span className="min-w-0">
                <span className="font-mono text-[11px] text-ink-faint">#{t.id}</span> {t.message_type ?? "?"} · seq {t.sequence ?? "–"}
                <span className="block text-[11px] text-ink-muted">
                  {ago(t.received_at)} · {t.reason_code} · {t.integrity_verified ? "authentic" : "not authenticated"}
                </span>
              </span>
              <StatusBadge status={DECISION[t.decision]} size="xs" />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[12.5px] text-ink-muted">No messages recorded.</p>
      )}
      <SectionTitle>Audit trail</SectionTitle>
      {data.recent_audit.length ? (
        <ul className="space-y-1">
          {data.recent_audit.map((a) => (
            <li key={a.id} className="rounded border border-line px-2 py-1.5 text-[12px]">
              <div className="flex justify-between gap-2">
                <span className="font-medium">{a.action}</span>
                <span className="text-[11px] text-ink-muted">{a.decision}</span>
              </div>
              <div className="text-ink-muted">{a.reason}</div>
              <div className="text-[11px] text-ink-faint">
                {dateTime(a.occurred_at)} · {a.actor_id}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[12.5px] text-ink-muted">No audit events reference this asset.</p>
      )}
    </div>
  );
}
