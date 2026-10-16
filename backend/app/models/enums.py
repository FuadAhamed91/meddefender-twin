"""Domain enumerations. Stored as VARCHAR with CHECK constraints."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    SECURITY_ADMIN = "SECURITY_ADMIN"


ROLE_RANK: dict[UserRole, int] = {
    UserRole.VIEWER: 1,
    UserRole.OPERATOR: 2,
    UserRole.SECURITY_ADMIN: 3,
}


class AssetKind(StrEnum):
    MEDICAL_DEVICE = "MEDICAL_DEVICE"
    IT_SYSTEM = "IT_SYSTEM"
    IT_ENDPOINT = "IT_ENDPOINT"
    NETWORK = "NETWORK"
    BUILDING_SYSTEM = "BUILDING_SYSTEM"
    SECURITY = "SECURITY"
    CLINICAL_SERVICE = "CLINICAL_SERVICE"
    UNKNOWN_ENDPOINT = "UNKNOWN_ENDPOINT"


class Criticality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


CRITICALITY_RANK: dict[Criticality, int] = {
    Criticality.LOW: 1,
    Criticality.MEDIUM: 2,
    Criticality.HIGH: 3,
    Criticality.CRITICAL: 4,
}


class RegistrationStatus(StrEnum):
    REGISTERED = "REGISTERED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    UNREGISTERED = "UNREGISTERED"


class TrustState(StrEnum):
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"
    AUTHENTICATED = "AUTHENTICATED"
    SUSPICIOUS = "SUSPICIOUS"
    QUARANTINED = "QUARANTINED"
    REVOKED = "REVOKED"
    OFFLINE = "OFFLINE"


class CredentialStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ROTATED = "ROTATED"
    REVOKED = "REVOKED"


class ContainmentState(StrEnum):
    NONE = "NONE"
    RESTRICTED = "RESTRICTED"
    ISOLATED = "ISOLATED"


class MessageType(StrEnum):
    TELEMETRY = "TELEMETRY"
    HEARTBEAT = "HEARTBEAT"
    COMMAND = "COMMAND"
    FLOW_REPORT = "FLOW_REPORT"


class TelemetryDecision(StrEnum):
    ACCEPTED = "ACCEPTED"
    HELD = "HELD"
    REJECTED = "REJECTED"


class CheckStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - not a password
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class IngestChannel(StrEnum):
    HTTP = "HTTP"
    GENERATOR = "GENERATOR"
    SCENARIO = "SCENARIO"


class RelationshipType(StrEnum):
    DATA_FLOW = "DATA_FLOW"
    CONTROL = "CONTROL"
    AUTH = "AUTH"
    MANAGEMENT = "MANAGEMENT"
    L2_UPLINK = "L2_UPLINK"


class RelationshipOrigin(StrEnum):
    BASELINE = "BASELINE"
    OBSERVED = "OBSERVED"


class DependencyType(StrEnum):
    DATA_SOURCE = "DATA_SOURCE"
    DATA_AGGREGATION = "DATA_AGGREGATION"
    DATA_FEED = "DATA_FEED"
    APPLICATION_HOSTING = "APPLICATION_HOSTING"
    AUTHENTICATION = "AUTHENTICATION"
    NETWORK_TRANSPORT = "NETWORK_TRANSPORT"
    ENVIRONMENTAL_CONTROL = "ENVIRONMENTAL_CONTROL"
    SENSOR_FEEDBACK = "SENSOR_FEEDBACK"
    SUPERVISORY_CONTROL = "SUPERVISORY_CONTROL"
    DISPLAY_ACCESS = "DISPLAY_ACCESS"
    CONFIGURATION_MANAGEMENT = "CONFIGURATION_MANAGEMENT"


class PolicyType(StrEnum):
    NETWORK_FLOW = "NETWORK_FLOW"
    DEVICE_COMMAND = "DEVICE_COMMAND"


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class EnforcementMode(StrEnum):
    ENFORCED = "ENFORCED"
    MONITOR = "MONITOR"
    DISABLED = "DISABLED"


class PolicyOrigin(StrEnum):
    BASELINE = "BASELINE"
    CONTAINMENT = "CONTAINMENT"
    ADMIN = "ADMIN"


class DecisionOutcome(StrEnum):
    PERMITTED = "PERMITTED"
    BLOCKED = "BLOCKED"
    ALLOWED_MONITOR_ONLY = "ALLOWED_MONITOR_ONLY"


class AlertClassification(StrEnum):
    CONFIRMED_POLICY_VIOLATION = "CONFIRMED_POLICY_VIOLATION"
    PROTOCOL_VIOLATION = "PROTOCOL_VIOLATION"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    SUSPECTED_ANOMALY = "SUSPECTED_ANOMALY"


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class IncidentStatus(StrEnum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    CONTAINMENT_PROPOSED = "CONTAINMENT_PROPOSED"
    CONTAINED = "CONTAINED"
    RECOVERY = "RECOVERY"
    RESOLVED = "RESOLVED"


class ActorType(StrEnum):
    USER = "USER"
    DEVICE = "DEVICE"
    SYSTEM = "SYSTEM"
    SIMULATOR = "SIMULATOR"


class AuditDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    INFO = "INFO"


class SimulationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PlanStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"


class EnrollmentStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
