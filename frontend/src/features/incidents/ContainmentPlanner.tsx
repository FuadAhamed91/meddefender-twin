import { Eye, ScanLine, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, errorMessage } from "../../api/client";
import { useApplyPlan, useGeneratePlans, useMe } from "../../api/queries";
import type { AttackPathResult, ContainmentPlan, IncidentDetail } from "../../api/types";
import { Button, ConfirmDialog, EmptyState, SectionTitle, StatusBadge } from "../../components/ui/primitives";
import { toast } from "../../components/ui/toast";
import { titleCase } from "../../lib/format";
import { CONTAINMENT, OUTCOME, PATH_CLASS } from "../../lib/status";
import { useTwinStore } from "../../state/twin";

const ROLE_RANK = { VIEWER: 1, OPERATOR: 2, SECURITY_ADMIN: 3 } as const;

function Metric({ label, before, after, lowerIsBetter = true }: { label: string; before: number; after: number; lowerIsBetter?: boolean }) {
  const better = lowerIsBetter ? after < before : after > before;
  const worse = lowerIsBetter ? after > before : after < before;
  return (
    <div className="rounded border border-line px-2 py-1.5">
      <div className="text-[11px] text-ink-muted">{label}</div>
      <div className="text-[13px] tabular">
        {before} → <span className={better ? "font-semibold text-ok" : worse ? "font-semibold text-crit" : ""}>{after}</span>
      </div>
    </div>
  );
}

