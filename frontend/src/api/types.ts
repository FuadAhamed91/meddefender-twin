// Contracts mirroring the backend Pydantic schemas (see /api/openapi.json).

export type Role = "VIEWER" | "OPERATOR" | "SECURITY_ADMIN";
export type TrustState =
  | "UNREGISTERED"
  | "REGISTERED"
  | "AUTHENTICATED"
  | "SUSPICIOUS"
  | "QUARANTINED"
  | "REVOKED"
  | "OFFLINE";
export type ContainmentState = "NONE" | "RESTRICTED" | "ISOLATED";
export type Severity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Decision = "ACCEPTED" | "HELD" | "REJECTED";
export type PolicyOutcome = "PERMITTED" | "BLOCKED" | "ALLOWED_MONITOR_ONLY" | "TOPOLOGY";
export type AlertClassification =
  | "CONFIRMED_POLICY_VIOLATION"
  | "PROTOCOL_VIOLATION"
  | "VALIDATION_FAILURE"
  | "AUTHENTICATION_FAILURE"
  | "SUSPECTED_ANOMALY";
export type IncidentStatus =
  | "DETECTED"
  | "INVESTIGATING"
  | "CONTAINMENT_PROPOSED"
  | "CONTAINED"
  | "RECOVERY"
  | "RESOLVED";

export interface User {
  username: string;
  display_name: string;
  role: Role;
  permissions: string[];
}

export interface Bounds {
  min: [number, number];
  max: [number, number];
}

export interface Zone {
  id: string;
  name: string;
  description: string;
  vlan_id: number;
  subnet: string;
  trust_level: string;
  color: string;
  bounds: Bounds;
}

export interface Room {
  id: string;
  name: string;
  area_zone_id: string | null;
  kind: string;
  bounds: Bounds;
}

export interface AssetPosition {
  x: number;
  y: number;
  rotation: number;
  approximate?: boolean;
  attached_via?: string;
}

export interface AssetSummary {
  id: string;
  display_name: string;
  asset_kind: string;
  asset_type: string;
  is_logical: boolean;
  network_zone_id: string | null;
  room_id: string | null;
  twin_node: string | null;
  position: AssetPosition | null;
  label_height: number | null;
  ip_address: string | null;
  criticality: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  discovered: boolean;
  is_active: boolean;
  containment_state: ContainmentState;
  trust_state: TrustState | null;
  registration_status: string | null;
  open_incident_count: number;
  last_seen_at: string | null;
  twin_version: number;
  reported_decision: Decision | null;
}

export type Values = Record<string, unknown>;

export interface MetricComparison {
  metric: string;
  reported: unknown;
  predicted: number;
  trusted: unknown;
  delta: number | null;
  tolerance: number;
  within_tolerance: boolean;
}

export interface Discrepancy {
  evaluated_at: string;
  model: string;
  comparisons: MetricComparison[];
  within_tolerance: boolean;
  note: string;
}

export interface TwinState {
  asset_id: string;
  version: number;
  reported: Values | null;
  reported_at: string | null;
  reported_decision: Decision | null;
  reported_event_id?: number | null;
  trusted: Values | null;
  trusted_at: string | null;
  trusted_event_id?: number | null;
  predicted: Values | null;
  predicted_at: string | null;
  model_name?: string | null;
  discrepancy: Discrepancy | null;
  trust_state?: TrustState | null;
}

export interface TwinSnapshot {
  last_event_id: number;
  epoch: number;
  generated_at: string;
  assets: AssetSummary[];
  twin_states: TwinState[];
}

export interface PolicyView {
  id: string;
  name: string;
  policy_type: "NETWORK_FLOW" | "DEVICE_COMMAND";
  source: string;
  destination: string;
  service_or_action: string;
  effect: "ALLOW" | "DENY";
  priority: number;
  enforcement_mode: "ENFORCED" | "MONITOR" | "DISABLED";
  enforcement_point_id: string | null;
  origin: "BASELINE" | "CONTAINMENT" | "ADMIN";
  rationale: string;
}

export interface Relationship {
  id: number;
  source_asset_id: string;
  destination_asset_id: string;
  relationship_type: "DATA_FLOW" | "CONTROL" | "AUTH" | "MANAGEMENT" | "L2_UPLINK";
  service: string;
  protocol_label: string;
  port: number | null;
  origin: "BASELINE" | "OBSERVED";
  description: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  observation_count: number;
  crosses_zone_boundary: boolean | null;
  policy_status: PolicyOutcome;
  decision: "ALLOW" | "DENY" | null;
  matched_policy_id: string | null;
  policy_reason: string;
}

