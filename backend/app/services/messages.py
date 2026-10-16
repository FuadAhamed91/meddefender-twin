"""Wire format for simulated device messages (envelope v1) and its strict validation.

The MAC covers the exact raw request body; the server never re-serialises before
verifying, so there is no canonicalisation ambiguity. Header:
``X-MD-Signature: hmac-sha256=<64 hex chars>``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import MessageType

DEVICE_ID_PATTERN = r"^[A-Z0-9][A-Z0-9-]{1,47}$"
DeviceId = Annotated[str, StringConstraints(pattern=DEVICE_ID_PATTERN)]
IPv4 = Annotated[
    str,
    StringConstraints(pattern=r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$"),
]


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    v: Literal[1]
    device_id: DeviceId
    key_version: Annotated[int, Field(ge=1, le=1_000_000)]
    sequence: Annotated[int, Field(ge=1, le=2**62)]
    timestamp: AwareDatetime
    nonce: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    type: MessageType
    payload: dict[str, Any]


class CommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target: DeviceId
    action: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,48}$")]
    parameters: dict[str, Any]


class FlowRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    src_ip: IPv4
    dst_ip: IPv4
    service: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,32}$")]
    dst_port: Annotated[int, Field(ge=0, le=65535)] | None = None
    packets: Annotated[int, Field(ge=0)]
    bytes: Annotated[int, Field(ge=0)]
    enforcement_action: Literal["permitted", "blocked"]
    enforcement_point: DeviceId | None = None


class FlowReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Parsed from JSON strings after the envelope is decoded, hence non-strict here.
    window_start: Annotated[AwareDatetime, Field(strict=False)]
    window_end: Annotated[AwareDatetime, Field(strict=False)]
    flows: Annotated[list[FlowRecord], Field(max_length=200)]


def build_envelope(
    *,
    device_id: str,
    key_version: int,
    sequence: int,
    timestamp: datetime,
    nonce: str,
    message_type: MessageType,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "v": 1,
        "device_id": device_id,
        "key_version": key_version,
        "sequence": sequence,
        "timestamp": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "nonce": nonce,
        "type": message_type.value,
        "payload": payload,
    }


def encode(envelope: dict[str, Any]) -> bytes:
    """Devices may serialise however they like; the simulator uses compact sorted JSON."""
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
