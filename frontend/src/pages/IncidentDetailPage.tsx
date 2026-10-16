import { ArrowLeft, Check, MessageSquarePlus, View, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { errorMessage } from "../api/client";
import { useAddNote, useIncident, useMe, useRecovery, useTransitionIncident } from "../api/queries";
import type { IncidentDetail, IncidentStatus } from "../api/types";
import { Button, ConfirmDialog, ErrorNote, Panel, SectionTitle, Spinner, StatusBadge, Tabs } from "../components/ui/primitives";
import { toast } from "../components/ui/toast";
import { ContainmentPlanner } from "../features/incidents/ContainmentPlanner";
import { ReplayPlayer } from "../features/incidents/ReplayPlayer";
import { cx } from "../components/ui/primitives";
import { dateTime, titleCase } from "../lib/format";
import { CLASSIFICATION, INCIDENT_FLOW, INCIDENT_STATUS, OUTCOME, SEVERITY } from "../lib/status";
import { useTwinStore } from "../state/twin";

function StatusStepper({ status }: { status: IncidentStatus }) {
  const current = INCIDENT_FLOW.indexOf(status);
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label="Incident lifecycle">
      {INCIDENT_FLOW.map((step, index) => {
        const s = INCIDENT_STATUS[step];
        const done = index < current;
        const active = index === current;
        return (
          <li key={step} className="flex items-center gap-1" aria-current={active ? "step" : undefined}>
            <span
              className={cx(
                "flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11.5px]",
                active ? "font-semibold" : done ? "text-ink-muted" : "text-ink-faint",
              )}
              style={active ? { color: s.color, borderColor: `${s.color}88`, backgroundColor: `${s.color}18` } : { borderColor: "rgb(148 163 184 / 0.14)" }}
            >
              {done ? <Check aria-hidden className="size-3" /> : <s.icon aria-hidden className="size-3" />}
              {s.label}
            </span>
            {index < INCIDENT_FLOW.length - 1 ? <span aria-hidden className="text-ink-faint">›</span> : null}
          </li>
        );
      })}
    </ol>
  );
}

const TRANSITION_LABEL: Partial<Record<IncidentStatus, string>> = {
  INVESTIGATING: "Start investigation",
  CONTAINMENT_PROPOSED: "Propose containment",
  RECOVERY: "Begin recovery",
  RESOLVED: "Resolve",
  CONTAINED: "Mark contained",
};

function TransitionControls({ incident }: { incident: IncidentDetail }) {
  const transition = useTransitionIncident(incident.id);
  const [target, setTarget] = useState<IncidentStatus | null>(null);
  const [resolution, setResolution] = useState("FALSE_POSITIVE");
  const [error, setError] = useState<string | null>(null);
  const options = incident.allowed_transitions.filter((s) => s !== "CONTAINED");
  const early = target === "RESOLVED" && incident.status === "INVESTIGATING";
  if (incident.read_only || options.length === 0) return null;
  return (
    <>
      <div className="flex flex-wrap gap-1.5">
        {options.map((s) => (
          <Button key={s} size="sm" variant={s === "RESOLVED" ? "secondary" : "primary"} onClick={() => { setError(null); setTarget(s); }}>
            {TRANSITION_LABEL[s] ?? titleCase(s)}
          </Button>
        ))}
      </div>
      <ConfirmDialog
        open={target !== null}
        title={target ? `${TRANSITION_LABEL[target] ?? titleCase(target)}: ${incident.reference}` : ""}
        confirmLabel="Confirm"
        loading={transition.isPending}
        error={error}
        onClose={() => setTarget(null)}
        onConfirm={(note) =>
          target &&
          transition.mutate(
            { target_status: target, note, resolution: early ? resolution : undefined },
            {
              onSuccess: () => {
                toast.success(`${incident.reference} → ${INCIDENT_STATUS[target].label}`);
                setTarget(null);
              },
              onError: (e) => setError(errorMessage(e)),
            },
          )
        }
      >
        <p>
          {incident.status} → {target}. The backend enforces the lifecycle; invalid moves are refused.
        </p>
        {early ? (
          <label className="block space-y-1">
            <span className="text-xs font-medium text-ink">Resolution without containment</span>
            <select
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              className="h-8 w-full rounded-md border border-line-strong bg-canvas px-2 text-[13px] text-ink"
            >
              <option value="FALSE_POSITIVE">False positive</option>
              <option value="BENIGN">Benign (explained)</option>
              <option value="NO_ACTION_REQUIRED">No action required</option>
              <option value="ACCEPTED_RISK">Accepted risk</option>
            </select>
          </label>
        ) : null}
      </ConfirmDialog>
    </>
  );
}

