"""Deterministic detection rules (no machine learning).

Every rule states its classification, severity and the limits of what it can conclude.
Confirmed policy/protocol violations are distinguished from suspected anomalies.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import AlertClassification as C
from app.models.enums import Severity as S


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    classification: C
    severity: S
    category: str
    opens_incident: bool
    marks_suspicious: bool
    confidence_note: str
    description: str


_RULES = [
    Rule(
        "MD-ID-001",
        "Message from unregistered identity",
        C.AUTHENTICATION_FAILURE,
        S.MEDIUM,
        "IDENTITY",
        True,
        False,
        "The sender is unknown to the registry. It may be a rogue device, a misconfigured "
        "device, or a typo in provisioning; the claimed ID proves nothing.",
        "A message claimed a device ID that has no registered identity.",
    ),
    Rule(
        "MD-ID-002",
        "Unregistered endpoint observed on the network",
        C.SUSPECTED_ANOMALY,
        S.MEDIUM,
        "ROGUE_DEVICE",
        True,
        False,
        "Attribution relies on the network sensor and a synthetic IP mapping; the endpoint "
        "could also be a legitimate device that has not been enrolled yet.",
        "The network sensor observed traffic from an address that matches no registered asset.",
    ),
    Rule(
        "MD-ID-003",
        "Message from quarantined or revoked identity refused",
        C.CONFIRMED_POLICY_VIOLATION,
        S.LOW,
        "CONTAINMENT",
        False,
        False,
        "Shows containment is holding. The message may come from the device itself or from "
        "someone replaying or forging its traffic.",
        "A message arrived for an identity whose current state refuses messages.",
    ),
    Rule(
        "MD-AUTH-001",
        "Message authentication failed",
        C.AUTHENTICATION_FAILURE,
        S.LOW,
        "AUTHENTICATION",
        False,
        False,
        "A single failure may be corruption or a key mismatch after rotation. The claimed "
        "identity is not penalised, because anyone can claim any ID.",
        "The HMAC-SHA-256 signature did not verify against the claimed identity's active key.",
    ),
    Rule(
        "MD-AUTH-002",
        "Repeated authentication failures",
        C.AUTHENTICATION_FAILURE,
        S.MEDIUM,
        "AUTHENTICATION",
        True,
        False,
        "Consistent with spoofing or a stale key on the device. The real device's trust "
        "state is deliberately left unchanged to avoid attacker-driven lockout.",
        "Several signature failures for the same claimed identity inside the window.",
    ),
    Rule(
        "MD-RPL-001",
        "Replayed message",
        C.PROTOCOL_VIOLATION,
        S.HIGH,
        "MESSAGE_REPLAY",
        True,
        False,
        "The message is authentic but was already processed. The simulated protocol never "
        "retransmits with the same sequence, so this is a protocol violation; it does not by "
        "itself show the device or its key is compromised (an on-path party can replay).",
        "An authentic message's sequence number and nonce were already used.",
    ),
    Rule(
        "MD-RPL-002",
        "Out-of-sequence message",
        C.PROTOCOL_VIOLATION,
        S.MEDIUM,
        "MESSAGE_REPLAY",
        True,
        False,
        "May be a delayed replay of a captured message, or reordering by a faulty relay.",
        "An authentic message carried a sequence number at or below the last accepted one.",
    ),
    Rule(
        "MD-RPL-003",
        "Stale message",
        C.PROTOCOL_VIOLATION,
        S.MEDIUM,
        "MESSAGE_REPLAY",
        True,
        False,
        "Clock drift on the device can also cause this; the device clock is not trusted.",
        "An authentic message's timestamp falls outside the freshness window.",
    ),
    Rule(
        "MD-RPL-004",
        "Sequence number reused with different content",
        C.PROTOCOL_VIOLATION,
        S.HIGH,
        "IDENTITY_MISUSE",
        True,
        True,
        "Two different authentic messages with the same counter implies a second key holder "
        "or a badly faulty device. Key compromise is possible but not proven.",
        "An authentic message reused an accepted sequence number with a different body.",
    ),
    Rule(
        "MD-RPL-005",
        "Sequence jump exceeds limit",
        C.PROTOCOL_VIOLATION,
        S.MEDIUM,
        "MESSAGE_REPLAY",
        True,
        False,
        "Rejected to prevent counter exhaustion. A device that lost its counter state would "
        "need re-provisioning.",
        "An authentic message advanced the sequence by more than the allowed gap.",
    ),
    Rule(
        "MD-VAL-001",
        "Message failed schema validation",
        C.VALIDATION_FAILURE,
        S.MEDIUM,
        "TELEMETRY_INTEGRITY",
        True,
        True,
        "If authentic, the device itself sent malformed data (fault or manipulation). If not "
        "authentic, nothing is concluded about the claimed device.",
        "The message or its payload did not match the expected types.",
    ),
    Rule(
        "MD-VAL-002",
        "Value outside configured limits",
        C.VALIDATION_FAILURE,
        S.HIGH,
        "TELEMETRY_INTEGRITY",
        True,
        True,
        "Physically implausible for this device type. Sensor fault and manipulation are both "
        "possible explanations; the value never reached trusted state.",
        "An authentic report contained a value outside its measurement or physical limits.",
    ),
    Rule(
        "MD-VAL-003",
        "Inconsistent telemetry",
        C.VALIDATION_FAILURE,
        S.MEDIUM,
        "TELEMETRY_INTEGRITY",
        True,
        True,
        "Violates a consistency rule (e.g. a cumulative counter decreased). Could be a device "
        "reset or manipulation.",
        "An authentic report contradicted a consistency rule against trusted state.",
    ),
    Rule(
        "MD-MDL-001",
        "Reported state disagrees with the deterministic model",
        C.SUSPECTED_ANOMALY,
        S.MEDIUM,
        "TELEMETRY_INTEGRITY",
        True,
        False,
        "Suspected only. A faulty sensor, delayed HVAC state, unmodelled heat sources or "
        "model error can all explain this. The reading is held for review, not discarded.",
        "An authentic, in-range reading differs from the model prediction beyond tolerance.",
    ),
    Rule(
        "MD-CMD-001",
        "Command outside permitted action set",
        C.CONFIRMED_POLICY_VIOLATION,
        S.HIGH,
        "UNAUTHORIZED_COMMAND",
        True,
        True,
        "The identity authenticated correctly and asked for something policy forbids. Misuse, "
        "compromise and misconfiguration are all possible causes.",
        "An authenticated identity issued a command that the policy engine denied.",
    ),
    Rule(
        "MD-CMD-002",
        "Message type not permitted for identity",
        C.CONFIRMED_POLICY_VIOLATION,
        S.HIGH,
        "UNAUTHORIZED_COMMAND",
        True,
        True,
        "The identity is not provisioned for this message type (least privilege).",
        "An authenticated identity sent a message type outside its provisioned set.",
    ),
    Rule(
        "MD-CMD-003",
        "Command refused by trust gate",
        C.CONFIRMED_POLICY_VIOLATION,
        S.MEDIUM,
        "UNAUTHORIZED_COMMAND",
        False,
        False,
        "Commands are refused while an identity is under suspicion; this confirms the gate, "
        "not new malicious intent.",
        "A command arrived from an identity that is not AUTHENTICATED.",
    ),
    Rule(
        "MD-NET-001",
        "Flow to unauthorized destination",
        C.CONFIRMED_POLICY_VIOLATION,
        S.HIGH,
        "LATERAL_MOVEMENT",
        True,
        True,
        "Observed by the network sensor and attributed by source address, which a real "
        "attacker could spoof. Misconfiguration is also possible.",
        "An observed flow was evaluated against policy and denied.",
    ),
    Rule(
        "MD-NET-002",
        "New communication path",
        C.SUSPECTED_ANOMALY,
        S.LOW,
        "LATERAL_MOVEMENT",
        False,
        False,
        "New is not necessarily malicious: maintenance or new workflows create new paths.",
        "An observed flow matches no modeled baseline relationship.",
    ),
    Rule(
        "MD-NET-003",
        "Policy violation allowed in monitor-only mode",
        C.CONFIRMED_POLICY_VIOLATION,
        S.HIGH,
        "LATERAL_MOVEMENT",
        True,
        True,
        "The matching deny rule is in MONITOR mode, so the traffic was not blocked.",
        "An observed flow violated a deny policy that is not enforced.",
    ),
    Rule(
        "MD-RATE-001",
        "Excessive message frequency",
        C.SUSPECTED_ANOMALY,
        S.MEDIUM,
        "RATE_ANOMALY",
        True,
        False,
        "Bursts can come from firmware faults or reconnect storms as well as abuse.",
        "An authenticated identity exceeded the configured message rate.",
    ),
]

RULES: dict[str, Rule] = {rule.id: rule for rule in _RULES}


def rule(rule_id: str) -> Rule:
    return RULES[rule_id]
