"""Telemetry profiles and the device command catalog.

Ranges here are *synthetic device measurement / physical plausibility limits* used for
input validation. They are not clinical thresholds and carry no clinical meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import MessageType


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str  # "float" | "int" | "enum"
    label: str
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class TelemetryProfile:
    id: str
    label: str
    fields: tuple[FieldSpec, ...]
    model: str | None = None
    notes: str = ""

    def field(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)


PROFILES: dict[str, TelemetryProfile] = {
    "patient_monitor": TelemetryProfile(
        id="patient_monitor",
        label="Bedside patient monitor (synthetic vitals)",
        fields=(
            FieldSpec("heart_rate_bpm", "int", "Heart rate", "bpm", 20, 300),
            FieldSpec("spo2_pct", "int", "SpO2", "%", 50, 100),
            FieldSpec("resp_rate_bpm", "int", "Respiratory rate", "/min", 0, 80),
            FieldSpec(
                "alarm_config_version", "int", "Alarm configuration version", None, 0, 100_000
            ),
        ),
        notes="Physiological values are not predicted by the twin; only measurement-range checks apply.",
    ),
    "infusion_pump": TelemetryProfile(
        id="infusion_pump",
        label="Infusion pump representation",
        fields=(
            FieldSpec("rate_ml_h", "float", "Programmed rate", "mL/h", 0, 999),
            FieldSpec("volume_infused_ml", "float", "Volume infused", "mL", 0, 10_000),
            FieldSpec("pump_state", "enum", "Pump state", choices=("running", "paused", "stopped")),
        ),
        model="infusion_volume",
    ),
    "monitoring_gateway": TelemetryProfile(
        id="monitoring_gateway",
        label="Central monitoring gateway",
        fields=(
            FieldSpec("connected_devices", "int", "Connected devices", None, 0, 64),
            FieldSpec("forwarded_per_min", "int", "Messages forwarded", "/min", 0, 100_000),
            FieldSpec("queue_depth", "int", "Queue depth", None, 0, 100_000),
        ),
    ),
    "imaging_modality": TelemetryProfile(
        id="imaging_modality",
        label="Imaging modality representation",
        fields=(
            FieldSpec(
                "modality_state", "enum", "State", choices=("idle", "scanning", "transferring")
            ),
            FieldSpec("studies_sent_total", "int", "Studies sent", None, 0, 1_000_000_000),
            FieldSpec("gantry_temp_c", "float", "Gantry temperature", "°C", 5, 60),
        ),
    ),
    "environment_sensor": TelemetryProfile(
        id="environment_sensor",
        label="Environmental sensor",
        fields=(
            FieldSpec("temperature_c", "float", "Room temperature", "°C", -20, 60),
            FieldSpec("humidity_pct", "float", "Relative humidity", "%", 0, 100),
        ),
        model="room_thermal",
        notes="Predicted temperature comes from the HVAC controller's trusted setpoint and mode.",
    ),
    "hvac_controller": TelemetryProfile(
        id="hvac_controller",
        label="HVAC controller",
        fields=(
            FieldSpec("mode", "enum", "Mode", choices=("cool", "heat", "auto", "off")),
            FieldSpec("setpoint_c", "float", "Setpoint", "°C", 16, 28),
            FieldSpec("supply_air_temp_c", "float", "Supply air temperature", "°C", 5, 40),
            FieldSpec("fan", "enum", "Fan", choices=("on", "off")),
        ),
    ),
    "heartbeat": TelemetryProfile(
        id="heartbeat",
        label="Heartbeat only",
        fields=(
            FieldSpec("uptime_s", "int", "Uptime", "s", 0, 10_000_000_000),
            FieldSpec("status", "enum", "Status", choices=("ok", "degraded")),
        ),
    ),
    "network_sensor": TelemetryProfile(
        id="network_sensor",
        label="Network monitoring sensor (flow reports)",
        fields=(),
    ),
}

HEARTBEAT_PROFILE = PROFILES["heartbeat"]


@dataclass(frozen=True)
class CommandSpec:
    action: str
    label: str
    target_types: tuple[str, ...]
    parameters: tuple[FieldSpec, ...]
    effect: str
    cross_checks: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (lower, higher)


COMMANDS: dict[str, CommandSpec] = {
    "update_alarm_limits": CommandSpec(
        action="update_alarm_limits",
        label="Update alarm limits",
        target_types=("patient_monitor",),
        parameters=(
            FieldSpec("hr_low", "int", "Heart-rate low limit", "bpm", 20, 120),
            FieldSpec("hr_high", "int", "Heart-rate high limit", "bpm", 60, 250),
            FieldSpec("spo2_low", "int", "SpO2 low limit", "%", 70, 99),
        ),
        effect="Replaces the monitor's simulated alarm limits and increments its configuration version.",
        cross_checks=(("hr_low", "hr_high"),),
    ),
    "set_setpoint": CommandSpec(
        action="set_setpoint",
        label="Set temperature setpoint",
        target_types=("hvac_controller",),
        parameters=(FieldSpec("setpoint_c", "float", "Setpoint", "°C", 16, 28),),
        effect="Changes the simulated HVAC setpoint; the room model follows it.",
    ),
    "set_mode": CommandSpec(
        action="set_mode",
        label="Set HVAC mode",
        target_types=("hvac_controller",),
        parameters=(FieldSpec("mode", "enum", "Mode", choices=("cool", "heat", "auto", "off")),),
        effect="Changes the simulated HVAC operating mode.",
    ),
}

# Which message types each telemetry profile's identity may send (least privilege).
DEFAULT_MESSAGE_TYPES: dict[str, tuple[MessageType, ...]] = {
    "patient_monitor": (MessageType.TELEMETRY, MessageType.HEARTBEAT),
    "infusion_pump": (MessageType.TELEMETRY, MessageType.HEARTBEAT),
    "monitoring_gateway": (MessageType.TELEMETRY, MessageType.HEARTBEAT, MessageType.COMMAND),
    "imaging_modality": (MessageType.TELEMETRY, MessageType.HEARTBEAT),
    "environment_sensor": (MessageType.TELEMETRY, MessageType.HEARTBEAT),
    "hvac_controller": (MessageType.TELEMETRY, MessageType.HEARTBEAT),
    "heartbeat": (MessageType.HEARTBEAT, MessageType.COMMAND),
    "network_sensor": (MessageType.FLOW_REPORT, MessageType.HEARTBEAT),
}


class FieldError(ValueError):
    """A field failed type or range validation."""


def check_field(spec: FieldSpec, value: Any) -> tuple[bool, str | None]:
    """Return (type_ok, range_error). Type errors are schema failures; range errors are
    content-validation failures. Booleans are rejected for numeric fields."""
    if spec.kind == "enum":
        if not isinstance(value, str):
            return False, None
        if value not in spec.choices:
            return True, f"{spec.name}={value!r} is not one of {list(spec.choices)}"
        return True, None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False, None
    if spec.kind == "int" and not (isinstance(value, int) or float(value).is_integer()):
        return False, None
    if spec.minimum is not None and value < spec.minimum:
        return True, f"{spec.name}={value} is below the limit {spec.minimum}"
    if spec.maximum is not None and value > spec.maximum:
        return True, f"{spec.name}={value} is above the limit {spec.maximum}"
    return True, None