export function ContainmentPlanner({ incident }: { incident: IncidentDetail }) {
  const { data: me } = useMe();
  const generate = useGeneratePlans(incident.id);
  const apply = useApplyPlan(incident.id);
  const navigate = useNavigate();
  const setAttackPath = useTwinStore((s) => s.setAttackPath);
  const setPlanPreview = useTwinStore((s) => s.setPlanPreview);
  const requestFocus = useTwinStore((s) => s.requestFocus);
  const [chosen, setChosen] = useState<ContainmentPlan | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const plans = incident.containment_plans;
  const proposed = plans.filter((p) => p.status === "PROPOSED");
  const canOperate = me?.permissions.includes("propose_containment") ?? false;
  const roleRank = me ? ROLE_RANK[me.role] : 0;

  const preview = async (plan: ContainmentPlan | null) => {
    const entry = plan?.target_asset_id ?? incident.primary_asset_id;
    if (!entry) return;
    try {
      const result = await api.post<AttackPathResult>("/api/v1/graph/attack-paths", {
        entry_asset_id: entry,
        max_depth: 3,
        containment_plan_id: plan?.id ?? null,
      });
      setAttackPath(result);
      setPlanPreview(plan);
      requestFocus("assets", [entry, ...result.reachable_assets.map((r) => r.asset_id)]);
      navigate("/");
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-[12.5px] text-ink-muted">
          Plans are evaluated as hypothetical policy sets: comparing them changes nothing. Applying one writes containment policies,
          changes identity and containment state, and moves the incident to Contained.
        </p>
        <div className="flex gap-1.5">
          <Button size="sm" icon={Eye} onClick={() => void preview(null)} disabled={!incident.primary_asset_id}>
            Current attack paths
          </Button>
          {canOperate && !incident.read_only && ["INVESTIGATING", "CONTAINMENT_PROPOSED"].includes(incident.status) ? (
            <Button
              size="sm"
              variant="primary"
              icon={ScanLine}
              loading={generate.isPending}
              onClick={() =>
                generate.mutate(undefined, {
                  onSuccess: (data) => toast.success(`${data.length} containment options generated`),
                  onError: (e) => toast.error(errorMessage(e)),
                })
              }
            >
              {plans.length ? "Regenerate plans" : "Generate plans"}
            </Button>
          ) : null}
        </div>
      </div>
      {incident.status === "DETECTED" ? (
        <p className="rounded-md border border-line bg-surface-2 p-2.5 text-[12.5px] text-ink-muted">Move the incident to Investigating before generating containment options.</p>
      ) : null}
      {plans.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="No containment plans yet">
          Generate plans to compare isolation, restriction, zone blocking and credential revocation.
        </EmptyState>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <caption className="sr-only">Containment plan comparison</caption>
              <thead className="text-left text-[11px] tracking-wide text-ink-muted uppercase">
                <tr>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Plan</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Attack paths</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Reachable high-value</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Flows blocked</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Dependencies disrupted</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Services impaired</th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">Approval</th>
                  <th scope="col" className="py-1.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => {
                  const m = plan.analysis.metrics;
                  return (
                    <tr key={plan.id} className="border-t border-line align-top">
                      <th scope="row" className="py-2 pr-3 text-left font-medium">
                        {plan.name}
                        <span className="block text-[11px] font-normal text-ink-muted">{titleCase(plan.strategy)}</span>
                      </th>
                      <td className="py-2 pr-3 tabular">
                        {m.paths_before} → {m.paths_after}
                        <span className="block text-[11px] text-ink-muted">−{m.path_reduction_pct}%</span>
                      </td>
                      <td className="py-2 pr-3 tabular">
                        {m.high_value_reachable_before} → {m.high_value_reachable_after}
                      </td>
                      <td className="py-2 pr-3 tabular">{m.flows_blocked}</td>
                      <td className="py-2 pr-3 tabular">{m.dependencies_disrupted}</td>
                      <td className={`py-2 pr-3 tabular ${m.services_impaired ? "font-semibold text-crit" : ""}`}>
                        {m.services_impaired}
                        {m.services_degraded ? <span className="block text-[11px] font-normal text-warn">{m.services_degraded} degraded</span> : null}
                      </td>
                      <td className="py-2 pr-3 text-[11.5px]">{plan.required_role.replace("_", " ")}</td>
                      <td className="py-2 text-[11.5px]">{titleCase(plan.status)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 xl:grid-cols-2">
            {plans.map((plan) => {
              const m = plan.analysis.metrics;
              const allowed = roleRank >= ROLE_RANK[plan.required_role];
              return (
                <article key={plan.id} className="space-y-2 rounded-lg border border-line bg-surface-2 p-3">
                  <header className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h3 className="text-[13.5px] font-semibold">{plan.name}</h3>
                      <p className="text-[12px] text-ink-muted">{plan.description}</p>
                    </div>
                    <StatusBadge size="xs" status={CONTAINMENT[plan.analysis.containment_state]} />
                  </header>
                  <p className="text-[12.5px]">{plan.analysis.summary}</p>
                  <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                    <Metric label="Attack paths" before={m.paths_before} after={m.paths_after} />
                    <Metric label="Reachable assets" before={m.reachable_before} after={m.reachable_after} />
                    <Metric label="High-value reachable" before={m.high_value_reachable_before} after={m.high_value_reachable_after} />
                    <Metric label="Impaired services" before={0} after={m.services_impaired} />
                  </div>
                  {plan.analysis.blocked_flows.length ? (
                    <>
                      <SectionTitle>Flows this plan blocks</SectionTitle>
                      <ul className="flex flex-wrap gap-1">
                        {plan.analysis.blocked_flows.map((f) => (
                          <li key={`${f.source}-${f.destination}-${f.service}`}>
                            <StatusBadge size="xs" status={{ ...OUTCOME.BLOCKED, label: `${f.source} → ${f.destination} (${f.service})` }} />
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                  {plan.analysis.service_impact.length ? (
                    <>
                      <SectionTitle>Operational impact</SectionTitle>
                      <ul className="space-y-1 text-[12px]">
                        {plan.analysis.service_impact.map((s) => (
                          <li key={s.asset_id}>
                            <span className={s.status === "IMPAIRED" ? "font-semibold text-crit" : "font-semibold text-warn"}>{titleCase(s.status)}</span> · {s.display_name}
                            <span className="block text-ink-muted">{s.reasons[0]}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                  {plan.analysis.residual_reachable.length ? (
                    <>
                      <SectionTitle>Residual reachability</SectionTitle>
                      <ul className="flex flex-wrap gap-1">
                        {plan.analysis.residual_reachable.map((r) => (
                          <li key={r.asset_id}>
                            <StatusBadge size="xs" status={{ ...PATH_CLASS[r.classification], label: `${r.asset_id} · ${r.min_hops} hop${r.min_hops > 1 ? "s" : ""}` }} />
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <p className="text-[12px] text-ok">No residual attack paths from the target.</p>
                  )}
                  <p className="text-[11.5px] text-ink-faint">{plan.analysis.required_role_reason}</p>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    <Button size="sm" icon={Eye} onClick={() => void preview(plan)}>
                      Preview on twin
                    </Button>
                    {plan.status === "PROPOSED" && !incident.read_only && incident.status === "CONTAINMENT_PROPOSED" && canOperate ? (
                      <Button
                        size="sm"
                        variant={plan.analysis.metrics.services_impaired ? "danger" : "primary"}
                        disabled={!allowed}
                        title={allowed ? undefined : `Requires ${plan.required_role.replace("_", " ")}`}
                        onClick={() => {
                          setApplyError(null);
                          setChosen(plan);
                        }}
                      >
                        Apply plan
                      </Button>
                    ) : null}
                    {!allowed && plan.status === "PROPOSED" ? <span className="self-center text-[11.5px] text-ink-muted">Requires {plan.required_role.replace("_", " ")}</span> : null}
                  </div>
                </article>
              );
            })}
          </div>
          {proposed.length === 0 && plans.some((p) => p.status === "APPLIED") ? (
            <p className="text-[12.5px] text-ink-muted">A plan has been applied; remaining options were superseded.</p>
          ) : null}
        </>
      )}
      <ConfirmDialog
        open={chosen !== null}
        title={`Apply: ${chosen?.name ?? ""}`}
        confirmLabel="Apply containment"
        danger={Boolean(chosen?.analysis.metrics.services_impaired)}
        loading={apply.isPending}
        error={applyError}
        onClose={() => setChosen(null)}
        onConfirm={(justification) =>
          chosen &&
          apply.mutate(
            { planId: chosen.id, justification },
            {
              onSuccess: () => {
                toast.success(`Containment applied: ${chosen.name}`);
                setChosen(null);
              },
              onError: (e) => setApplyError(errorMessage(e)),
            },
          )
        }
      >
        <p>{chosen?.analysis.summary}</p>
        {chosen?.analysis.metrics.services_impaired ? (
          <p className="rounded border border-crit/40 bg-crit/10 p-2 text-ink">This plan impairs a modeled high-criticality service. Confirm the trade-off is acceptable.</p>
        ) : null}
        <p>The change is enforced on the backend, audited, and visible in the twin immediately.</p>
      </ConfirmDialog>
    </div>
  );
}
