import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  AssetDetail,
  AttackPathResult,
  AuditEvent,
  AuditVerification,
  Alert,
  ContainmentPlan,
  DependencyGraph,
  IncidentDetail,
  IncidentReplay,
  IncidentStatus,
  IncidentSummary,
  MetricsSummary,
  NetworkGraph,
  Policy,
  PolicyDecision,
  PolicyEvaluation,
  Room,
  Scenario,
  SimulationRun,
  SimulationStatus,
  TelemetryEvent,
  TimeseriesPoint,
  User,
  Zone,
} from "./types";

export const qk = {
  me: ["me"] as const,
  zones: ["zones"] as const,
  rooms: ["rooms"] as const,
  asset: (id: string) => ["asset", id] as const,
  metrics: ["metrics"] as const,
  timeseries: (minutes: number) => ["timeseries", minutes] as const,
  incidents: (filters: Record<string, unknown>) => ["incidents", filters] as const,
  incident: (id: number) => ["incident", id] as const,
  replay: (id: number) => ["replay", id] as const,
  scenarios: ["scenarios"] as const,
  runs: ["runs"] as const,
  run: (id: number) => ["run", id] as const,
  status: ["simulation-status"] as const,
  policies: (includeInactive: boolean) => ["policies", includeInactive] as const,
  decisions: ["policy-decisions"] as const,
  alerts: (filters: Record<string, unknown>) => ["alerts", filters] as const,
  audit: (filters: Record<string, unknown>) => ["audit", filters] as const,
  networkGraph: ["graph-network"] as const,
  dependencyGraph: ["graph-dependencies"] as const,
  attackPaths: (entry: string, planId: number | null) => ["attack-paths", entry, planId] as const,
  telemetry: (assetId: string | null) => ["telemetry", assetId] as const,
  telemetryEvent: (id: number) => ["telemetry-event", id] as const,
};