export interface DependencyView {
  id: number;
  dependent_asset_id: string;
  dependent_name: string;
  provider_asset_id: string;
  provider_name: string;
  dependency_type: string;
  criticality: string;
  description: string;
  carried_by_relationship_id: number | null;
}

export interface AssetDetail {
  asset: AssetSummary & {
    description: string;
    zone_name: string | null;
    room_name: string | null;
    is_simulated: boolean;
  };
  identity: null | {
    registration_status: string;
    trust_state: TrustState;
    trust_reason: string;
    trust_changed_at: string;
    telemetry_profile: string | null;
    allowed_message_types: string[];
    last_seen_at: string | null;
    last_authenticated_at: string | null;
    credentials: {
      key_version: number;
      algorithm: string;
      fingerprint: string;
      status: string;
      created_at: string;
      retired_at: string | null;
      retired_reason: string | null;
    }[];
  };
  telemetry_profile: null | {
    id: string;
    label: string;
    model: string | null;
    notes: string;
    fields: {
      name: string;
      label: string;
      unit: string | null;
      kind: string;
      minimum: number | null;
      maximum: number | null;
      choices: string[];
    }[];
  };
  twin_state: TwinState | null;
  permissions: {
    outbound: PolicyView[];
    inbound: PolicyView[];
    defaults: PolicyView[];
    accepted_commands: { action: string; label: string; effect: string; permitted_sources: string[] }[];
  };
  network_relationships: Relationship[];
  dependencies: { relies_on: DependencyView[]; relied_on_by: DependencyView[] };
  incidents: {
    id: number;
    reference: string | null;
    title: string;
    status: IncidentStatus;
    severity: Severity;
    role: string;
    epoch: number;
    current_epoch: boolean;
    created_at: string;
  }[];
  recent_audit: {
    id: number;
    occurred_at: string;
    actor_id: string;
    action: string;
    decision: string;
    reason: string;
    correlation_id: string;
  }[];
  recent_telemetry: {
    id: number;
    received_at: string;
    message_type: string | null;
    decision: Decision;
    reason_code: string;
    integrity_verified: boolean;
    sequence: number | null;
  }[];
}

export interface Check {
  check: string;
  status: "PASS" | "FAIL" | "WARN" | "SKIPPED" | "NOT_APPLICABLE" | "INFO";
  detail: string;
  code?: string;
}

export interface TelemetryEvent {
  id: number;
  received_at: string;
  claimed_device_id: string | null;
  asset_id: string | null;
  message_type: string | null;
  sequence: number | null;
  device_timestamp: string | null;
  key_version: number | null;
  message_digest: string;
  integrity_verified: boolean;
  decision: Decision;
  reason_code: string;
  reason: string;
  checks: Check[];
  payload: Values | null;
  channel: string;
  simulation_run_id: number | null;
  correlation_id: string;
  epoch: number;
  raw_message?: string;
}

export interface Alert {
  id: number;
  created_at: string;
  rule_id: string;
  title: string;
  classification: AlertClassification;
  severity: Severity;
  asset_id: string | null;
  subject_ref: string;
  evidence: Record<string, unknown>;
  confidence_note: string;
  telemetry_event_id: number | null;
  policy_decision_id: number | null;
  incident_id: number | null;
  simulation_run_id: number | null;
  correlation_id: string;
  epoch: number;
}

export interface PolicyDecision {
  id: number;
  evaluated_at: string;
  policy_type: string;
  source_ref: string;
  source_asset_id: string | null;
  destination_ref: string;
  destination_asset_id: string | null;
  service_or_action: string;
  decision: "ALLOW" | "DENY";
  outcome: PolicyOutcome;
  matched_policy_id: string | null;
  reason: string;
  explanation: Record<string, unknown>;
  telemetry_event_id: number | null;
  correlation_id: string;
  epoch: number;
}

export interface IncidentSummary {
  id: number;
  reference: string | null;
  title: string;
  summary: string;
  category: string;
  status: IncidentStatus;
  severity: Severity;
  primary_asset_id: string | null;
  primary_subject_ref: string;
  detection_rule_id: string;
  alert_count: number;
  recovery_completed: boolean;
  resolution: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  epoch: number;
}

export interface IncidentEvent {
  id: number;
  occurred_at: string;
  event_type: string;
  actor_type: string;
  actor_id: string;
  summary: string;
  details: Record<string, unknown>;
  alert_id: number | null;
  policy_decision_id: number | null;
  telemetry_event_id: number | null;
  correlation_id: string;
}

export interface PlanMetrics {
  paths_before: number;
  paths_after: number;
  path_reduction_pct: number;
  reachable_before: number;
  reachable_after: number;
  high_value_reachable_before: number;
  high_value_reachable_after: number;
  flows_blocked: number;
  dependencies_disrupted: number;
  services_impaired: number;
  services_degraded: number;
}