function RecoveryPanel({ incident }: { incident: IncidentDetail }) {
  const recovery = useRecovery(incident.id);
  const [opts, setOpts] = useState({ rotate_credentials: true, release_containment: true, restore_trusted_state: true });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const steps = incident.events.filter((e) => e.event_type === "RECOVERY_EXECUTED");
  return (
    <div className="space-y-3">
      <p className="max-w-2xl text-[12.5px] text-ink-muted">
        Recovery re-provisions affected identities with a new key version, lifts containment by <em>deactivating</em> (not deleting)
        containment policies, and re-anchors trusted state to the last accepted observation before the incident. Evidence is never erased.
      </p>
      {incident.status === "RECOVERY" && !incident.read_only ? (
        <fieldset className="space-y-1.5 rounded-lg border border-line p-3">
          <legend className="px-1 text-[12px] font-medium">Recovery actions</legend>
          {(
            [
              ["rotate_credentials", "Rotate device credentials (new key version; device must re-authenticate)"],
              ["release_containment", "Release containment policies (kept for evidence)"],
              ["restore_trusted_state", "Restore trusted state to last known-good observation"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex cursor-pointer items-center gap-2 text-[12.5px]">
              <input type="checkbox" checked={opts[key]} onChange={(e) => setOpts({ ...opts, [key]: e.target.checked })} className="accent-[#22c3d6]" />
              {label}
            </label>
          ))}
          <Button size="sm" variant="primary" icon={Wrench} className="mt-1" onClick={() => { setError(null); setOpen(true); }}>
            Execute recovery
          </Button>
        </fieldset>
      ) : (
        <p className="rounded-md border border-line bg-surface-2 p-2.5 text-[12.5px] text-ink-muted">
          {incident.status === "CONTAINED" ? "Begin recovery from the actions above to enable these steps." : `Recovery runs while the incident is in Recovery (currently ${INCIDENT_STATUS[incident.status].label}).`}
        </p>
      )}
      {steps.map((event) => (
        <div key={event.id} className="rounded-lg border border-line bg-surface-2 p-3 text-[12.5px]">
          <p className="font-medium">
            {event.summary} · {dateTime(event.occurred_at)} by {event.actor_id}
          </p>
          <ul className="mt-1 space-y-0.5 text-ink-muted">
            {((event.details.steps as Record<string, unknown>[] | undefined) ?? []).map((s, i) => (
              <li key={i}>
                {titleCase(String(s.action))}
                {s.asset_id ? ` · ${String(s.asset_id)}` : ""}
                {s.new_key_version ? ` · key v${String(s.new_key_version)}` : ""}
                {s.note ? ` · ${String(s.note)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <ConfirmDialog
        open={open}
        title={`Execute recovery for ${incident.reference}`}
        confirmLabel="Execute recovery"
        loading={recovery.isPending}
        error={error}
        onClose={() => setOpen(false)}
        onConfirm={(note) =>
          recovery.mutate(
            { ...opts, note },
            {
              onSuccess: () => {
                toast.success("Recovery executed; resolve the incident when verified.");
                setOpen(false);
              },
              onError: (e) => setError(errorMessage(e)),
            },
          )
        }
      >
        <p>Selected recovery actions run in one audited transaction.</p>
      </ConfirmDialog>
    </div>
  );
}

function NoteBox({ incident }: { incident: IncidentDetail }) {
  const add = useAddNote(incident.id);
  const [text, setText] = useState("");
  if (incident.read_only) return null;
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim().length < 3) return;
        add.mutate(text.trim(), { onSuccess: () => setText(""), onError: (err) => toast.error(errorMessage(err)) });
      }}
    >
      <label className="sr-only" htmlFor="incident-note">
        Add a note to the timeline
      </label>
      <input
        id="incident-note"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Add an analyst note to the timeline"
        className="h-8 min-w-0 flex-1 rounded-md border border-line-strong bg-canvas px-2.5 text-[13px] focus:border-accent focus:outline-none"
      />
      <Button size="sm" type="submit" icon={MessageSquarePlus} loading={add.isPending} disabled={text.trim().length < 3}>
        Add note
      </Button>
    </form>
  );
}

export default function IncidentDetailPage() {
  const { incidentId } = useParams();
  const id = Number(incidentId);
  const { data: incident, isPending, error, refetch } = useIncident(Number.isFinite(id) ? id : null);
  const { data: me } = useMe();
  const [tab, setTab] = useState("timeline");
  const navigate = useNavigate();
  const setHighlight = useTwinStore((s) => s.setHighlight);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  if (isPending) return <Spinner label="Loading incident" />;
  if (error || !incident) return <ErrorNote error={errorMessage(error)} onRetry={() => void refetch()} />;
  const canManage = me?.permissions.includes("manage_incidents") ?? false;
  const assetIds = incident.assets.map((a) => a.asset_id);

  const tabs = [
    { id: "timeline", label: "Timeline", count: incident.events.length },
    { id: "evidence", label: "Evidence", count: incident.alerts.length },
    { id: "assets", label: "Assets", count: incident.assets.length },
    { id: "decisions", label: "Policy decisions", count: incident.policy_decisions.length },
    { id: "containment", label: "Containment", count: incident.containment_plans.length },
    { id: "recovery", label: "Recovery" },
    { id: "replay", label: "Replay" },
  ];

  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto max-w-[1400px] space-y-3">
        <Link to="/incidents" className="inline-flex items-center gap-1 text-[12.5px] text-ink-muted hover:text-ink">
          <ArrowLeft aria-hidden className="size-3.5" /> Incidents
        </Link>
        <header className="space-y-2 rounded-lg border border-line bg-surface p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-mono text-[12px] text-accent-strong">
                {incident.reference} · {titleCase(incident.category)} · baseline #{incident.epoch}
              </p>
              <h1 className="text-lg leading-snug font-semibold">{incident.title}</h1>
              <p className="max-w-3xl text-[13px] text-ink-muted">{incident.summary}</p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusBadge status={SEVERITY[incident.severity]} />
              <Button
                size="sm"
                icon={View}
                onClick={() => {
                  setHighlight({ assets: assetIds, label: `${incident.reference}: ${assetIds.length} involved asset(s)` });
                  requestFocus("assets", assetIds);
                  navigate("/");
                }}
              >
                Show in twin
              </Button>
            </div>
          </div>
          <StatusStepper status={incident.status} />
          {incident.read_only ? (
            <p className="rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-[12.5px] text-ink-muted">
              This incident belongs to a previous simulation baseline and is read-only. Its evidence is preserved.
            </p>
          ) : null}
          {canManage ? <TransitionControls incident={incident} /> : null}
          {incident.resolution ? (
            <p className="text-[12.5px] text-ink-muted">
              Resolved as {titleCase(incident.resolution)}: {incident.resolution_note}
            </p>
          ) : null}
        </header>
        <Panel bodyClassName="p-0">
          <Tabs items={tabs} value={tab} onChange={setTab} label="Incident sections" />
          <div className="p-3" role="tabpanel">
            {tab === "timeline" ? (
              <div className="space-y-3">
                {canManage ? <NoteBox incident={incident} /> : null}
                <ol className="relative space-y-2 border-l border-line pl-4">
                  {incident.events.map((event) => (
                    <li key={event.id} className="relative">
                      <span aria-hidden className="absolute top-1.5 -left-[1.3rem] size-2 rounded-full bg-accent" />
                      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[12px] text-ink-muted">
                        <span className="font-semibold text-ink">{titleCase(event.event_type)}</span>
                        <span>
                          {dateTime(event.occurred_at)} · {event.actor_type.toLowerCase()} {event.actor_id}
                        </span>
                      </div>
                      <p className="text-[13px] wrap-anywhere">{event.summary}</p>
                      {Object.keys(event.details).length ? (
                        <details>
                          <summary className="cursor-pointer text-[11.5px] text-ink-muted">Details</summary>
                          <pre className="mt-1 max-h-60 overflow-auto rounded bg-canvas p-2 font-mono text-[11px] text-ink-muted">{JSON.stringify(event.details, null, 2)}</pre>
                        </details>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}
            {tab === "evidence" ? (
              <ul className="space-y-2">
                {incident.alerts.map((alert) => (
                  <li key={alert.id} className="rounded-lg border border-line bg-surface-2 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-[13px] font-semibold">
                        <span className="font-mono text-[12px] text-ink-muted">{alert.rule_id}</span> {alert.title}
                      </p>
                      <div className="flex gap-1">
                        <StatusBadge size="xs" status={CLASSIFICATION[alert.classification]} />
                        <StatusBadge size="xs" status={SEVERITY[alert.severity]} />
                      </div>
                    </div>
                    <p className="text-[12px] text-ink-muted">
                      {dateTime(alert.created_at)} · subject <span className="font-mono">{alert.subject_ref}</span>
                    </p>
                    <p className="mt-1.5 rounded border border-line bg-canvas p-2 text-[12px] text-ink-muted">
                      <span className="font-medium text-ink">Confidence: </span>
                      {alert.confidence_note}
                    </p>
                    <details className="mt-1.5">
                      <summary className="cursor-pointer text-[12px] text-ink-muted">Evidence</summary>
                      <pre className="mt-1 max-h-72 overflow-auto rounded bg-canvas p-2 font-mono text-[11px] text-ink-muted">{JSON.stringify(alert.evidence, null, 2)}</pre>
                    </details>
                  </li>
                ))}
              </ul>
            ) : null}
            {tab === "assets" ? (
              <ul className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                {incident.assets.map((a) => (
                  <li key={a.asset_id} className="flex items-center justify-between rounded-md border border-line bg-surface-2 px-2.5 py-2 text-[12.5px]">
                    <button
                      type="button"
                      className="cursor-pointer font-mono text-[12px] text-accent-strong hover:underline"
                      onClick={() => {
                        useTwinStore.getState().select(a.asset_id);
                        requestFocus("asset", [a.asset_id]);
                        navigate("/");
                      }}
                    >
                      {a.asset_id}
                    </button>
                    <span className="text-ink-muted">{titleCase(a.role)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {tab === "decisions" ? (
              incident.policy_decisions.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-[12.5px]">
                    <caption className="sr-only">Related policy decisions</caption>
                    <thead className="text-left text-[11px] tracking-wide text-ink-muted uppercase">
                      <tr>
                        <th scope="col" className="py-1.5 pr-3 font-medium">Time</th>
                        <th scope="col" className="py-1.5 pr-3 font-medium">Request</th>
                        <th scope="col" className="py-1.5 pr-3 font-medium">Outcome</th>
                        <th scope="col" className="py-1.5 font-medium">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {incident.policy_decisions.map((d) => (
                        <tr key={d.id} className="border-t border-line align-top">
                          <td className="py-1.5 pr-3 whitespace-nowrap text-ink-muted">{dateTime(d.evaluated_at)}</td>
                          <td className="py-1.5 pr-3 font-mono text-[11.5px]">
                            {d.source_ref} → {d.destination_ref} ({d.service_or_action})
                          </td>
                          <td className="py-1.5 pr-3">
                            <StatusBadge size="xs" status={OUTCOME[d.outcome]} />
                          </td>
                          <td className="py-1.5 text-ink-muted">{d.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-[12.5px] text-ink-muted">No policy decisions are linked to this incident.</p>
              )
            ) : null}
            {tab === "containment" ? <ContainmentPlanner incident={incident} /> : null}
            {tab === "recovery" ? <RecoveryPanel incident={incident} /> : null}
            {tab === "replay" ? <ReplayPlayer incidentId={incident.id} /> : null}
          </div>
        </Panel>
        <SectionTitle>Lifecycle rules</SectionTitle>
        <p className="text-[12px] text-ink-muted">
          Detected → Investigating → Containment proposed → Contained → Recovery → Resolved. Containment happens only by applying a plan; resolving
          from Investigating requires a disposition; resolving after containment requires executed recovery.
        </p>
      </div>
    </div>
  );
}
