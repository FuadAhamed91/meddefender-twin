"""Device-side behaviour: builds and signs messages exactly like a device would.

Device-side counters and key versions live in ``sim_devices`` (the device's own memory),
independently of the platform's replay state.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core import crypto
from app.models import SimDevice
from app.models.enums import MessageType
from app.services.context import AppServices
from app.services.messages import build_envelope, encode


@dataclass(frozen=True)
class SignedMessage:
    raw: bytes
    signature_header: str
    device_id: str
    sequence: int
    key_version: int
    envelope: dict[str, Any]


class DeviceFactory:
    def __init__(self, services: AppServices) -> None:
        self.services = services

    def _claim_sequence(self, device_id: str) -> tuple[int, int]:
        with self.services.session_factory() as session, session.begin():
            sim = session.get(SimDevice, device_id, with_for_update=True)
            if sim is None:
                raise KeyError(f"{device_id} is not a simulated device")
            sequence = sim.next_sequence
            sim.next_sequence = sequence + 1
            return sequence, sim.key_version

    def message(
        self,
        device_id: str,
        message_type: MessageType,
        payload: dict[str, Any],
        *,
        timestamp: datetime | None = None,
    ) -> SignedMessage:
        """An honest message: next device sequence, current key, current time."""
        sequence, key_version = self._claim_sequence(device_id)
        key = crypto.derive_device_key(
            self.services.settings.master_secret_bytes, device_id, key_version
        )
        return self._sign(device_id, key, key_version, sequence, message_type, payload, timestamp)

    def forged(
        self,
        device_id: str,
        message_type: MessageType,
        payload: dict[str, Any],
        *,
        sequence: int,
        key_version: int = 1,
        timestamp: datetime | None = None,
    ) -> SignedMessage:
        """A message from a party that does NOT hold the device key (random key)."""
        key = secrets.token_bytes(32)
        return self._sign(device_id, key, key_version, sequence, message_type, payload, timestamp)

    def _sign(
        self,
        device_id: str,
        key: bytes,
        key_version: int,
        sequence: int,
        message_type: MessageType,
        payload: dict[str, Any],
        timestamp: datetime | None,
    ) -> SignedMessage:
        envelope = build_envelope(
            device_id=device_id,
            key_version=key_version,
            sequence=sequence,
            timestamp=timestamp or self.services.clock.now(),
            nonce=secrets.token_hex(16),
            message_type=message_type,
            payload=payload,
        )
        raw = encode(envelope)
        signature = crypto.format_signature_header(crypto.sign(key, raw))
        return SignedMessage(raw, signature, device_id, sequence, key_version, envelope)