export interface ReachableAsset {
  asset_id: string;
  display_name: string;
  network_zone_id: string | null;
  criticality: string;
  min_hops: number;
  classification: "DEMONSTRATED" | "PERMITTED" | "HYPOTHETICAL";
  via: string[];
  services: string[];
}

export interface EdgeView {
  source: string;
  destination: string;
  service: string;
  outcome: PolicyOutcome;
  matched_policy_id: string | null;
  reason: string;
  relationship_id: number | null;
  origin: string;
  observed: boolean;
}

export interface ContainmentPlan {
  id: number;
  incident_id: number;
  strategy: "ISOLATE_ASSET" | "RESTRICT_TO_REQUIRED_FLOWS" | "ISOLATE_ZONE_EGRESS" | "REVOKE_CREDENTIALS";
  target_asset_id: string;
  name: string;
  description: string;
  status: "PROPOSED" | "APPLIED" | "SUPERSEDED" | "ROLLED_BACK";
  required_role: Role;
  analysis: {
    metrics: PlanMetrics;
    blocked_flows: EdgeView[];
    reachable_before: ReachableAsset[];
    residual_reachable: ReachableAsset[];
    residual_paths: { hops: EdgeView[]; classification: string; length: number; target: string }[];
    disrupted_dependencies: {
      dependent_asset_id: string;
      provider_asset_id: string;
      dependency_type: string;
      criticality: string;
      description: string;
      reason: string;
    }[];
    service_impact: { asset_id: string; display_name: string; status: string; reasons: string[] }[];
    summary: string;
    limitations: string[];
    required_role_reason: string;
    containment_state: ContainmentState;
  };
  policy_changes: Record<string, unknown>[];
  identity_changes: Record<string, unknown>[];
  created_at: string;
  applied_at: string | null;
  apply_justification: string | null;
  rolled_back_at: string | null;
}

export interface IncidentDetail extends IncidentSummary {
  resolution_note: string | null;
  events: IncidentEvent[];
  assets: { asset_id: string; role: string; added_at: string }[];
  alerts: Alert[];
  policy_decisions: PolicyDecision[];
  containment_plans: ContainmentPlan[];
  allowed_transitions: IncidentStatus[];
  read_only: boolean;
}

export interface ReplayFrame {
  t: string;
  kind: "telemetry" | "policy_decision" | "alert" | "audit" | "incident_event";
  ref_id: number;
  summary: string;
  assets: string[];
  event_type?: string;
  edge?: { source: string; destination: string; service: string; outcome: PolicyOutcome };
  detail: Record<string, unknown>;
  incident_status: IncidentStatus | null;
  highlighted_assets: string[];
  trust_states: Record<string, string>;
}

export interface IncidentReplay {
  incident: { id: number; reference: string; title: string; status: IncidentStatus; severity: Severity; epoch: number };
  frames: ReplayFrame[];
  sources: Record<string, number>;
  note: string;
}

export interface AttackPathResult {
  entry_asset_id: string;
  max_depth: number;
  assumptions: string[];
  paths: { hops: EdgeView[]; classification: string; length: number; target: string }[];
  path_count: number;
  truncated: boolean;
  reachable_assets: ReachableAsset[];
  blocked_edges_from_entry: EdgeView[];
  observed_attempts: {
    destination: string;
    service: string;
    outcome: PolicyOutcome;
    matched_policy_id: string | null;
    policy_decision_id: number;
    reason: string;
  }[];
  nearby_unreachable: {
    asset_id: string;
    display_name: string;
    network_zone_id: string | null;
    physically_nearby: boolean;
    same_network_segment: boolean;
    why_unreachable: string;
  }[];
  potentially_affected_dependents: {
    asset_id: string;
    display_name: string;
    via_provider: string;
    dependency_type: string;
    criticality: string;
    chain: string[];
  }[];
}

export interface NetworkGraph {
  nodes: { id: string; display_name: string; asset_kind: string; network_zone_id: string | null; room_id: string | null; discovered: boolean }[];
  edges: {
    id: number;
    source: string;
    destination: string;
    relationship_type: Relationship["relationship_type"];
    service: string;
    protocol_label: string;
    origin: "BASELINE" | "OBSERVED";
    policy_status: PolicyOutcome;
    matched_policy_id: string | null;
    policy_reason: string;
    crosses_zone_boundary: boolean;
    last_seen_at: string | null;
    observation_count: number;
  }[];
}

