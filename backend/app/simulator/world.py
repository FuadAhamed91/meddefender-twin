"""The simulated physical world: device ground truth and deterministic physics.

Nothing in the security pipeline reads this module's state. The twin learns about the world
only through signed messages that devices emit.
"""

from __future__ import annotations

import math
import random
from typing import Any

from sqlalchemy.orm import Session

from app.models import SimDevice

# Synthetic per-bed vital-sign baselines. Not derived from any real patient.
_MONITOR_BASELINES = {
    "ICU-MONITOR-01": {"hr": 74, "spo2": 97, "rr": 15},
    "ICU-MONITOR-02": {"hr": 86, "spo2": 95, "rr": 18},
    "ICU-MONITOR-03": {"hr": 66, "spo2": 98, "rr": 13},
}
_DEFAULT_ALARM_LIMITS = {"hr_low": 50, "hr_high": 120, "spo2_low": 90}

ROOM_OFFSETS_C = {"HVAC-SENSOR-01": 0.3, "HVAC-SENSOR-02": -0.2}
TAU_ACTIVE_S = 900.0
TAU_OFF_S = 3600.0
AMBIENT_C = 25.5


def initial_state(asset_id: str, profile: str) -> dict[str, Any]:
    if profile == "patient_monitor":
        return {
            "baseline": dict(_MONITOR_BASELINES.get(asset_id, {"hr": 75, "spo2": 97, "rr": 15})),
            "alarm_limits": dict(_DEFAULT_ALARM_LIMITS),
            "alarm_config_version": 1,
        }
    if profile == "infusion_pump":
        return {"rate_ml_h": 42.0, "volume_infused_ml": 120.0, "pump_state": "running"}
    if profile == "monitoring_gateway":
        return {"connected_devices": 4, "queue_depth": 0}
    if profile == "imaging_modality":
        return {
            "modality_state": "idle",
            "studies_sent_total": 1842,
            "gantry_temp_c": 24.0,
            "phase_tick": 0,
        }
    if profile == "hvac_controller":
        return {"mode": "auto", "setpoint_c": 21.0, "fan": "on"}
    if profile == "environment_sensor":
        offset = ROOM_OFFSETS_C.get(asset_id, 0.0)
        return {
            "temperature_c": round(21.0 + offset, 2),
            "humidity_pct": 44.0 if asset_id.endswith("01") else 41.0,
        }
    if profile == "heartbeat":
        return {"uptime_s": 12 * 86_400, "status": "ok"}
    return {}


def _rng(asset_id: str, tick: int) -> random.Random:
    # Deterministic per (asset, tick): replays of the same simulation produce the same values.
    return random.Random(f"{asset_id}:{tick}")


