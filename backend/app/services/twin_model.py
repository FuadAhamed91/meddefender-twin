"""Deterministic predicted-state models.

Predictions use only *trusted* inputs (never reported or simulator ground-truth values):

* ``room_thermal`` - first-order thermal response. The room approaches the HVAC
  controller's trusted setpoint plus a modeled room offset while the HVAC is active, and
  drifts toward ambient when it is off:

      T(t) = T_target + (T_anchor - T_target) * exp(-dt / tau)

  The anchor is the last trusted reading, so the model catches abrupt manipulation but not
  slow drifts that stay inside tolerance (a documented false-negative).
* ``infusion_volume`` - volume infused grows by rate x elapsed time while running.

Comparisons return per-metric status with the tolerance used, so every discrepancy is
explainable. A discrepancy is a *suspected* anomaly, never proof of attack.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import TwinState

ROOM_MODEL = "room_thermal_v1"
INFUSION_MODEL = "infusion_volume_v1"

TAU_ACTIVE_S = 900.0
TAU_OFF_S = 3600.0
AMBIENT_C = 25.5
TEMPERATURE_TOLERANCE_C = 1.5
# Modeled steady-state offsets from setpoint (equipment heat load, room position).
ROOM_OFFSETS_C: dict[str, float] = {"HVAC-SENSOR-01": 0.3, "HVAC-SENSOR-02": -0.2}
HVAC_FOR_SENSOR: dict[str, str] = {
    "HVAC-SENSOR-01": "HVAC-CTRL-01",
    "HVAC-SENSOR-02": "HVAC-CTRL-01",
}


@dataclass
class Prediction:
    model: str
    values: dict[str, float]
    tolerance: dict[str, float]
    inputs: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass
class MetricComparison:
    metric: str
    reported: Any
    predicted: float
    trusted: Any
    delta: float | None
    tolerance: float
    within_tolerance: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "reported": self.reported,
            "predicted": self.predicted,
            "trusted": self.trusted,
            "delta": self.delta,
            "tolerance": self.tolerance,
            "within_tolerance": self.within_tolerance,
        }


def predict(
    session: Session, asset_id: str, model: str | None, twin: TwinState, now: datetime
) -> Prediction | None:
    if model == "room_thermal":
        return _predict_room(session, asset_id, twin, now)
    if model == "infusion_volume":
        return _predict_infusion(twin, now)
    return None


def _predict_room(
    session: Session, asset_id: str, twin: TwinState, now: datetime
) -> Prediction | None:
    hvac_id = HVAC_FOR_SENSOR.get(asset_id)
    hvac = session.get(TwinState, hvac_id) if hvac_id else None
    if hvac is None or not hvac.trusted:
        return None
    if not twin.trusted or twin.trusted_at is None or "temperature_c" not in twin.trusted:
        return None
    try:
        setpoint = float(hvac.trusted["setpoint_c"])
        mode = str(hvac.trusted["mode"])
        anchor = float(twin.trusted["temperature_c"])
    except (KeyError, TypeError, ValueError):
        return None
    active = mode != "off"
    target = setpoint + ROOM_OFFSETS_C.get(asset_id, 0.0) if active else AMBIENT_C
    tau = TAU_ACTIVE_S if active else TAU_OFF_S
    dt = max(0.0, (now - twin.trusted_at).total_seconds())
    value = target + (anchor - target) * math.exp(-dt / tau)
    return Prediction(
        model=ROOM_MODEL,
        values={"temperature_c": round(value, 2)},
        tolerance={"temperature_c": TEMPERATURE_TOLERANCE_C},
        inputs={
            "hvac_asset_id": hvac_id,
            "hvac_trusted_setpoint_c": setpoint,
            "hvac_trusted_mode": mode,
            "anchor_trusted_temperature_c": anchor,
            "anchor_at": twin.trusted_at.isoformat(),
            "elapsed_s": round(dt, 1),
            "tau_s": tau,
            "target_c": round(target, 2),
        },
        note="First-order thermal model anchored on the last trusted reading.",
    )


def _predict_infusion(twin: TwinState, now: datetime) -> Prediction | None:
    if not twin.trusted or twin.trusted_at is None:
        return None
    try:
        rate = float(twin.trusted["rate_ml_h"])
        volume = float(twin.trusted["volume_infused_ml"])
        state = str(twin.trusted["pump_state"])
    except (KeyError, TypeError, ValueError):
        return None
    dt = max(0.0, (now - twin.trusted_at).total_seconds())
    predicted = volume + (rate * dt / 3600.0 if state == "running" else 0.0)
    tolerance = max(0.5, round(predicted * 0.02, 2))
    return Prediction(
        model=INFUSION_MODEL,
        values={"volume_infused_ml": round(predicted, 2)},
        tolerance={"volume_infused_ml": tolerance},
        inputs={
            "trusted_rate_ml_h": rate,
            "trusted_volume_ml": volume,
            "trusted_pump_state": state,
            "elapsed_s": round(dt, 1),
        },
        note="Volume grows by programmed rate x elapsed time while running.",
    )


def compare(
    prediction: Prediction, reported: dict[str, Any], trusted: dict[str, Any] | None
) -> list[MetricComparison]:
    results: list[MetricComparison] = []
    for metric, predicted in prediction.values.items():
        tolerance = prediction.tolerance[metric]
        value = reported.get(metric)
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        delta = round(float(value) - predicted, 3)
        results.append(
            MetricComparison(
                metric=metric,
                reported=value,
                predicted=predicted,
                trusted=(trusted or {}).get(metric),
                delta=delta,
                tolerance=tolerance,
                within_tolerance=abs(delta) <= tolerance,
            )
        )
    return results