export interface DependencyGraph {
  nodes: { id: string; display_name: string; is_logical: boolean; asset_kind: string; criticality: string }[];
  edges: {
    id: number;
    dependent: string;
    provider: string;
    dependency_type: string;
    criticality: string;
    description: string;
    carried_by_relationship_id: number | null;
  }[];
}

export interface MetricsSummary {
  epoch: number;
  generated_at: string;
  inventory: { assets: number; logical_services: number; device_identities: number; discovered_unregistered: number; by_kind: Record<string, number> };
  trust_distribution: Partial<Record<TrustState, number>>;
  incidents: { open: number; total: number; open_by_severity: Partial<Record<Severity, number>>; open_by_status: Partial<Record<IncidentStatus, number>> };
  telemetry: { last_hour: Record<Decision, number>; epoch_total: Record<Decision, number> };
  rejections_by_reason: Record<string, number>;
  policy_denials: Record<string, number>;
  blocked_flows: number;
  alerts: { total: number; by_classification: Partial<Record<AlertClassification, number>>; by_severity: Partial<Record<Severity, number>> };
  communication_anomalies: number;
  containment: { active_containment_policies: number; assets_contained: { asset_id: string; state: ContainmentState }[] };
  recent_alerts: Pick<Alert, "id" | "created_at" | "rule_id" | "title" | "classification" | "severity" | "subject_ref" | "incident_id">[];
}

export interface TimeseriesPoint {
  minute: string;
  ACCEPTED: number;
  HELD: number;
  REJECTED: number;
}

export interface Scenario {
  id: string;
  title: string;
  summary: string;
  narrative: string;
  expected: string[];
  controls: string[];
  preconditions: string[];
  precondition_checks: { label: string; met: boolean; detail: string }[];
}

export interface ScenarioStep {
  index: number;
  label: string;
  actor: string;
  transport_source?: string | null;
  telemetry_event_id?: number;
  decision: string;
  reason_code?: string;
  reason?: string;
  authenticated?: boolean;
  checks?: Check[];
  alert_ids?: number[];
  incident_refs?: string[];
  trust_changes?: { asset_id: string; from: string; to: string; reason: string }[];
  policy_decision_ids?: number[];
  correlation_id?: string;
  flows?: { src_ip: string; dst_ip: string; service: string; enforcement_action: string }[];
}

export interface SimulationRun {
  id: number;
  scenario_id: string;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  seed: number;
  started_at: string;
  completed_at: string | null;
  epoch: number;
  parameters: Record<string, unknown>;
  result: null | {
    steps: ScenarioStep[];
    expectations: { label: string; met: boolean; detail: string }[];
    expectations_met: number;
    expectations_total: number;
    all_met: boolean;
    notes: string[];
    artifacts: Record<string, unknown> & { focus_assets?: string[] };
    error: { code: string; message: string } | null;
    incidents: string[];
  };
  correlation_id: string;
}

export interface SimulationStatus {
  epoch: number;
  generator_enabled: boolean;
  tick_count: number;
  last_tick_at: string | null;
  last_reset_at: string | null;
  interval_seconds: number;
}

export interface Policy {
  id: string;
  name: string;
  description: string;
  rationale: string;
  policy_type: "NETWORK_FLOW" | "DEVICE_COMMAND";
  source_asset_id: string | null;
  source_zone_id: string | null;
  destination_asset_id: string | null;
  destination_zone_id: string | null;
  service_or_action: string;
  effect: "ALLOW" | "DENY";
  priority: number;
  enforcement_mode: "ENFORCED" | "MONITOR" | "DISABLED";
  enforcement_point_id: string | null;
  origin: "BASELINE" | "CONTAINMENT" | "ADMIN";
  incident_id: number | null;
  containment_plan_id: number | null;
  is_active: boolean;
  created_at: string;
  deactivated_at: string | null;
}

export interface PolicyEvaluation {
  decision: "ALLOW" | "DENY";
  outcome: PolicyOutcome;
  matched_policy_id: string | null;
  reason: string;
  explanation: Record<string, unknown>;
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor_type: string;
  actor_id: string;
  action: string;
  target_type: string;
  target_id: string;
  decision: string;
  reason: string;
  correlation_id: string;
  incident_id: number | null;
  simulation_run_id: number | null;
  details: Record<string, unknown>;
  epoch: number;
  prev_hash: string;
  entry_hash: string;
}

export interface AuditVerification {
  valid: boolean;
  checked: number;
  first_invalid_id: number | null;
  problem: string | null;
  head_hash: string | null;
  note: string;
}

export interface LiveEvent {
  id?: number;
  type: string;
  created_at?: string;
  payload?: Record<string, unknown>;
  latest_event_id?: number;
  epoch?: number;
  reason?: string;
}
