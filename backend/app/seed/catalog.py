"""Baseline security model for the simulated hospital.

Network relationships describe *expected* communication paths. Policies decide what is
*permitted*. Operational dependencies describe what *relies on* what. The three are kept
separate on purpose; see docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import AssetKind, Criticality, DependencyType, RelationshipType

# --------------------------------------------------------------------------------------
# Asset criticality and descriptions (layout file holds placement; this holds semantics)
# --------------------------------------------------------------------------------------

ASSET_DETAILS: dict[str, tuple[Criticality, str]] = {
    "ICU-MONITOR-01": (
        Criticality.HIGH,
        "Simulated bedside monitor streaming synthetic vitals to the central gateway.",
    ),
    "ICU-MONITOR-02": (
        Criticality.HIGH,
        "Simulated bedside monitor streaming synthetic vitals to the central gateway.",
    ),
    "ICU-MONITOR-03": (
        Criticality.HIGH,
        "Simulated bedside monitor streaming synthetic vitals to the central gateway.",
    ),
    "ICU-PUMP-01": (
        Criticality.HIGH,
        "Simulated infusion-pump representation reporting synthetic rate and volume. Accepts no remote commands in this model.",
    ),
    "ICU-GATEWAY-01": (
        Criticality.HIGH,
        "Aggregates bedside monitor feeds and forwards them to the central monitoring server; pushes alarm-limit configuration to monitors.",
    ),
    "ICU-SWITCH-01": (
        Criticality.HIGH,
        "ICU access switch; enforcement point for intra-ICU segmentation (ACLs / private VLANs assumed).",
    ),
    "ICU-WS-01": (
        Criticality.MEDIUM,
        "Nurse-station workstation used for central monitoring view and clinical records.",
    ),
    "HVAC-SENSOR-01": (
        Criticality.MEDIUM,
        "Wall-mounted ICU temperature/humidity sensor on the building-management network.",
    ),
    "IMG-CT-01": (
        Criticality.HIGH,
        "Simulated CT modality representation sending studies to the imaging archive.",
    ),
    "IMG-WS-01": (Criticality.MEDIUM, "Imaging review workstation querying the imaging archive."),
    "IMG-SWITCH-01": (
        Criticality.MEDIUM,
        "Imaging access switch; enforcement point for intra-imaging segmentation.",
    ),
    "HVAC-SENSOR-02": (
        Criticality.MEDIUM,
        "CT room temperature/humidity sensor on the building-management network.",
    ),
    "NET-GW-01": (
        Criticality.CRITICAL,
        "Core zone gateway / firewall; enforcement point for all inter-zone traffic.",
    ),
    "APP-SERVER-01": (
        Criticality.HIGH,
        "Hospital application server hosting the simulated clinical records service.",
    ),
    "MON-SERVER-01": (
        Criticality.HIGH,
        "Central monitoring server receiving aggregated monitor data from the ICU gateway.",
    ),
    "IAM-SERVER-01": (Criticality.CRITICAL, "Identity and access service used for staff sign-in."),
    "IMG-SERVER-01": (Criticality.HIGH, "Imaging archive server storing simulated studies."),
    "NET-SENSOR-01": (
        Criticality.MEDIUM,
        "Passive network sensor that reports observed flows to MedDefender (signed flow reports).",
    ),
    "SOC-WS-01": (Criticality.MEDIUM, "Security operations workstation."),
    "BMS-GW-01": (Criticality.MEDIUM, "Building-management gateway supervising HVAC equipment."),
    "HVAC-CTRL-01": (
        Criticality.HIGH,
        "Controller for air-handling unit AHU-1 serving the ICU and imaging suite.",
    ),
}

LOGICAL_SERVICES: list[tuple[str, str, Criticality, str]] = [
    (
        "SVC-CENTRAL-MONITORING",
        "Central patient monitoring",
        Criticality.CRITICAL,
        "Simulated central view of bedside monitor data. Modeled dependency chain only; not a clinical workflow claim.",
    ),
    (
        "SVC-CLINICAL-RECORDS",
        "Clinical records access",
        Criticality.HIGH,
        "Simulated access to clinical records from workstations.",
    ),
    (
        "SVC-IMAGING",
        "Imaging acquisition & review",
        Criticality.HIGH,
        "Simulated acquisition, archiving and review of imaging studies.",
    ),
    (
        "SVC-ICU-ENVIRONMENT",
        "ICU environmental control",
        Criticality.HIGH,
        "Simulated temperature control for the ICU via AHU-1.",
    ),
    (
        "SVC-STAFF-IDENTITY",
        "Staff sign-in & access",
        Criticality.CRITICAL,
        "Simulated staff authentication used by clinical applications.",
    ),
]

# --------------------------------------------------------------------------------------
# Device identities: asset -> telemetry profile
# --------------------------------------------------------------------------------------

IDENTITY_PROFILES: dict[str, str] = {
    "ICU-MONITOR-01": "patient_monitor",
    "ICU-MONITOR-02": "patient_monitor",
    "ICU-MONITOR-03": "patient_monitor",
    "ICU-PUMP-01": "infusion_pump",
    "ICU-GATEWAY-01": "monitoring_gateway",
    "ICU-WS-01": "heartbeat",
    "IMG-CT-01": "imaging_modality",
    "IMG-WS-01": "heartbeat",
    "HVAC-SENSOR-01": "environment_sensor",
    "HVAC-SENSOR-02": "environment_sensor",
    "HVAC-CTRL-01": "hvac_controller",
    "BMS-GW-01": "heartbeat",
    "NET-SENSOR-01": "network_sensor",
}

# --------------------------------------------------------------------------------------
# Network relationships (expected communication paths)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowDef:
    source: str
    destination: str
    service: str
    protocol: str
    port: int | None
    kind: RelationshipType
    description: str


SERVICES: dict[str, tuple[str, int | None]] = {
    "monitor-feed": ("Monitor data feed (synthetic, tcp/24105)", 24105),
    "pump-status": ("Pump status feed (synthetic, tcp/24110)", 24110),
    "device-config": ("Device configuration channel (synthetic, tcp/24120)", 24120),
    "hl7-mllp": ("HL7 v2 over MLLP (tcp/2575)", 2575),
    "https": ("HTTPS (tcp/443)", 443),
    "ldaps": ("LDAPS (tcp/636)", 636),
    "dicom": ("DICOM (tcp/11112)", 11112),
    "bacnet": ("BACnet/IP (udp/47808)", 47808),
    "ssh": ("SSH (tcp/22)", 22),
    "smb": ("SMB (tcp/445)", 445),
    "link": ("Layer-2 uplink", None),
}


def _flow(src: str, dst: str, service: str, kind: RelationshipType, description: str) -> FlowDef:
    protocol, port = SERVICES[service]
    return FlowDef(src, dst, service, protocol, port, kind, description)


DF, CT, AU, MG = (
    RelationshipType.DATA_FLOW,
    RelationshipType.CONTROL,
    RelationshipType.AUTH,
    RelationshipType.MANAGEMENT,
)

BASELINE_FLOWS: list[FlowDef] = [
    _flow(
        "ICU-MONITOR-01", "ICU-GATEWAY-01", "monitor-feed", DF, "Bedside data to central gateway"
    ),
    _flow(
        "ICU-MONITOR-02", "ICU-GATEWAY-01", "monitor-feed", DF, "Bedside data to central gateway"
    ),
    _flow(
        "ICU-MONITOR-03", "ICU-GATEWAY-01", "monitor-feed", DF, "Bedside data to central gateway"
    ),
    _flow("ICU-PUMP-01", "ICU-GATEWAY-01", "pump-status", DF, "Pump status to central gateway"),
    _flow(
        "ICU-GATEWAY-01", "ICU-MONITOR-01", "device-config", CT, "Alarm-limit configuration push"
    ),
    _flow(
        "ICU-GATEWAY-01", "ICU-MONITOR-02", "device-config", CT, "Alarm-limit configuration push"
    ),
    _flow(
        "ICU-GATEWAY-01", "ICU-MONITOR-03", "device-config", CT, "Alarm-limit configuration push"
    ),
    _flow("ICU-GATEWAY-01", "MON-SERVER-01", "hl7-mllp", DF, "Aggregated monitoring feed"),
    _flow("MON-SERVER-01", "APP-SERVER-01", "hl7-mllp", DF, "Vitals results into clinical records"),
    _flow("ICU-WS-01", "MON-SERVER-01", "https", DF, "Central monitoring view"),
    _flow("ICU-WS-01", "APP-SERVER-01", "https", DF, "Clinical records access"),
    _flow("ICU-WS-01", "IAM-SERVER-01", "ldaps", AU, "Staff sign-in"),
    _flow("APP-SERVER-01", "IAM-SERVER-01", "ldaps", AU, "Application authentication"),
    _flow("IMG-CT-01", "IMG-SERVER-01", "dicom", DF, "Study storage"),
    _flow("IMG-WS-01", "IMG-SERVER-01", "dicom", DF, "Study query/retrieve"),
    _flow("IMG-WS-01", "IAM-SERVER-01", "ldaps", AU, "Staff sign-in"),
    _flow("IMG-SERVER-01", "APP-SERVER-01", "hl7-mllp", DF, "Imaging reports and orders"),
    _flow("BMS-GW-01", "HVAC-CTRL-01", "bacnet", CT, "Supervisory control"),
    _flow("HVAC-CTRL-01", "BMS-GW-01", "bacnet", DF, "Controller status"),
    _flow("HVAC-SENSOR-01", "BMS-GW-01", "bacnet", DF, "ICU environment readings"),
    _flow("HVAC-SENSOR-02", "BMS-GW-01", "bacnet", DF, "CT room environment readings"),
    _flow("SOC-WS-01", "NET-SENSOR-01", "https", MG, "Sensor management"),
]

L2_UPLINKS: list[tuple[str, str]] = [
    ("ICU-MONITOR-01", "ICU-SWITCH-01"),
    ("ICU-MONITOR-02", "ICU-SWITCH-01"),
    ("ICU-MONITOR-03", "ICU-SWITCH-01"),
    ("ICU-PUMP-01", "ICU-SWITCH-01"),
    ("ICU-GATEWAY-01", "ICU-SWITCH-01"),
    ("ICU-WS-01", "ICU-SWITCH-01"),
    ("ICU-SWITCH-01", "NET-GW-01"),
    ("IMG-CT-01", "IMG-SWITCH-01"),
    ("IMG-WS-01", "IMG-SWITCH-01"),
    ("IMG-SWITCH-01", "NET-GW-01"),
    ("APP-SERVER-01", "NET-GW-01"),
    ("MON-SERVER-01", "NET-GW-01"),
    ("IAM-SERVER-01", "NET-GW-01"),
    ("IMG-SERVER-01", "NET-GW-01"),
    ("NET-SENSOR-01", "NET-GW-01"),
    ("SOC-WS-01", "NET-GW-01"),
    ("HVAC-SENSOR-01", "BMS-GW-01"),
    ("HVAC-SENSOR-02", "BMS-GW-01"),
    ("HVAC-CTRL-01", "BMS-GW-01"),
    ("BMS-GW-01", "NET-GW-01"),
]

# --------------------------------------------------------------------------------------
# Operational dependencies: (dependent, provider, type, criticality, description, carried_by)
# carried_by = (source, destination, service) of the flow that carries the dependency.
# --------------------------------------------------------------------------------------

DependencyDef = tuple[str, str, DependencyType, Criticality, str, tuple[str, str, str] | None]

H, M, L = Criticality.HIGH, Criticality.MEDIUM, Criticality.LOW

BASELINE_DEPENDENCIES: list[DependencyDef] = [
    (
        "SVC-CENTRAL-MONITORING",
        "ICU-GATEWAY-01",
        DependencyType.DATA_AGGREGATION,
        H,
        "Gateway aggregates bedside data for the central view.",
        ("ICU-GATEWAY-01", "MON-SERVER-01", "hl7-mllp"),
    ),
    (
        "SVC-CENTRAL-MONITORING",
        "MON-SERVER-01",
        DependencyType.APPLICATION_HOSTING,
        H,
        "Central monitoring application host.",
        None,
    ),
    (
        "SVC-CENTRAL-MONITORING",
        "ICU-MONITOR-01",
        DependencyType.DATA_SOURCE,
        H,
        "Bay 1 data source.",
        ("ICU-MONITOR-01", "ICU-GATEWAY-01", "monitor-feed"),
    ),
    (
        "SVC-CENTRAL-MONITORING",
        "ICU-MONITOR-02",
        DependencyType.DATA_SOURCE,
        H,
        "Bay 2 data source.",
        ("ICU-MONITOR-02", "ICU-GATEWAY-01", "monitor-feed"),
    ),
    (
        "SVC-CENTRAL-MONITORING",
        "ICU-MONITOR-03",
        DependencyType.DATA_SOURCE,
        H,
        "Bay 3 data source.",
        ("ICU-MONITOR-03", "ICU-GATEWAY-01", "monitor-feed"),
    ),
    (
        "SVC-CENTRAL-MONITORING",
        "ICU-WS-01",
        DependencyType.DISPLAY_ACCESS,
        M,
        "Nurse-station display of the central view.",
        ("ICU-WS-01", "MON-SERVER-01", "https"),
    ),
    (
        "SVC-CENTRAL-MONITORING",
        "ICU-SWITCH-01",
        DependencyType.NETWORK_TRANSPORT,
        H,
        "ICU access network.",
        None,
    ),
    (
        "SVC-CENTRAL-MONITORING",
        "NET-GW-01",
        DependencyType.NETWORK_TRANSPORT,
        H,
        "Inter-zone transport ICU -> server room.",
        None,
    ),
    (
        "ICU-MONITOR-01",
        "ICU-GATEWAY-01",
        DependencyType.CONFIGURATION_MANAGEMENT,
        L,
        "Central alarm-limit management (bedside configuration remains possible in this model).",
        ("ICU-GATEWAY-01", "ICU-MONITOR-01", "device-config"),
    ),
    (
        "ICU-MONITOR-02",
        "ICU-GATEWAY-01",
        DependencyType.CONFIGURATION_MANAGEMENT,
        L,
        "Central alarm-limit management (bedside configuration remains possible in this model).",
        ("ICU-GATEWAY-01", "ICU-MONITOR-02", "device-config"),
    ),
    (
        "ICU-MONITOR-03",
        "ICU-GATEWAY-01",
        DependencyType.CONFIGURATION_MANAGEMENT,
        L,
        "Central alarm-limit management (bedside configuration remains possible in this model).",
        ("ICU-GATEWAY-01", "ICU-MONITOR-03", "device-config"),
    ),
    (
        "MON-SERVER-01",
        "ICU-GATEWAY-01",
        DependencyType.DATA_FEED,
        H,
        "Monitoring server receives the aggregated feed.",
        ("ICU-GATEWAY-01", "MON-SERVER-01", "hl7-mllp"),
    ),
    (
        "SVC-CLINICAL-RECORDS",
        "APP-SERVER-01",
        DependencyType.APPLICATION_HOSTING,
        H,
        "Clinical records application host.",
        None,
    ),
    (
        "SVC-CLINICAL-RECORDS",
        "SVC-STAFF-IDENTITY",
        DependencyType.AUTHENTICATION,
        H,
        "Users must sign in.",
        None,
    ),
    (
        "SVC-CLINICAL-RECORDS",
        "MON-SERVER-01",
        DependencyType.DATA_FEED,
        M,
        "Vitals charting feed.",
        ("MON-SERVER-01", "APP-SERVER-01", "hl7-mllp"),
    ),
    (
        "SVC-CLINICAL-RECORDS",
        "ICU-WS-01",
        DependencyType.DISPLAY_ACCESS,
        L,
        "ICU access point for records.",
        ("ICU-WS-01", "APP-SERVER-01", "https"),
    ),
    (
        "SVC-CLINICAL-RECORDS",
        "NET-GW-01",
        DependencyType.NETWORK_TRANSPORT,
        H,
        "Inter-zone transport.",
        None,
    ),
    (
        "APP-SERVER-01",
        "IAM-SERVER-01",
        DependencyType.AUTHENTICATION,
        H,
        "Application authenticates users against IAM.",
        ("APP-SERVER-01", "IAM-SERVER-01", "ldaps"),
    ),
    (
        "SVC-IMAGING",
        "IMG-CT-01",
        DependencyType.DATA_SOURCE,
        H,
        "Study acquisition.",
        ("IMG-CT-01", "IMG-SERVER-01", "dicom"),
    ),
    (
        "SVC-IMAGING",
        "IMG-SERVER-01",
        DependencyType.APPLICATION_HOSTING,
        H,
        "Imaging archive.",
        None,
    ),
    (
        "SVC-IMAGING",
        "IMG-WS-01",
        DependencyType.DISPLAY_ACCESS,
        M,
        "Study review.",
        ("IMG-WS-01", "IMG-SERVER-01", "dicom"),
    ),
    (
        "SVC-IMAGING",
        "IMG-SWITCH-01",
        DependencyType.NETWORK_TRANSPORT,
        H,
        "Imaging access network.",
        None,
    ),
    (
        "SVC-IMAGING",
        "NET-GW-01",
        DependencyType.NETWORK_TRANSPORT,
        H,
        "Inter-zone transport imaging -> server room.",
        None,
    ),
    (
        "SVC-IMAGING",
        "SVC-STAFF-IDENTITY",
        DependencyType.AUTHENTICATION,
        M,
        "Reviewers sign in.",
        None,
    ),
    (
        "SVC-IMAGING",
        "HVAC-CTRL-01",
        DependencyType.ENVIRONMENTAL_CONTROL,
        M,
        "Equipment-room cooling via AHU-1.",
        None,
    ),
    (
        "SVC-ICU-ENVIRONMENT",
        "HVAC-CTRL-01",
        DependencyType.ENVIRONMENTAL_CONTROL,
        H,
        "AHU-1 controller.",
        None,
    ),
    (
        "SVC-ICU-ENVIRONMENT",
        "HVAC-SENSOR-01",
        DependencyType.SENSOR_FEEDBACK,
        H,
        "Room temperature feedback.",
        ("HVAC-SENSOR-01", "BMS-GW-01", "bacnet"),
    ),
    (
        "SVC-ICU-ENVIRONMENT",
        "BMS-GW-01",
        DependencyType.SUPERVISORY_CONTROL,
        M,
        "Supervisory setpoint management.",
        ("BMS-GW-01", "HVAC-CTRL-01", "bacnet"),
    ),
    (
        "HVAC-CTRL-01",
        "HVAC-SENSOR-01",
        DependencyType.SENSOR_FEEDBACK,
        H,
        "Control loop uses the ICU sensor reading.",
        ("HVAC-SENSOR-01", "BMS-GW-01", "bacnet"),
    ),
    (
        "SVC-STAFF-IDENTITY",
        "IAM-SERVER-01",
        DependencyType.APPLICATION_HOSTING,
        H,
        "Identity service host.",
        None,
    ),
    (
        "SVC-STAFF-IDENTITY",
        "NET-GW-01",
        DependencyType.NETWORK_TRANSPORT,
        H,
        "Inter-zone transport.",
        None,
    ),
]

# --------------------------------------------------------------------------------------
# Zone-boundary rules (explicit denies for zone pairs that never communicate)
# --------------------------------------------------------------------------------------

ZONE_DENIES: list[tuple[str, str, str, str]] = [
    (
        "ZB-BMS-TO-ICU",
        "ZONE-BMS",
        "ZONE-ICU",
        "Building-management devices never initiate traffic into clinical care zones.",
    ),
    (
        "ZB-BMS-TO-IMG",
        "ZONE-BMS",
        "ZONE-IMG",
        "Building-management devices never initiate traffic into imaging.",
    ),
    (
        "ZB-BMS-TO-DC",
        "ZONE-BMS",
        "ZONE-DC",
        "Building management is isolated from hospital IT systems.",
    ),
    (
        "ZB-ICU-TO-IMG",
        "ZONE-ICU",
        "ZONE-IMG",
        "No clinical workflow in this model links ICU devices to imaging devices.",
    ),
    (
        "ZB-IMG-TO-ICU",
        "ZONE-IMG",
        "ZONE-ICU",
        "No clinical workflow in this model links imaging devices to ICU devices.",
    ),
    (
        "ZB-ICU-TO-BMS",
        "ZONE-ICU",
        "ZONE-BMS",
        "Clinical devices have no reason to reach building management.",
    ),
    (
        "ZB-IMG-TO-BMS",
        "ZONE-IMG",
        "ZONE-BMS",
        "Imaging devices have no reason to reach building management.",
    ),
]

# Command permissions: (source, target, action, rationale)
COMMAND_ALLOWS: list[tuple[str, str, str, str]] = [
    ("ICU-GATEWAY-01", "ICU-MONITOR-01", "update_alarm_limits", "Central alarm-limit management."),
    ("ICU-GATEWAY-01", "ICU-MONITOR-02", "update_alarm_limits", "Central alarm-limit management."),
    ("ICU-GATEWAY-01", "ICU-MONITOR-03", "update_alarm_limits", "Central alarm-limit management."),
    ("BMS-GW-01", "HVAC-CTRL-01", "set_setpoint", "Supervisory setpoint control."),
    ("BMS-GW-01", "HVAC-CTRL-01", "set_mode", "Supervisory mode control."),
]

ASSET_KIND_BY_NAME = {kind.value: kind for kind in AssetKind}
