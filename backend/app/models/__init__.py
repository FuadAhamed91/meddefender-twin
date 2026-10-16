"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.audit import AuditEvent, AuditImmutableError
from app.models.hospital import Asset, HospitalZone, Room
from app.models.identity import (
    DeviceCredential,
    DeviceIdentity,
    DeviceNonce,
    DeviceReplayState,
    EnrollmentRequest,
)
from app.models.incidents import (
    ContainmentPlan,
    Incident,
    IncidentAsset,
    IncidentEvent,
    SecurityAlert,
)
from app.models.network import (
    NetworkRelationship,
    OperationalDependency,
    PolicyDecision,
    SecurityPolicy,
)
from app.models.simulation import EventLogEntry, SimulationRun, SimulationState
from app.models.telemetry import SimDevice, TelemetryEvent, TwinState
from app.models.users import User, UserSession

__all__ = [
    "Asset",
    "AuditEvent",
    "AuditImmutableError",
    "ContainmentPlan",
    "DeviceCredential",
    "DeviceIdentity",
    "DeviceNonce",
    "DeviceReplayState",
    "EnrollmentRequest",
    "EventLogEntry",
    "HospitalZone",
    "Incident",
    "IncidentAsset",
    "IncidentEvent",
    "NetworkRelationship",
    "OperationalDependency",
    "PolicyDecision",
    "Room",
    "SecurityAlert",
    "SecurityPolicy",
    "SimDevice",
    "SimulationRun",
    "SimulationState",
    "TelemetryEvent",
    "TwinState",
    "User",
    "UserSession",
]
