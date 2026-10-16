import { Link2, ScrollText, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { errorMessage } from "../api/client";
import { useAudit, useMe, useVerifyAudit } from "../api/queries";
import { Button, ErrorNote, Panel, Spinner } from "../components/ui/primitives";
import { dateTime, shortHash } from "../lib/format";

export default function AuditPage() {
  const [filters, setFilters] = useState({ action: "", target_id: "", actor_id: "" });
  const [applied, setApplied] = useState(filters);
  const { data = [], isPending, error, refetch } = useAudit(applied);
  const verify = useVerifyAudit();
  const { data: me } = useMe();
  const canVerify = me?.permissions.includes("verify_audit") ?? false;
  const input = "h-8 rounded-md border border-line-strong bg-canvas px-2 text-[12.5px] focus:border-accent focus:outline-none";
  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto max-w-[1500px] space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Audit trail</h1>
            <p className="text-[12.5px] text-ink-muted">Append-only (database trigger) and hash-chained. There are no edit or delete endpoints.</p>
          </div>
          {canVerify ? (
            <Button icon={Link2} loading={verify.isPending} onClick={() => verify.mutate()}>
              Verify hash chain
            </Button>
          ) : null}
        </div>
        {verify.data ? (
          <div
            role="status"
            className={`flex items-start gap-2 rounded-lg border p-3 text-[12.5px] ${verify.data.valid ? "border-ok/40 bg-ok/10" : "border-crit/40 bg-crit/10"}`}
          >
            {verify.data.valid ? <ShieldCheck aria-hidden className="size-4 shrink-0 text-ok" /> : <ShieldX aria-hidden className="size-4 shrink-0 text-crit" />}
            <div>
              <p className="font-medium">
                {verify.data.valid
                  ? `Chain intact: ${verify.data.checked} entries verified (head ${shortHash(verify.data.head_hash, 16)})`
                  : `Chain broken at entry #${verify.data.first_invalid_id}: ${verify.data.problem}`}
              </p>
              <p className="text-ink-muted">{verify.data.note}</p>
            </div>
          </div>
        ) : null}
        {verify.error ? <ErrorNote error={errorMessage(verify.error)} /> : null}
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(filters);
          }}
        >
          {(["action", "actor_id", "target_id"] as const).map((key) => (
            <label key={key} className="space-y-1 text-[12px]">
              <span className="block text-ink-muted">{key === "action" ? "Action" : key === "actor_id" ? "Actor" : "Target"}</span>
              <input className={input} value={filters[key]} onChange={(e) => setFilters({ ...filters, [key]: e.target.value })} placeholder={key === "action" ? "e.g. TELEMETRY_REJECTED" : ""} />
            </label>
          ))}
          <Button type="submit" size="md">
            Filter
          </Button>
        </form>
        <Panel title={`Entries (${data.length}, newest first)`} icon={ScrollText} bodyClassName="overflow-x-auto p-0">
          {isPending ? (
            <Spinner label="Loading audit events" />
          ) : error ? (
            <ErrorNote error={errorMessage(error)} onRetry={() => void refetch()} />
          ) : (
            <table className="w-full text-[12.5px]">
              <caption className="sr-only">Audit events</caption>
              <thead className="text-left text-[11px] tracking-wide text-ink-muted uppercase">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">#</th>
                  <th scope="col" className="px-3 py-2 font-medium">Time</th>
                  <th scope="col" className="px-3 py-2 font-medium">Actor</th>
                  <th scope="col" className="px-3 py-2 font-medium">Action</th>
                  <th scope="col" className="px-3 py-2 font-medium">Target</th>
                  <th scope="col" className="px-3 py-2 font-medium">Decision</th>
                  <th scope="col" className="px-3 py-2 font-medium">Reason</th>
                  <th scope="col" className="px-3 py-2 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.id} className="border-t border-line align-top">
                    <td className="px-3 py-1.5 tabular text-ink-muted">{a.id}</td>
                    <td className="px-3 py-1.5 whitespace-nowrap text-ink-muted">{dateTime(a.occurred_at)}</td>
                    <td className="px-3 py-1.5">
                      <span className="text-[11px] text-ink-faint">{a.actor_type.toLowerCase()}</span>
                      <span className="block font-mono text-[11.5px]">{a.actor_id}</span>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{a.action}</td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px] wrap-anywhere">
                      {a.target_type}:{a.target_id}
                    </td>
                    <td className={`px-3 py-1.5 font-semibold ${a.decision === "DENY" || a.decision === "FAILURE" ? "text-crit" : a.decision === "ALLOW" || a.decision === "SUCCESS" ? "text-ok" : "text-ink-muted"}`}>
                      {a.decision}
                    </td>
                    <td className="max-w-md px-3 py-1.5 text-ink-muted wrap-anywhere">
                      {a.reason}
                      <span className="block font-mono text-[10.5px] text-ink-faint">corr {a.correlation_id.slice(0, 8)}</span>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-[11px] text-ink-faint" title={`prev ${a.prev_hash}\nthis ${a.entry_hash}`}>
                      {shortHash(a.entry_hash, 10)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  );
}
