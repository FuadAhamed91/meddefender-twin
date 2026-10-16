import { CircleCheck, CircleX, FlaskConical, Play, RotateCcw, View } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { errorMessage } from "../api/client";
import { useMe, useResetSimulation, useRunScenario, useRuns, useScenarios } from "../api/queries";
import type { Scenario, SimulationRun } from "../api/types";
import { Button, ConfirmDialog, ErrorNote, Panel, Spinner, StatusBadge } from "../components/ui/primitives";
import { toast } from "../components/ui/toast";
import { dateTime } from "../lib/format";
import { CHECK_STATUS, DECISION } from "../lib/status";
import { useTwinStore } from "../state/twin";

function RunResult({ run }: { run: SimulationRun }) {
  const navigate = useNavigate();
  const setHighlight = useTwinStore((s) => s.setHighlight);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  const result = run.result;
  if (!result) return null;
  const focus = result.artifacts.focus_assets ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px]">
          Run #{run.id} · {dateTime(run.started_at)} ·{" "}
          <span className={result.all_met ? "font-semibold text-ok" : "font-semibold text-crit"}>
            {result.expectations_met}/{result.expectations_total} expectations met
          </span>
        </p>
        <div className="flex gap-1.5">
          {focus.length ? (
            <Button
              size="sm"
              icon={View}
              onClick={() => {
                setHighlight({ assets: focus, label: `Scenario ${run.scenario_id} run #${run.id}` });
                requestFocus("assets", focus);
                navigate("/");
              }}
            >
              View in twin
            </Button>
          ) : null}
          {result.incidents.map((ref) => (
            <Link key={ref} to="/incidents" className="self-center text-[12.5px] text-accent-strong hover:underline">
              {ref}
            </Link>
          ))}
        </div>
      </div>
      {result.error ? <ErrorNote error={`${result.error.code}: ${result.error.message}`} /> : null}
      <section aria-labelledby={`exp-${run.id}`}>
        <h3 id={`exp-${run.id}`} className="mb-1 text-[11px] font-semibold tracking-wider text-ink-muted uppercase">
          Expectations, evaluated against persisted state
        </h3>
        <ul className="space-y-1">
          {result.expectations.map((e) => (
            <li key={e.label} className="flex items-start gap-2 text-[12.5px]">
              {e.met ? <CircleCheck aria-label="Met" className="mt-0.5 size-4 shrink-0 text-ok" /> : <CircleX aria-label="Not met" className="mt-0.5 size-4 shrink-0 text-crit" />}
              <span>
                {e.label}
                {e.detail ? <span className="block text-[11.5px] text-ink-muted wrap-anywhere">{e.detail}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      </section>
      {result.notes.length ? (
        <ul className="space-y-1 text-[12px] text-warn">
          {result.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      <section aria-labelledby={`steps-${run.id}`}>
        <h3 id={`steps-${run.id}`} className="mb-1 text-[11px] font-semibold tracking-wider text-ink-muted uppercase">
          Steps (real pipeline results)
        </h3>
        <ol className="space-y-1.5">
          {result.steps.map((step) => (
            <li key={step.index} className="rounded-md border border-line bg-surface-2 p-2.5 text-[12.5px]">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0">
                  <span className="mr-1 text-ink-muted tabular">{step.index}.</span>
                  {step.label}
                  <span className="block text-[11.5px] text-ink-muted">
                    actor: {step.actor}
                    {step.transport_source ? ` · from ${step.transport_source}` : ""}
                    {step.reason_code ? ` · ${step.reason_code}` : ""}
                  </span>
                </p>
                {step.decision in DECISION ? <StatusBadge size="xs" status={DECISION[step.decision as keyof typeof DECISION]} /> : <span className="text-[11.5px] text-ink-muted">{step.decision}</span>}
              </div>
              {step.checks?.length ? (
                <ul className="mt-1.5 flex flex-wrap gap-1" aria-label="Pipeline checks">
                  {step.checks
                    .filter((c) => c.check !== "transport")
                    .map((c) => (
                      <li key={c.check}>
                        <StatusBadge size="xs" status={{ ...(CHECK_STATUS[c.status] ?? CHECK_STATUS.INFO), label: `${c.check}` }} title={`${c.status}: ${c.detail}`} />
                      </li>
                    ))}
                </ul>
              ) : null}
              {step.reason && step.decision !== "ACCEPTED" ? <p className="mt-1 text-[11.5px] text-ink-muted wrap-anywhere">{step.reason}</p> : null}
              {step.trust_changes?.length ? (
                <p className="mt-1 text-[11.5px] text-warn">
                  Trust: {step.trust_changes.map((t) => `${t.asset_id} ${t.from} → ${t.to}`).join("; ")}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function ScenarioCard({ scenario, onRun, running, canRun }: { scenario: Scenario; onRun: () => void; running: boolean; canRun: boolean }) {
  const ready = scenario.precondition_checks.every((c) => c.met);
  return (
    <article className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-[11.5px] text-accent-strong">Scenario {scenario.id}</p>
          <h2 className="text-[14px] font-semibold">{scenario.title}</h2>
        </div>
        <Button size="sm" variant="primary" icon={Play} loading={running} disabled={!canRun} onClick={onRun} title={canRun ? undefined : "Operator role required"}>
          Run
        </Button>
      </header>
      <p className="text-[12.5px] text-ink-muted">{scenario.narrative}</p>
      <div className="grid gap-2 text-[12px] sm:grid-cols-2">
        <div>
          <p className="mb-0.5 font-semibold text-ink">Expected</p>
          <ul className="list-disc space-y-0.5 pl-4 text-ink-muted">
            {scenario.expected.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className="mb-0.5 font-semibold text-ink">Controls exercised</p>
          <ul className="list-disc space-y-0.5 pl-4 text-ink-muted">
            {scenario.controls.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      </div>
      <ul className="mt-auto space-y-0.5 border-t border-line pt-2 text-[12px]" aria-label="Preconditions">
        {scenario.precondition_checks.map((c) => (
          <li key={c.label} className="flex items-start gap-1.5">
            {c.met ? <CircleCheck aria-label="Met" className="mt-0.5 size-3.5 shrink-0 text-ok" /> : <CircleX aria-label="Not met" className="mt-0.5 size-3.5 shrink-0 text-warn" />}
            <span className={c.met ? "text-ink-muted" : "text-warn"}>
              {c.label} <span className="text-ink-faint">({c.detail})</span>
            </span>
          </li>
        ))}
      </ul>
      {!ready ? <p className="text-[11.5px] text-ink-faint">Unmet preconditions are reported in the run result rather than faked.</p> : null}
    </article>
  );
}

export default function ScenariosPage() {
  const { data: scenarios = [], isPending, error, refetch } = useScenarios();
  const { data: runs = [] } = useRuns();
  const { data: me } = useMe();
  const run = useRunScenario();
  const reset = useResetSimulation();
  const [latest, setLatest] = useState<SimulationRun | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const canRun = me?.permissions.includes("run_scenarios") ?? false;
  const canReset = me?.permissions.includes("reset_simulation") ?? false;
  const shown = latest ?? runs[0] ?? null;

  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto max-w-[1500px] space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Scenario console</h1>
            <p className="text-[12.5px] text-ink-muted">Synthetic attacks executed through the same enforcement pipeline as live device traffic.</p>
          </div>
          {canReset ? (
            <Button icon={RotateCcw} onClick={() => setResetOpen(true)}>
              Reset baseline
            </Button>
          ) : null}
        </div>
        {isPending ? (
          <Spinner label="Loading scenarios" />
        ) : error ? (
          <ErrorNote error={errorMessage(error)} onRetry={() => void refetch()} />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {scenarios.map((scenario) => (
              <ScenarioCard
                key={scenario.id}
                scenario={scenario}
                canRun={canRun}
                running={runningId === scenario.id}
                onRun={() => {
                  setRunningId(scenario.id);
                  run.mutate(scenario.id, {
                    onSuccess: (data) => {
                      setLatest(data);
                      const r = data.result;
                      if (r?.error) toast.error(`Scenario ${scenario.id}: ${r.error.message}`);
                      else toast.success(`Scenario ${scenario.id}: ${r?.expectations_met}/${r?.expectations_total} expectations met`);
                    },
                    onError: (e) => toast.error(errorMessage(e)),
                    onSettled: () => setRunningId(null),
                  });
                }}
              />
            ))}
          </div>
        )}
        <Panel title={shown ? `Result: Scenario ${shown.scenario_id}` : "Results"} icon={FlaskConical}>
          {shown ? <RunResult run={shown} /> : <p className="text-[13px] text-ink-muted">Run a scenario to see each step, the checks it hit, and which expectations held.</p>}
        </Panel>
        {runs.length > 1 ? (
          <Panel title="Recent runs" bodyClassName="overflow-x-auto p-0">
            <table className="w-full text-[12.5px]">
              <caption className="sr-only">Recent scenario runs</caption>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="border-t border-line first:border-t-0">
                    <td className="px-3 py-1.5 tabular text-ink-muted">#{r.id}</td>
                    <td className="px-3 py-1.5">Scenario {r.scenario_id}</td>
                    <td className="px-3 py-1.5 text-ink-muted">{dateTime(r.started_at)}</td>
                    <td className="px-3 py-1.5">
                      {r.result ? `${r.result.expectations_met}/${r.result.expectations_total}` : r.status}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <Button size="sm" variant="ghost" onClick={() => setLatest(r)}>
                        Show
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        ) : null}
      </div>
      <ConfirmDialog
        open={resetOpen}
        title="Reset to the known baseline"
        confirmLabel="Reset baseline"
        danger
        loading={reset.isPending}
        onClose={() => setResetOpen(false)}
        onConfirm={(reason) =>
          reset.mutate(reason, {
            onSuccess: (data) => {
              toast.success(`Baseline restored (epoch ${data.epoch}). Audit history kept.`);
              setResetOpen(false);
              setLatest(null);
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      >
        <p>
          Starts a new baseline epoch: identities return to Registered, containment policies are deactivated and simulated devices restart from their
          initial physical state.
        </p>
        <p>Audit events, incidents, alerts and evidence are preserved (previous incidents become read-only). Replay protection is not reset.</p>
      </ConfirmDialog>
    </div>
  );
}
