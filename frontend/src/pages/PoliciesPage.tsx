import { Scale, Waypoints } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { errorMessage } from "../api/client";
import { useEvaluatePolicy, usePolicies } from "../api/queries";
import type { Policy, PolicyEvaluation } from "../api/types";
import { Button, ErrorNote, Panel, Spinner, StatusBadge } from "../components/ui/primitives";
import { titleCase } from "../lib/format";
import { OUTCOME } from "../lib/status";
import { useTwinStore } from "../state/twin";

function selector(asset: string | null, zone: string | null) {
  return asset ?? (zone ? `zone ${zone}` : "any");
}

function Evaluator() {
  const assets = useTwinStore((s) => s.assets);
  const ids = useMemo(() => Object.values(assets).filter((a) => !a.is_logical).map((a) => a.id).sort(), [assets]);
  const evaluate = useEvaluatePolicy();
  const [form, setForm] = useState({ policy_type: "NETWORK_FLOW" as "NETWORK_FLOW" | "DEVICE_COMMAND", source_asset_id: "ICU-GATEWAY-01", destination_asset_id: "IMG-SERVER-01", service_or_action: "dicom" });
  const [result, setResult] = useState<PolicyEvaluation | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    evaluate.mutate(form, { onSuccess: setResult, onError: () => setResult(null) });
  };
  const field = "h-8 w-full rounded-md border border-line-strong bg-canvas px-2 text-[13px] focus:border-accent focus:outline-none";
  return (
    <form onSubmit={submit} className="space-y-2">
      <p className="text-[12.5px] text-ink-muted">Dry-run evaluation against live policy. Nothing is recorded or enforced.</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="space-y-1 text-[12px]">
          <span className="text-ink-muted">Type</span>
          <select className={field} value={form.policy_type} onChange={(e) => setForm({ ...form, policy_type: e.target.value as typeof form.policy_type })}>
            <option value="NETWORK_FLOW">Network flow</option>
            <option value="DEVICE_COMMAND">Device command</option>
          </select>
        </label>
        <label className="space-y-1 text-[12px]">
          <span className="text-ink-muted">{form.policy_type === "NETWORK_FLOW" ? "Service" : "Action"}</span>
          <input className={field} value={form.service_or_action} onChange={(e) => setForm({ ...form, service_or_action: e.target.value })} required pattern="^(\*|[a-z0-9_\-]{1,48})$" />
        </label>
        <label className="space-y-1 text-[12px]">
          <span className="text-ink-muted">Source</span>
          <select className={field} value={form.source_asset_id} onChange={(e) => setForm({ ...form, source_asset_id: e.target.value })}>
            {ids.map((id) => (
              <option key={id}>{id}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-[12px]">
          <span className="text-ink-muted">Destination</span>
          <select className={field} value={form.destination_asset_id} onChange={(e) => setForm({ ...form, destination_asset_id: e.target.value })}>
            {ids.map((id) => (
              <option key={id}>{id}</option>
            ))}
          </select>
        </label>
      </div>
      <Button type="submit" variant="primary" icon={Scale} loading={evaluate.isPending}>
        Evaluate
      </Button>
      {evaluate.error ? <ErrorNote error={errorMessage(evaluate.error)} /> : null}
      {result ? (
        <div className="space-y-2 rounded-lg border border-line bg-surface-2 p-3 text-[12.5px]" aria-live="polite">
          <StatusBadge status={OUTCOME[result.outcome]} />
          <p>{result.reason}</p>
          <details>
            <summary className="cursor-pointer text-ink-muted">Explanation (matched and shadowed rules)</summary>
            <pre className="mt-1 max-h-72 overflow-auto rounded bg-canvas p-2 font-mono text-[11px] text-ink-muted">{JSON.stringify(result.explanation, null, 2)}</pre>
          </details>
        </div>
      ) : null}
    </form>
  );
}

export default function PoliciesPage() {
  const [inactive, setInactive] = useState(false);
  const [type, setType] = useState<"ALL" | Policy["policy_type"]>("ALL");
  const { data = [], isPending, error, refetch } = usePolicies(inactive);
  const rows = data.filter((p) => type === "ALL" || p.policy_type === type);
  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto grid max-w-[1500px] gap-3 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <Panel
          title={`Policies (${rows.length})`}
          icon={Waypoints}
          bodyClassName="overflow-x-auto p-0"
          actions={
            <div className="flex items-center gap-3 text-[12px]">
              <label className="flex items-center gap-1">
                <span className="sr-only">Policy type</span>
                <select value={type} onChange={(e) => setType(e.target.value as typeof type)} className="h-7 rounded border border-line-strong bg-canvas px-1.5 text-[12px]">
                  <option value="ALL">All types</option>
                  <option value="NETWORK_FLOW">Network flows</option>
                  <option value="DEVICE_COMMAND">Device commands</option>
                </select>
              </label>
              <label className="flex cursor-pointer items-center gap-1.5">
                <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} className="accent-[#22c3d6]" />
                Include inactive
              </label>
            </div>
          }
        >
          {isPending ? (
            <Spinner label="Loading policies" />
          ) : error ? (
            <ErrorNote error={errorMessage(error)} onRetry={() => void refetch()} />
          ) : (
            <table className="w-full text-[12.5px]">
              <caption className="sr-only">Security policies in evaluation order</caption>
              <thead className="text-left text-[11px] tracking-wide text-ink-muted uppercase">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Priority</th>
                  <th scope="col" className="px-3 py-2 font-medium">Effect</th>
                  <th scope="col" className="px-3 py-2 font-medium">Source → destination</th>
                  <th scope="col" className="px-3 py-2 font-medium">Service / action</th>
                  <th scope="col" className="px-3 py-2 font-medium">Mode</th>
                  <th scope="col" className="px-3 py-2 font-medium">Origin</th>
                  <th scope="col" className="px-3 py-2 font-medium">Enforced at</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} className={`border-t border-line align-top ${p.is_active ? "" : "opacity-60"}`}>
                    <td className="px-3 py-1.5 tabular">{p.priority}</td>
                    <td className={`px-3 py-1.5 font-semibold ${p.effect === "ALLOW" ? "text-ok" : "text-crit"}`}>{p.effect}</td>
                    <td className="px-3 py-1.5">
                      <span className="font-mono text-[11.5px]">
                        {selector(p.source_asset_id, p.source_zone_id)} → {selector(p.destination_asset_id, p.destination_zone_id)}
                      </span>
                      <span className="block text-[11px] text-ink-faint">{p.id}</span>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{p.service_or_action}</td>
                    <td className="px-3 py-1.5">{titleCase(p.enforcement_mode)}</td>
                    <td className="px-3 py-1.5">
                      {titleCase(p.origin)}
                      {p.incident_id ? <span className="block text-[11px] text-ink-faint">incident {p.incident_id}</span> : null}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{p.enforcement_point_id ?? "command broker"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <div className="space-y-3">
          <Panel title="Policy dry run" icon={Scale}>
            <Evaluator />
          </Panel>
          <Panel title="How evaluation works">
            <ul className="list-disc space-y-1 pl-4 text-[12.5px] text-ink-muted">
              <li>Lower priority numbers are evaluated first; at equal priority, deny wins.</li>
              <li>The first matching rule decides. If nothing matches, the default is deny.</li>
              <li>Deny rules in monitor mode let traffic pass but are recorded and alerted.</li>
              <li>Commands pass a trust gate first: only authenticated identities may issue them.</li>
              <li>Containment plans add high-priority rules; recovery deactivates them, keeping them for evidence.</li>
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