function qs(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString()}` : "";
}

export const useZones = () => useQuery({ queryKey: qk.zones, queryFn: () => api.get<Zone[]>("/api/v1/zones"), staleTime: Infinity });
export const useRooms = () => useQuery({ queryKey: qk.rooms, queryFn: () => api.get<Room[]>("/api/v1/rooms"), staleTime: Infinity });

export const useAssetDetail = (id: string | null) =>
  useQuery({
    queryKey: qk.asset(id ?? ""),
    queryFn: () => api.get<AssetDetail>(`/api/v1/assets/${encodeURIComponent(id ?? "")}`),
    enabled: Boolean(id),
  });

export const useMetrics = () =>
  useQuery({ queryKey: qk.metrics, queryFn: () => api.get<MetricsSummary>("/api/v1/metrics/summary"), refetchInterval: 15_000 });

export const useTimeseries = (minutes = 30) =>
  useQuery({
    queryKey: qk.timeseries(minutes),
    queryFn: () => api.get<TimeseriesPoint[]>(`/api/v1/metrics/timeseries?minutes=${minutes}`),
    refetchInterval: 20_000,
  });

export const useIncidents = (filters: { open_only?: boolean; include_previous_epochs?: boolean; status?: IncidentStatus } = {}) =>
  useQuery({ queryKey: qk.incidents(filters), queryFn: () => api.get<IncidentSummary[]>(`/api/v1/incidents${qs(filters)}`) });

export const useIncident = (id: number | null) =>
  useQuery({
    queryKey: qk.incident(id ?? 0),
    queryFn: () => api.get<IncidentDetail>(`/api/v1/incidents/${id}`),
    enabled: id !== null && Number.isFinite(id),
  });

export const useReplay = (id: number | null, enabled: boolean) =>
  useQuery({
    queryKey: qk.replay(id ?? 0),
    queryFn: () => api.get<IncidentReplay>(`/api/v1/incidents/${id}/replay`),
    enabled: enabled && id !== null,
  });

export const useScenarios = () => useQuery({ queryKey: qk.scenarios, queryFn: () => api.get<Scenario[]>("/api/v1/scenarios") });
export const useRuns = () => useQuery({ queryKey: qk.runs, queryFn: () => api.get<SimulationRun[]>("/api/v1/simulation/runs?limit=20") });
export const useSimulationStatus = () =>
  useQuery({ queryKey: qk.status, queryFn: () => api.get<SimulationStatus>("/api/v1/simulation/status"), refetchInterval: 10_000 });

export const usePolicies = (includeInactive = false) =>
  useQuery({
    queryKey: qk.policies(includeInactive),
    queryFn: () => api.get<Policy[]>(`/api/v1/policies${qs({ include_inactive: includeInactive })}`),
  });

export const usePolicyDecisions = () =>
  useQuery({ queryKey: qk.decisions, queryFn: () => api.get<PolicyDecision[]>("/api/v1/policy-decisions?limit=100") });

export const useAlerts = (filters: Record<string, unknown> = {}) =>
  useQuery({ queryKey: qk.alerts(filters), queryFn: () => api.get<Alert[]>(`/api/v1/security-events${qs({ limit: 100, ...filters })}`) });

export const useAudit = (filters: Record<string, unknown>) =>
  useQuery({ queryKey: qk.audit(filters), queryFn: () => api.get<AuditEvent[]>(`/api/v1/audit${qs({ limit: 100, ...filters })}`) });

export const useNetworkGraph = () =>
  useQuery({ queryKey: qk.networkGraph, queryFn: () => api.get<NetworkGraph>("/api/v1/graph/network"), refetchInterval: 30_000 });

export const useDependencyGraph = () =>
  useQuery({ queryKey: qk.dependencyGraph, queryFn: () => api.get<DependencyGraph>("/api/v1/graph/dependencies"), staleTime: 60_000 });

export const useAttackPaths = (entry: string | null, planId: number | null = null) =>
  useQuery({
    queryKey: qk.attackPaths(entry ?? "", planId),
    queryFn: () =>
      api.post<AttackPathResult>("/api/v1/graph/attack-paths", {
        entry_asset_id: entry,
        max_depth: 3,
        containment_plan_id: planId,
      }),
    enabled: Boolean(entry),
  });

export const useTelemetry = (assetId: string | null) =>
  useQuery({
    queryKey: qk.telemetry(assetId),
    queryFn: () => api.get<TelemetryEvent[]>(`/api/v1/telemetry/events${qs({ asset_id: assetId, limit: 50 })}`),
  });

export const useTelemetryEvent = (id: number | null) =>
  useQuery({
    queryKey: qk.telemetryEvent(id ?? 0),
    queryFn: () => api.get<TelemetryEvent>(`/api/v1/telemetry/events/${id}`),
    enabled: id !== null,
  });

// ---- mutations ----------------------------------------------------------------------------

export function useRunScenario() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (scenarioId: string) => api.post<SimulationRun>(`/api/v1/scenarios/${scenarioId}/run`, { seed: 7 }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.runs });
      void client.invalidateQueries({ queryKey: qk.scenarios });
      void client.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}

export function useTransitionIncident(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { target_status: IncidentStatus; note: string; resolution?: string }) =>
      api.post<IncidentSummary>(`/api/v1/incidents/${id}/transition`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.incident(id) });
      void client.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}

export function useAddNote(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (note: string) => api.post(`/api/v1/incidents/${id}/notes`, { note }),
    onSuccess: () => void client.invalidateQueries({ queryKey: qk.incident(id) }),
  });
}

export function useGeneratePlans(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<ContainmentPlan[]>(`/api/v1/incidents/${id}/containment/plans`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.incident(id) });
      void client.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}

export function useApplyPlan(incidentId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, justification }: { planId: number; justification: string }) =>
      api.post<ContainmentPlan>(`/api/v1/containment/plans/${planId}/apply`, { justification, confirm: true }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.incident(incidentId) });
      void client.invalidateQueries({ queryKey: ["incidents"] });
      void client.invalidateQueries({ queryKey: qk.networkGraph });
    },
  });
}

export function useRecovery(incidentId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { rotate_credentials: boolean; release_containment: boolean; restore_trusted_state: boolean; note: string }) =>
      api.post<{ steps: Record<string, unknown>[] }>(`/api/v1/incidents/${incidentId}/recovery`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.incident(incidentId) });
      void client.invalidateQueries({ queryKey: qk.networkGraph });
    },
  });
}

export function useToggleGenerator() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => api.post<SimulationStatus>("/api/v1/simulation/generator", { enabled }),
    onSuccess: (data) => client.setQueryData(qk.status, data),
  });
}

export function useResetSimulation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) => api.post<{ epoch: number }>("/api/v1/simulation/reset", { reason }),
    onSuccess: () => void client.invalidateQueries(),
  });
}

export function useEvaluatePolicy() {
  return useMutation({
    mutationFn: (body: { policy_type: "NETWORK_FLOW" | "DEVICE_COMMAND"; source_asset_id: string; destination_asset_id: string; service_or_action: string }) =>
      api.post<PolicyEvaluation>("/api/v1/policies/evaluate", body),
  });
}

export function useVerifyAudit() {
  return useMutation({ mutationFn: () => api.get<AuditVerification>("/api/v1/audit/verify") });
}

export function useDeviceAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, action, reason }: { assetId: string; action: "revoke" | "rotate-key" | "clear-suspicion"; reason: string }) =>
      api.post(`/api/v1/devices/${assetId}/${action}`, { reason }),
    onSuccess: (_d, vars) => void client.invalidateQueries({ queryKey: qk.asset(vars.assetId) }),
  });
}

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => api.get<User>("/api/v1/auth/me"), retry: false, staleTime: 60_000 });
}
