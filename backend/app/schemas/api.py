"""Request and response contracts (also drive the OpenAPI document)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

AssetId = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{1,47}$")]
Note = Annotated[str, StringConstraints(min_length=3, max_length=2000, strip_whitespace=True)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- errors ---------------------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    correlation_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---- auth -----------------------------------------------------------------------------


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class UserOut(BaseModel):
    username: str
    display_name: str
    role: str
    permissions: list[str]


class LoginResponse(BaseModel):
    user: UserOut
    csrf_token: str


# ---- hospital model ---------------------------------------------------------------------


class ZoneOut(ORM):
    id: str
    name: str
    description: str
    vlan_id: int
    subnet: str
    trust_level: str
    color: str
    bounds: dict[str, Any]


class RoomOut(ORM):
    id: str
    name: str
    area_zone_id: str | None
    kind: str
    bounds: dict[str, Any]


class AssetSummary(BaseModel):
    id: str
    display_name: str
    asset_kind: str
    asset_type: str
    is_logical: bool
    network_zone_id: str | None
    room_id: str | None
    twin_node: str | None
    position: dict[str, Any] | None
    label_height: float | None
    ip_address: str | None
    criticality: str
    discovered: bool
    is_active: bool
    containment_state: str
    trust_state: str | None
    registration_status: str | None
    open_incident_count: int
    last_seen_at: datetime | None
    twin_version: int
    reported_decision: str | None


class TwinStateOut(BaseModel):
    asset_id: str
    version: int
    reported: dict[str, Any] | None
    reported_at: datetime | None
    reported_decision: str | None
    reported_event_id: int | None
    trusted: dict[str, Any] | None
    trusted_at: datetime | None
    trusted_event_id: int | None
    predicted: dict[str, Any] | None
    predicted_at: datetime | None
    model_name: str | None
    discrepancy: dict[str, Any] | None


class TwinSnapshot(BaseModel):
    last_event_id: int
    epoch: int
    generated_at: datetime
    assets: list[AssetSummary]
    twin_states: list[TwinStateOut]


# ---- telemetry --------------------------------------------------------------------------


class IngestResponse(BaseModel):
    decision: str
    event_id: int
    correlation_id: str
    reason_code: str | None = Field(
        None, description="Only disclosed when the sender authenticated (prevents ID enumeration)."
    )


class TelemetryEventOut(ORM):
    id: int
    received_at: datetime
    claimed_device_id: str | None
    asset_id: str | None
    message_type: str | None
    sequence: int | None
    device_timestamp: datetime | None
    key_version: int | None
    message_digest: str
    integrity_verified: bool
    decision: str
    reason_code: str
    reason: str
    checks: list[Any]
    payload: dict[str, Any] | None
    channel: str
    simulation_run_id: int | None
    correlation_id: str
    epoch: int


class TelemetryEventDetail(TelemetryEventOut):
    raw_message: str


# ---- policies ---------------------------------------------------------------------------


class PolicyOut(ORM):
    id: str
    name: str
    description: str
    rationale: str
    policy_type: str
    source_asset_id: str | None
    source_zone_id: str | None
    destination_asset_id: str | None
    destination_zone_id: str | None
    service_or_action: str
    effect: str
    priority: int
    enforcement_mode: str
    enforcement_point_id: str | None
    origin: str
    incident_id: int | None
    containment_plan_id: int | None
    is_active: bool
    created_at: datetime
    deactivated_at: datetime | None


class PolicyEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_type: Literal["NETWORK_FLOW", "DEVICE_COMMAND"]
    source_asset_id: AssetId
    destination_asset_id: AssetId
    service_or_action: Annotated[str, StringConstraints(pattern=r"^(\*|[a-z0-9_-]{1,48})$")]


class PolicyEvaluationOut(BaseModel):
    decision: str
    outcome: str
    matched_policy_id: str | None
    reason: str
    explanation: dict[str, Any]


class PolicyModeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enforcement_mode: Literal["ENFORCED", "MONITOR", "DISABLED"]
    reason: Note


class PolicyDecisionOut(ORM):
    id: int
    evaluated_at: datetime
    policy_type: str
    source_ref: str
    source_asset_id: str | None
    destination_ref: str
    destination_asset_id: str | None
    service_or_action: str
    decision: str
    outcome: str
    matched_policy_id: str | None
    reason: str
    explanation: dict[str, Any]
    telemetry_event_id: int | None
    correlation_id: str
    epoch: int


# ---- alerts and incidents -------------------------------------------------------------------


class AlertOut(ORM):
    id: int
    created_at: datetime
    rule_id: str
    title: str
    classification: str
    severity: str
    asset_id: str | None
    subject_ref: str
    evidence: dict[str, Any]
    confidence_note: str
    telemetry_event_id: int | None
    policy_decision_id: int | None
    incident_id: int | None
    simulation_run_id: int | None
    correlation_id: str
    epoch: int


class IncidentSummaryOut(ORM):
    id: int
    reference: str | None
    title: str
    summary: str
    category: str
    status: str
    severity: str
    primary_asset_id: str | None
    primary_subject_ref: str
    detection_rule_id: str
    alert_count: int
    recovery_completed: bool
    resolution: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    epoch: int


class IncidentEventOut(ORM):
    id: int
    occurred_at: datetime
    event_type: str
    actor_type: str
    actor_id: str
    summary: str
    details: dict[str, Any]
    alert_id: int | None
    policy_decision_id: int | None
    telemetry_event_id: int | None
    correlation_id: str


class IncidentAssetOut(ORM):
    asset_id: str
    role: str
    added_at: datetime


class ContainmentPlanOut(ORM):
    id: int
    incident_id: int
    strategy: str
    target_asset_id: str
    name: str
    description: str
    status: str
    required_role: str
    analysis: dict[str, Any]
    policy_changes: list[Any]
    identity_changes: list[Any]
    created_at: datetime
    applied_at: datetime | None
    apply_justification: str | None
    rolled_back_at: datetime | None


class IncidentDetailOut(IncidentSummaryOut):
    resolution_note: str | None
    events: list[IncidentEventOut]
    assets: list[IncidentAssetOut]
    alerts: list[AlertOut]
    policy_decisions: list[PolicyDecisionOut]
    containment_plans: list[ContainmentPlanOut]
    allowed_transitions: list[str]
    read_only: bool


class IncidentTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_status: Literal[
        "INVESTIGATING", "CONTAINMENT_PROPOSED", "CONTAINED", "RECOVERY", "RESOLVED"
    ]
    note: Note
    resolution: (
        Literal["FALSE_POSITIVE", "BENIGN", "NO_ACTION_REQUIRED", "ACCEPTED_RISK"] | None
    ) = None


class IncidentNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Note


class ApplyPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    justification: Note
    confirm: Literal[True]


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotate_credentials: bool = True
    release_containment: bool = True
    restore_trusted_state: bool = True
    note: Note


# ---- audit ------------------------------------------------------------------------------


class AuditEventOut(ORM):
    id: int
    occurred_at: datetime
    actor_type: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    decision: str
    reason: str
    correlation_id: str
    incident_id: int | None
    simulation_run_id: int | None
    details: dict[str, Any]
    epoch: int
    prev_hash: str
    entry_hash: str


class AuditVerifyOut(BaseModel):
    valid: bool
    checked: int
    first_invalid_id: int | None
    problem: str | None
    head_hash: str | None
    note: str


# ---- simulation -------------------------------------------------------------------------


class SimulationStatusOut(BaseModel):
    epoch: int
    generator_enabled: bool
    tick_count: int
    last_tick_at: datetime | None
    last_reset_at: datetime | None
    interval_seconds: float


class GeneratorToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Note


class ScenarioRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 7


class SimulationRunOut(ORM):
    id: int
    scenario_id: str
    status: str
    seed: int
    started_at: datetime
    completed_at: datetime | None
    epoch: int
    parameters: dict[str, Any]
    result: dict[str, Any] | None
    correlation_id: str


class AttackPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_asset_id: AssetId
    max_depth: Annotated[int, Field(ge=1, le=5)] = 3
    containment_plan_id: int | None = None


class EnrollmentRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claimed_device_id: AssetId
    requested_type: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,48}$")]
    details: dict[str, Annotated[str, StringConstraints(max_length=120)]] = Field(
        default_factory=dict, max_length=10
    )


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Note
