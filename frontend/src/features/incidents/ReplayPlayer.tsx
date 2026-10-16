import { Pause, Play, SkipBack, SkipForward, View } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useReplay } from "../../api/queries";
import { Button, EmptyState, Spinner, StatusBadge } from "../../components/ui/primitives";
import { dateTime, titleCase } from "../../lib/format";
import { INCIDENT_STATUS, OUTCOME } from "../../lib/status";
import { useTwinStore } from "../../state/twin";

const KIND_LABEL = { telemetry: "Message", policy_decision: "Policy decision", alert: "Alert", audit: "Audit", incident_event: "Incident" } as const;

/** Steps through the incident as reconstructed from persisted records. */
export function ReplayPlayer({ incidentId }: { incidentId: number }) {
  const { data, isPending } = useReplay(incidentId, true);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const setHighlight = useTwinStore((s) => s.setHighlight);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  const navigate = useNavigate();
  const frames = data?.frames ?? [];

  useEffect(() => {
    if (!playing) return;
    if (index >= frames.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setIndex((i) => Math.min(i + 1, frames.length - 1)), 1100);
    return () => window.clearTimeout(timer);
  }, [playing, index, frames.length]);

  if (isPending) return <Spinner label="Reconstructing incident" />;
  if (!data || frames.length === 0) return <EmptyState icon={View} title="Nothing to replay yet" />;
  const frame = frames[Math.min(index, frames.length - 1)];

  const showOnTwin = () => {
    setHighlight({
      assets: frame.highlighted_assets,
      label: `Replay ${data.incident.reference}: step ${index + 1}/${frames.length} · ${frame.incident_status ? INCIDENT_STATUS[frame.incident_status].label : ""}`,
      edges: frame.edge ? [{ source: frame.edge.source, destination: frame.edge.destination, outcome: frame.edge.outcome }] : undefined,
    });
    requestFocus("assets", frame.highlighted_assets);
    navigate("/");
  };

  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-ink-muted">{data.note}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" icon={SkipBack} aria-label="Previous step" onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0} />
        <Button size="sm" icon={playing ? Pause : Play} onClick={() => setPlaying((p) => !p)} variant="primary">
          {playing ? "Pause" : "Play"}
        </Button>
        <Button size="sm" icon={SkipForward} aria-label="Next step" onClick={() => setIndex((i) => Math.min(frames.length - 1, i + 1))} disabled={index >= frames.length - 1} />
        <label className="flex min-w-[12rem] flex-1 items-center gap-2 text-[12px] text-ink-muted">
          <span className="sr-only">Replay position</span>
          <input type="range" min={0} max={frames.length - 1} value={index} onChange={(e) => setIndex(Number(e.target.value))} className="flex-1 accent-[#22c3d6]" />
          <span className="tabular">
            {index + 1}/{frames.length}
          </span>
        </label>
        <Button size="sm" icon={View} onClick={showOnTwin}>
          Show step on twin
        </Button>
      </div>
      <div className="rounded-lg border border-line bg-surface-2 p-3" aria-live="polite">
        <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-muted">
          <span>
            {KIND_LABEL[frame.kind]} · {dateTime(frame.t)}
          </span>
          {frame.incident_status ? <StatusBadge size="xs" status={INCIDENT_STATUS[frame.incident_status]} /> : <span>Before the incident opened</span>}
        </div>
        <p className="mt-1 text-[13px] font-medium wrap-anywhere">{frame.summary}</p>
        {frame.edge ? (
          <p className="mt-1">
            <StatusBadge size="xs" status={{ ...OUTCOME[frame.edge.outcome], label: `${frame.edge.source} → ${frame.edge.destination} (${frame.edge.service}): ${OUTCOME[frame.edge.outcome].label}` }} />
          </p>
        ) : null}
        {frame.highlighted_assets.length ? <p className="mt-1 text-[12px] text-ink-muted">Assets involved so far: {frame.highlighted_assets.join(", ")}</p> : null}
        {Object.keys(frame.trust_states).length ? (
          <p className="mt-0.5 text-[12px] text-ink-muted">
            Trust changes so far: {Object.entries(frame.trust_states).map(([a, s]) => `${a} → ${titleCase(s)}`).join(", ")}
          </p>
        ) : null}
        <details className="mt-2">
          <summary className="cursor-pointer text-[12px] text-ink-muted">Recorded detail</summary>
          <pre className="mt-1 max-h-64 overflow-auto font-mono text-[11px] text-ink-muted">{JSON.stringify(frame.detail, null, 2)}</pre>
        </details>
      </div>
      <ol className="max-h-72 space-y-0.5 overflow-y-auto text-[12px]">
        {frames.map((f, i) => (
          <li key={`${f.kind}-${f.ref_id}`}>
            <button
              type="button"
              onClick={() => setIndex(i)}
              aria-current={i === index}
              className={`flex w-full cursor-pointer gap-2 rounded px-2 py-1 text-left ${i === index ? "bg-accent-soft text-ink" : "text-ink-muted hover:bg-surface-2"}`}
            >
              <span className="w-6 shrink-0 tabular">{i + 1}</span>
              <span className="w-24 shrink-0">{KIND_LABEL[f.kind]}</span>
              <span className="min-w-0 truncate">{f.summary}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