def advance(
    asset_id: str,
    profile: str,
    state: dict[str, Any],
    *,
    dt: float,
    tick: int,
    hvac: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the next ground-truth state after ``dt`` seconds."""
    s = dict(state)
    if profile == "infusion_pump" and s.get("pump_state") == "running":
        s["volume_infused_ml"] = round(
            float(s["volume_infused_ml"]) + float(s["rate_ml_h"]) * dt / 3600.0, 3
        )
    elif profile == "imaging_modality":
        phase = (int(s.get("phase_tick", 0)) + 1) % 12
        s["phase_tick"] = phase
        s["modality_state"] = (
            "idle" if phase < 7 else ("scanning" if phase < 10 else "transferring")
        )
        if phase == 11:
            s["studies_sent_total"] = int(s["studies_sent_total"]) + 1
        target = 31.0 if s["modality_state"] == "scanning" else 24.0
        s["gantry_temp_c"] = round(
            float(s["gantry_temp_c"]) + (target - float(s["gantry_temp_c"])) * 0.3, 2
        )
    elif profile == "environment_sensor" and hvac is not None:
        active = hvac.get("mode") != "off"
        target = (
            float(hvac.get("setpoint_c", 21.0)) + ROOM_OFFSETS_C.get(asset_id, 0.0)
            if active
            else AMBIENT_C
        )
        tau = TAU_ACTIVE_S if active else TAU_OFF_S
        current = float(s["temperature_c"])
        noise = _rng(asset_id, tick).uniform(-0.05, 0.05)
        s["temperature_c"] = round(target + (current - target) * math.exp(-dt / tau) + noise, 2)
        s["humidity_pct"] = round(
            min(
                100.0,
                max(0.0, float(s["humidity_pct"]) + _rng(asset_id, tick + 7).uniform(-0.2, 0.2)),
            ),
            1,
        )
    elif profile == "heartbeat":
        s["uptime_s"] = int(s.get("uptime_s", 0)) + int(dt)
    return s


def telemetry_payload(
    asset_id: str, profile: str, state: dict[str, Any], tick: int
) -> dict[str, Any]:
    """What an honest device reports about its ground-truth state."""
    if profile == "patient_monitor":
        base = state["baseline"]
        rng = _rng(asset_id, tick)
        phase = 2 * math.pi * tick / 18.0
        return {
            "heart_rate_bpm": round(base["hr"] + 3 * math.sin(phase) + rng.uniform(-1, 1)),
            "spo2_pct": int(
                min(100, round(base["spo2"] + 0.6 * math.sin(phase / 2) + rng.uniform(-0.4, 0.4)))
            ),
            "resp_rate_bpm": round(base["rr"] + math.sin(phase / 3) + rng.uniform(-0.5, 0.5)),
            "alarm_config_version": int(state["alarm_config_version"]),
        }
    if profile == "infusion_pump":
        return {
            "rate_ml_h": float(state["rate_ml_h"]),
            "volume_infused_ml": round(float(state["volume_infused_ml"]), 2),
            "pump_state": state["pump_state"],
        }
    if profile == "monitoring_gateway":
        rng = _rng(asset_id, tick)
        connected = int(state["connected_devices"])
        return {
            "connected_devices": connected,
            "forwarded_per_min": connected * 12 + rng.randint(0, 4),
            "queue_depth": int(state.get("queue_depth", 0)) + rng.randint(0, 2),
        }
    if profile == "imaging_modality":
        return {
            "modality_state": state["modality_state"],
            "studies_sent_total": int(state["studies_sent_total"]),
            "gantry_temp_c": float(state["gantry_temp_c"]),
        }
    if profile == "hvac_controller":
        supply = float(state["setpoint_c"]) - (8.0 if state["mode"] != "off" else 0.0)
        return {
            "mode": state["mode"],
            "setpoint_c": float(state["setpoint_c"]),
            "supply_air_temp_c": round(supply + _rng(asset_id, tick).uniform(-0.2, 0.2), 2),
            "fan": state["fan"],
        }
    if profile == "environment_sensor":
        return {
            "temperature_c": float(state["temperature_c"]),
            "humidity_pct": float(state["humidity_pct"]),
        }
    if profile == "heartbeat":
        return {"uptime_s": int(state["uptime_s"]), "status": state.get("status", "ok")}
    return {}


class WorldCommandSink:
    """Applies policy-permitted commands to device ground truth (the command broker's
    delivery step). Denied commands never reach this code."""

    def deliver(
        self, session: Session, target_asset_id: str, action: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        sim = session.get(SimDevice, target_asset_id, with_for_update=True)
        if sim is None or not sim.online:
            return {
                "delivered": False,
                "note": f"{target_asset_id} is not reachable in the simulation",
            }
        state = dict(sim.physical_state)
        before = {
            k: state.get(k) for k in ("alarm_limits", "alarm_config_version", "setpoint_c", "mode")
        }
        if action == "update_alarm_limits":
            state["alarm_limits"] = {
                k: int(parameters[k]) for k in ("hr_low", "hr_high", "spo2_low")
            }
            state["alarm_config_version"] = int(state.get("alarm_config_version", 0)) + 1
        elif action == "set_setpoint":
            state["setpoint_c"] = float(parameters["setpoint_c"])
        elif action == "set_mode":
            state["mode"] = str(parameters["mode"])
            state["fan"] = "off" if state["mode"] == "off" else "on"
        else:
            return {"delivered": False, "note": f"{action} has no simulated effect"}
        sim.physical_state = state
        after = {k: state.get(k) for k in before}
        return {"delivered": True, "before": before, "after": after}
