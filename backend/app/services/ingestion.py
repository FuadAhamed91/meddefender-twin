"""Device message ingestion pipeline: the single enforcement path for every device message.

Check order (each recorded as PASS / FAIL / WARN / SKIPPED / NOT_APPLICABLE):

1. identity   - claimed ID is a registered identity with an active credential and a
                trust state that accepts messages
2. schema     - envelope and payload types (strict; unknown fields rejected)
3. integrity  - HMAC-SHA-256 over the raw body, constant-time comparison
4. sequence   - strictly increasing, bounded gap       } evaluated under a row lock on
5. freshness  - timestamp inside the window            } device_replay_state; state only
6. nonce      - never seen before for this device      } advances for authentic messages
7. content    - measurement/physical limits and consistency rules
8. policy     - message-type permission, command policy, flow policy
9. model      - reported vs predicted state (discrepancy -> HELD, never trusted)

Live HTTP traffic, the background generator and every attack scenario call ``process``;
nothing else may write telemetry outcomes, alerts or trusted state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import crypto
from app.models import (
    Asset,
    DeviceCredential,
    DeviceIdentity,
    DeviceNonce,
    DeviceReplayState,
    PolicyDecision,
    TelemetryEvent,
    TwinState,
)
from app.models.enums import (
    ActorType,
    AuditDecision,
    CheckStatus,
    CredentialStatus,
    DecisionOutcome,
    IngestChannel,
    MessageType,
    PolicyEffect,
    PolicyType,
    RegistrationStatus,
    TelemetryDecision,
    TrustState,
)
from app.services import incidents, trust, twin_model
from app.services.context import AppServices, UnitOfWork
from app.services.detection import rule as get_rule
from app.services.messages import CommandPayload, Envelope, FlowReportPayload
from app.services.policy_engine import PolicyEngine, PolicyEvaluation, endpoint_for_asset
from app.services.profiles import (
    COMMANDS,
    HEARTBEAT_PROFILE,
    PROFILES,
    TelemetryProfile,
    check_field,
)

_DEVICE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,47}$")
RAW_STORE_LIMIT = 16_384

AUTH_FAILURE_CODES = (
    "BAD_SIGNATURE",
    "MISSING_SIGNATURE",
    "KEY_VERSION_RETIRED",
    "UNKNOWN_KEY_VERSION",
)

# Which detection rule a rejection reason maps to (one primary alert per message).
REJECTION_RULES: dict[str, str] = {
    "UNKNOWN_DEVICE": "MD-ID-001",
    "NOT_REGISTERED": "MD-ID-001",
    "IDENTITY_QUARANTINED": "MD-ID-003",
    "IDENTITY_REVOKED": "MD-ID-003",
    "REPLAY_DUPLICATE": "MD-RPL-001",
    "DUPLICATE_NONCE": "MD-RPL-001",
    "SEQUENCE_REUSED": "MD-RPL-004",
    "OUT_OF_SEQUENCE": "MD-RPL-002",
    "STALE": "MD-RPL-003",
    "FUTURE_TIMESTAMP": "MD-RPL-003",
    "SEQUENCE_GAP": "MD-RPL-005",
    "SCHEMA_INVALID": "MD-VAL-001",
    "OUT_OF_RANGE": "MD-VAL-002",
    "INCONSISTENT": "MD-VAL-003",
    "MESSAGE_TYPE_NOT_PERMITTED": "MD-CMD-002",
    "POLICY_DENIED": "MD-CMD-001",
    "TRUST_GATE": "MD-CMD-003",
    "MODEL_DISCREPANCY": "MD-MDL-001",
}

CHECK_ORDER = (
    "identity",
    "schema",
    "integrity",
    "sequence",
    "freshness",
    "nonce",
    "content",
    "policy",
    "model",
)

REPLAY_PRIORITY = (
    "REPLAY_DUPLICATE",
    "SEQUENCE_REUSED",
    "OUT_OF_SEQUENCE",
    "STALE",
    "FUTURE_TIMESTAMP",
    "DUPLICATE_NONCE",
    "SEQUENCE_GAP",
)


class CommandSink(Protocol):
    """Delivers a permitted command to the simulated device (the 'physical world')."""

    def deliver(
        self, session: Session, target_asset_id: str, action: str, parameters: dict[str, Any]
    ) -> dict[str, Any]: ...


class FlowAnalyzer(Protocol):
    def analyze(self, ctx: Ingest, report: FlowReportPayload) -> dict[str, Any]: ...


@dataclass
class InboundMessage:
    raw: bytes
    signature_header: str | None
    channel: IngestChannel
    transport_source: str | None = None
    simulation_run_id: int | None = None
    correlation_id: str | None = None


@dataclass
class Check:
    name: str
    status: CheckStatus
    detail: str
    code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "check": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }
        if self.code:
            out["code"] = self.code
        return out


@dataclass
class IngestionResult:
    telemetry_event_id: int
    decision: TelemetryDecision
    reason_code: str
    reason: str
    authenticated: bool
    checks: list[dict[str, Any]]
    claimed_device_id: str | None
    asset_id: str | None
    alert_ids: list[int]
    incident_refs: list[str]
    trust_changes: list[dict[str, str]]
    policy_decision_ids: list[int]
    correlation_id: str
    extra: dict[str, Any] = field(default_factory=dict)


class Ingest:
    """Mutable per-message context."""

    def __init__(self, uow: UnitOfWork, msg: InboundMessage, services: AppServices) -> None:
        self.uow = uow
        self.msg = msg
        self.services = services
        self.settings = services.settings
        self.session: Session = uow.session
        self.now = uow.now
        self.checks: list[Check] = []
        self.claimed_id: str | None = None
        self.lenient: dict[str, Any] | None = None
        self.asset: Asset | None = None
        self.identity: DeviceIdentity | None = None
        self.credential: DeviceCredential | None = None
        self.envelope: Envelope | None = None
        self.payload_errors: list[str] = []
        self.authenticated = False
        self.fresh = False
        self.decision = TelemetryDecision.REJECTED
        self.reason_code = "UNPROCESSED"
        self.reason = ""
        self.event: TelemetryEvent | None = None
        self.alert_ids: list[int] = []
        self.incident_refs: list[str] = []
        self.trust_changes: list[trust.TrustChange] = []
        self.policy_decision_ids: list[int] = []
        self.extra: dict[str, Any] = {}
        self.source_asset: Asset | None = None

    # -- helpers --------------------------------------------------------------------------

    def check(self, name: str, status: CheckStatus, detail: str, code: str | None = None) -> None:
        self.checks.append(Check(name, status, detail, code))

    def skip_remaining(self, why: str) -> None:
        """Mark every check that has not run yet as SKIPPED."""
        done = {c.name for c in self.checks}
        for name in CHECK_ORDER:
            if name not in done:
                self.check(name, CheckStatus.SKIPPED, why)

    def ordered_checks(self) -> list[Check]:
        rank = {name: i for i, name in enumerate(CHECK_ORDER)}
        return sorted(self.checks, key=lambda c: rank.get(c.name, len(rank)))

    def reject(self, code: str, reason: str) -> None:
        self.decision = TelemetryDecision.REJECTED
        self.reason_code = code
        self.reason = reason

    @property
    def subject_ref(self) -> str:
        """Who an alert is about: a mapped (e.g. rogue) transport source, else the claim."""
        if self.source_asset is not None and self.source_asset.discovered:
            return self.source_asset.id
        return self.claimed_id or (self.msg.transport_source or "unknown-sender")


class IngestionPipeline:
    def __init__(
        self,
        services: AppServices,
        command_sink: CommandSink | None = None,
        flow_analyzer: FlowAnalyzer | None = None,
    ) -> None:
        self.services = services
        self.command_sink = command_sink
        self.flow_analyzer = flow_analyzer

    def process(self, msg: InboundMessage) -> IngestionResult:
        with self.services.uow(msg.correlation_id) as uow:
            ctx = Ingest(uow, msg, self.services)
            self._run(ctx)
            self._finalize(ctx)
            result = IngestionResult(
                telemetry_event_id=ctx.event.id if ctx.event else 0,
                decision=ctx.decision,
                reason_code=ctx.reason_code,
                reason=ctx.reason,
                authenticated=ctx.authenticated,
                checks=[c.as_dict() for c in ctx.ordered_checks()],
                claimed_device_id=ctx.claimed_id,
                asset_id=ctx.identity.asset_id if ctx.identity else None,
                alert_ids=ctx.alert_ids,
                incident_refs=ctx.incident_refs,
                trust_changes=[
                    {
                        "asset_id": t.asset_id,
                        "from": t.from_state.value,
                        "to": t.to_state.value,
                        "reason": t.reason,
                    }
                    for t in ctx.trust_changes
                ],
                policy_decision_ids=ctx.policy_decision_ids,
                correlation_id=uow.correlation_id,
                extra=ctx.extra,
            )
        return result

    # =====================================================================================
    # Stages
    # =====================================================================================

    def _run(self, ctx: Ingest) -> None:
        raw = ctx.msg.raw
        if ctx.msg.transport_source:
            ctx.source_asset = ctx.session.scalars(
                select(Asset).where(Asset.ip_address == ctx.msg.transport_source)
            ).first()

        if len(raw) > ctx.settings.max_message_bytes:
            ctx.check("identity", CheckStatus.SKIPPED, "Message not parsed (too large).")
            ctx.check(
                "schema",
                CheckStatus.FAIL,
                f"Body is {len(raw)} bytes; limit is {ctx.settings.max_message_bytes}.",
                "PAYLOAD_TOO_LARGE",
            )
            ctx.reject("PAYLOAD_TOO_LARGE", "Message exceeds the size limit.")
            ctx.skip_remaining("Not evaluated: message rejected before authentication.")
            return
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        if not isinstance(parsed, dict):
            ctx.check("identity", CheckStatus.SKIPPED, "Message is not a JSON object.")
            ctx.check("schema", CheckStatus.FAIL, "Body is not a JSON object.", "MALFORMED")
            ctx.reject("MALFORMED", "Message is not valid JSON.")
            ctx.skip_remaining("Not evaluated: message rejected before authentication.")
            return
        ctx.lenient = parsed
        claimed = parsed.get("device_id")
        ctx.claimed_id = (
            claimed if isinstance(claimed, str) and _DEVICE_ID_RE.match(claimed) else None
        )

        if not self._check_identity(ctx):
            return
        if not self._check_schema(ctx):
            return
        if not self._check_integrity(ctx):
            return
        if not self._check_replay(ctx):
            return

        # ---- From here the message is authentic and fresh: a current claim by the device.
        assert ctx.identity is not None and ctx.envelope is not None
        ctx.identity.last_seen_at = ctx.now
        self._check_rate(ctx)

        if ctx.payload_errors:
            ctx.check("content", CheckStatus.SKIPPED, "Payload failed schema validation.")
            ctx.reject(
                "SCHEMA_INVALID",
                "Payload failed schema validation: " + "; ".join(ctx.payload_errors[:3]),
            )
            self._update_reported(ctx)
            ctx.skip_remaining("Not evaluated: payload invalid.")
            return

        if not self._check_content(ctx):
            self._update_reported(ctx)
            return

        self._dispatch(ctx)

    # ---- 1. identity --------------------------------------------------------------------

    def _check_identity(self, ctx: Ingest) -> bool:
        session = ctx.session
        if ctx.claimed_id is None:
            ctx.check("identity", CheckStatus.FAIL, "No valid device_id claimed.", "UNKNOWN_DEVICE")
            ctx.reject("UNKNOWN_DEVICE", "No valid device identity was claimed.")
            ctx.skip_remaining("Not evaluated: unknown sender.")
            return False
        ctx.asset = session.get(Asset, ctx.claimed_id)
        ctx.identity = session.get(DeviceIdentity, ctx.claimed_id)
        identity = ctx.identity
        if identity is None:
            detail = (
                f"{ctx.claimed_id} is a modeled asset but not a messaging identity."
                if ctx.asset
                else f"{ctx.claimed_id} is not in the identity registry."
            )
            ctx.check("identity", CheckStatus.FAIL, detail, "UNKNOWN_DEVICE")
            ctx.reject("UNKNOWN_DEVICE", detail)
            ctx.skip_remaining("Not evaluated: unknown identity.")
            return False
        if identity.registration_status is not RegistrationStatus.REGISTERED:
            detail = f"{ctx.claimed_id} is {identity.registration_status.value}; it is not trusted for any operation."
            ctx.check("identity", CheckStatus.FAIL, detail, "NOT_REGISTERED")
            ctx.reject("NOT_REGISTERED", detail)
            ctx.skip_remaining("Not evaluated: identity not registered.")
            return False
        ctx.credential = session.scalars(
            select(DeviceCredential).where(
                DeviceCredential.asset_id == identity.asset_id,
                DeviceCredential.status == CredentialStatus.ACTIVE,
            )
        ).first()
        if identity.trust_state in trust.REFUSED_STATES:
            code = (
                "IDENTITY_QUARANTINED"
                if identity.trust_state is TrustState.QUARANTINED
                else "IDENTITY_REVOKED"
            )
            detail = (
                f"{identity.asset_id} is {identity.trust_state.value}; its messages are refused."
            )
            ctx.check("identity", CheckStatus.FAIL, detail, code)
            ctx.reject(code, detail)
            self._attribution_only_integrity(ctx)
            ctx.skip_remaining("Not evaluated: identity refuses messages.")
            return False
        if ctx.credential is None:
            ctx.check(
                "identity",
                CheckStatus.FAIL,
                f"{identity.asset_id} has no active credential.",
                "NO_ACTIVE_CREDENTIAL",
            )
            ctx.reject("NO_ACTIVE_CREDENTIAL", "No active credential.")
            ctx.skip_remaining("Not evaluated: no active credential.")
            return False
        ctx.check(
            "identity",
            CheckStatus.PASS,
            f"Registered identity ({identity.trust_state.value}); active key v{ctx.credential.key_version} "
            f"fingerprint {ctx.credential.fingerprint}.",
        )
        return True

    # ---- 2. schema ----------------------------------------------------------------------

    def _check_schema(self, ctx: Ingest) -> bool:
        try:
            envelope = Envelope.model_validate_json(ctx.msg.raw)
        except ValidationError as exc:
            errors = _summarise_errors(exc)
            ctx.check(
                "schema",
                CheckStatus.FAIL,
                "Envelope invalid: " + "; ".join(errors),
                "SCHEMA_INVALID",
            )
            ctx.reject(
                "SCHEMA_INVALID", "Envelope failed schema validation: " + "; ".join(errors[:3])
            )
            self._attribution_only_integrity(ctx)
            ctx.skip_remaining("Not evaluated: envelope invalid.")
            return False
        if envelope.device_id != ctx.claimed_id:
            ctx.check("schema", CheckStatus.FAIL, "device_id is ambiguous.", "SCHEMA_INVALID")
            ctx.reject("SCHEMA_INVALID", "device_id is ambiguous.")
            ctx.skip_remaining("Not evaluated: envelope invalid.")
            return False
        ctx.envelope = envelope
        ctx.payload_errors = self._payload_type_errors(ctx, envelope)
        if ctx.payload_errors:
            ctx.check(
                "schema",
                CheckStatus.FAIL,
                "Payload invalid: " + "; ".join(ctx.payload_errors[:5]),
                "SCHEMA_INVALID",
            )
        else:
            ctx.check(
                "schema",
                CheckStatus.PASS,
                f"Envelope v1 and {envelope.type.value} payload types are valid.",
            )
        return True

    def _profile(self, ctx: Ingest) -> TelemetryProfile | None:
        if ctx.identity is None or ctx.identity.telemetry_profile is None:
            return None
        return PROFILES.get(ctx.identity.telemetry_profile)

    def _payload_type_errors(self, ctx: Ingest, envelope: Envelope) -> list[str]:
        payload = envelope.payload
        if envelope.type in (MessageType.TELEMETRY, MessageType.HEARTBEAT):
            profile = (
                HEARTBEAT_PROFILE if envelope.type is MessageType.HEARTBEAT else self._profile(ctx)
            )
            if profile is None or not profile.fields:
                return [f"identity has no {envelope.type.value.lower()} profile"]
            errors = [f"missing field '{f.name}'" for f in profile.fields if f.name not in payload]
            known = {f.name for f in profile.fields}
            errors += [f"unexpected field '{k}'" for k in payload if k not in known]
            for spec in profile.fields:
                if spec.name in payload:
                    type_ok, _ = check_field(spec, payload[spec.name])
                    if not type_ok:
                        errors.append(
                            f"'{spec.name}' must be {spec.kind}, got {type(payload[spec.name]).__name__}"
                        )
            return errors
        if envelope.type is MessageType.COMMAND:
            try:
                command = CommandPayload.model_validate(payload)
            except ValidationError as exc:
                return _summarise_errors(exc)
            spec = COMMANDS.get(command.action)
            if spec is None:
                return [f"unknown action '{command.action}'"]
            errors = [
                f"missing parameter '{p.name}'"
                for p in spec.parameters
                if p.name not in command.parameters
            ]
            known = {p.name for p in spec.parameters}
            errors += [f"unexpected parameter '{k}'" for k in command.parameters if k not in known]
            for p in spec.parameters:
                if (
                    p.name in command.parameters
                    and not check_field(p, command.parameters[p.name])[0]
                ):
                    errors.append(f"parameter '{p.name}' must be {p.kind}")
            return errors
        if envelope.type is MessageType.FLOW_REPORT:
            try:
                FlowReportPayload.model_validate(payload)
            except ValidationError as exc:
                return _summarise_errors(exc)
            return []
        return [f"unsupported message type {envelope.type.value}"]  # pragma: no cover

    # ---- 3. integrity -------------------------------------------------------------------

    def _check_integrity(self, ctx: Ingest) -> bool:
        assert ctx.envelope is not None and ctx.credential is not None and ctx.identity is not None
        presented = crypto.parse_signature_header(ctx.msg.signature_header)
        code: str | None = None
        if presented is None:
            code = "MISSING_SIGNATURE"
            detail = "No well-formed 'hmac-sha256=<hex>' signature header."
        elif ctx.envelope.key_version != ctx.credential.key_version:
            retired = ctx.session.scalars(
                select(DeviceCredential).where(
                    DeviceCredential.asset_id == ctx.identity.asset_id,
                    DeviceCredential.key_version == ctx.envelope.key_version,
                )
            ).first()
            code = "KEY_VERSION_RETIRED" if retired else "UNKNOWN_KEY_VERSION"
            detail = (
                f"Message signed with key v{ctx.envelope.key_version}; active key is v{ctx.credential.key_version}"
                + (f" (v{ctx.envelope.key_version} is {retired.status.value})." if retired else ".")
            )
        else:
            key = crypto.derive_device_key(
                ctx.settings.master_secret_bytes, ctx.identity.asset_id, ctx.credential.key_version
            )
            if crypto.verify(key, ctx.msg.raw, presented):
                ctx.authenticated = True
                ctx.check(
                    "integrity",
                    CheckStatus.PASS,
                    f"HMAC-SHA-256 verified with key v{ctx.credential.key_version} (constant-time compare).",
                )
                return True
            code = "BAD_SIGNATURE"
            detail = "HMAC-SHA-256 did not verify against the active key."
        ctx.check("integrity", CheckStatus.FAIL, detail, code)
        ctx.reject(code, detail)
        ctx.skip_remaining("Not evaluated: message not authenticated.")
        return False

    def _attribution_only_integrity(self, ctx: Ingest) -> None:
        """For messages already rejected, verify the MAC only to decide whether the failure
        is attributable to the device. Never changes replay state."""
        if ctx.identity is None or ctx.credential is None or ctx.lenient is None:
            return
        presented = crypto.parse_signature_header(ctx.msg.signature_header)
        key_version = ctx.lenient.get("key_version")
        if (
            presented is None
            or not isinstance(key_version, int)
            or key_version != ctx.credential.key_version
        ):
            ctx.check(
                "integrity",
                CheckStatus.SKIPPED,
                "Attribution check not possible (no matching key version or signature).",
            )
            return
        key = crypto.derive_device_key(
            ctx.settings.master_secret_bytes, ctx.identity.asset_id, key_version
        )
        if crypto.verify(key, ctx.msg.raw, presented):
            ctx.authenticated = True
            ctx.check(
                "integrity",
                CheckStatus.PASS,
                "Authentic (evaluated for attribution only; message still rejected).",
            )
        else:
            ctx.check(
                "integrity",
                CheckStatus.FAIL,
                "Not authentic (evaluated for attribution only).",
                "BAD_SIGNATURE",
            )

    # ---- 4-6. sequence, freshness, nonce ------------------------------------------------

    def _check_replay(self, ctx: Ingest) -> bool:
        assert ctx.envelope is not None and ctx.identity is not None
        session, env, settings = ctx.session, ctx.envelope, ctx.settings
        asset_id = ctx.identity.asset_id
        state = session.scalars(
            select(DeviceReplayState)
            .where(DeviceReplayState.asset_id == asset_id)
            .with_for_update()
        ).one()
        digest = crypto.message_digest(ctx.msg.raw)
        failures: list[str] = []

        last = state.last_sequence
        if env.sequence <= last:
            original = session.scalars(
                select(TelemetryEvent)
                .where(
                    TelemetryEvent.asset_id == asset_id,
                    TelemetryEvent.sequence == env.sequence,
                    TelemetryEvent.integrity_verified.is_(True),
                    TelemetryEvent.decision != TelemetryDecision.REJECTED,
                )
                .order_by(TelemetryEvent.id)
                .limit(1)
            ).first()
            if original is not None and original.message_digest == digest:
                code = "REPLAY_DUPLICATE"
                detail = (
                    f"Sequence {env.sequence} <= last accepted {last}. Exact duplicate of event "
                    f"#{original.id} received {original.received_at.isoformat()}."
                )
                ctx.extra["original_event_id"] = original.id
            elif original is not None:
                code = "SEQUENCE_REUSED"
                detail = (
                    f"Sequence {env.sequence} was already used by event #{original.id} with "
                    "different content."
                )
                ctx.extra["original_event_id"] = original.id
            else:
                code = "OUT_OF_SEQUENCE"
                detail = f"Sequence {env.sequence} <= last accepted {last}."
            ctx.check("sequence", CheckStatus.FAIL, detail, code)
            failures.append(code)
        elif last > 0 and env.sequence - last > settings.max_sequence_gap:
            detail = (
                f"Sequence jumped by {env.sequence - last} (limit {settings.max_sequence_gap})."
            )
            ctx.check("sequence", CheckStatus.FAIL, detail, "SEQUENCE_GAP")
            failures.append("SEQUENCE_GAP")
        else:
            ctx.check(
                "sequence", CheckStatus.PASS, f"Sequence {env.sequence} > last accepted {last}."
            )

        age = (ctx.now - env.timestamp).total_seconds()
        if age > settings.freshness_window_seconds:
            ctx.check(
                "freshness",
                CheckStatus.FAIL,
                f"Message is {age:.1f}s old (window {settings.freshness_window_seconds}s).",
                "STALE",
            )
            failures.append("STALE")
        elif age < -settings.future_skew_seconds:
            ctx.check(
                "freshness",
                CheckStatus.FAIL,
                f"Timestamp is {-age:.1f}s in the future (skew {settings.future_skew_seconds}s).",
                "FUTURE_TIMESTAMP",
            )
            failures.append("FUTURE_TIMESTAMP")
        else:
            ctx.check(
                "freshness",
                CheckStatus.PASS,
                f"Age {age:.1f}s within {settings.freshness_window_seconds}s window.",
            )

        seen = session.get(DeviceNonce, (asset_id, env.nonce))
        if seen is not None:
            ctx.check(
                "nonce",
                CheckStatus.FAIL,
                f"Nonce first seen {seen.first_seen_at.isoformat()}.",
                "DUPLICATE_NONCE",
            )
            failures.append("DUPLICATE_NONCE")
        else:
            ctx.check("nonce", CheckStatus.PASS, "Nonce not seen before for this device.")

        if failures:
            primary = next(code for code in REPLAY_PRIORITY if code in failures)
            ctx.reject(primary, next(c.detail for c in ctx.checks if c.code == primary))
            ctx.skip_remaining("Not evaluated: message is not new.")
            return False

        state.last_sequence = env.sequence
        state.last_message_at = ctx.now
        state.updated_at = ctx.now
        ctx.extra["_nonce"] = DeviceNonce(asset_id=asset_id, nonce=env.nonce, first_seen_at=ctx.now)
        session.add(ctx.extra["_nonce"])
        ctx.fresh = True
        return True

    def _check_rate(self, ctx: Ingest) -> None:
        assert ctx.identity is not None
        window_start = ctx.now - timedelta(seconds=ctx.settings.rate_limit_window_seconds)
        count = (
            ctx.session.scalar(
                select(func.count(TelemetryEvent.id)).where(
                    TelemetryEvent.asset_id == ctx.identity.asset_id,
                    TelemetryEvent.integrity_verified.is_(True),
                    TelemetryEvent.received_at >= window_start,
                )
            )
            or 0
        )
        if count + 1 > ctx.settings.rate_limit_messages:
            ctx.extra["rate_exceeded"] = count + 1

    # ---- 7. content ---------------------------------------------------------------------

    def _check_content(self, ctx: Ingest) -> bool:
        assert ctx.envelope is not None
        env = ctx.envelope
        errors: list[str] = []
        code = "OUT_OF_RANGE"
        if env.type in (MessageType.TELEMETRY, MessageType.HEARTBEAT):
            profile = HEARTBEAT_PROFILE if env.type is MessageType.HEARTBEAT else self._profile(ctx)
            assert profile is not None
            for spec in profile.fields:
                _, range_error = check_field(spec, env.payload[spec.name])
                if range_error:
                    errors.append(range_error)
            if not errors:
                inconsistency = self._consistency(ctx, env.payload)
                if inconsistency:
                    errors.append(inconsistency)
                    code = "INCONSISTENT"
        elif env.type is MessageType.COMMAND:
            command = CommandPayload.model_validate(env.payload)
            spec = COMMANDS[command.action]
            for p in spec.parameters:
                _, range_error = check_field(p, command.parameters[p.name])
                if range_error:
                    errors.append(range_error)
            for low, high in spec.cross_checks:
                if not errors and command.parameters[low] >= command.parameters[high]:
                    errors.append(f"{low} must be below {high}")
                    code = "INCONSISTENT"
        elif env.type is MessageType.FLOW_REPORT:
            report = FlowReportPayload.model_validate(env.payload)
            if report.window_end < report.window_start:
                errors.append("window_end precedes window_start")
                code = "INCONSISTENT"

        if errors:
            ctx.check("content", CheckStatus.FAIL, "; ".join(errors), code)
            ctx.reject(code, "; ".join(errors))
            ctx.skip_remaining("Not evaluated: content invalid.")
            return False
        ctx.check(
            "content", CheckStatus.PASS, "Values within configured limits; consistency rules hold."
        )
        return True

    def _consistency(self, ctx: Ingest, payload: dict[str, Any]) -> str | None:
        assert ctx.identity is not None
        twin = ctx.session.get(TwinState, ctx.identity.asset_id)
        trusted = (twin.trusted if twin else None) or {}
        for counter in ("volume_infused_ml", "studies_sent_total"):
            if counter in payload and counter in trusted:
                try:
                    if float(payload[counter]) + 0.01 < float(trusted[counter]):
                        return f"{counter} decreased from trusted {trusted[counter]} to {payload[counter]}"
                except (TypeError, ValueError):
                    continue
        return None

    # ---- 8 + 9. policy and model --------------------------------------------------------

    def _dispatch(self, ctx: Ingest) -> None:
        assert ctx.identity is not None and ctx.envelope is not None
        env = ctx.envelope
        allowed = {str(t) for t in (ctx.identity.allowed_message_types or [])}
        if env.type.value not in allowed:
            detail = (
                f"{ctx.identity.asset_id} is provisioned for {sorted(allowed)}; "
                f"{env.type.value} is not permitted (least privilege)."
            )
            ctx.check("policy", CheckStatus.FAIL, detail, "MESSAGE_TYPE_NOT_PERMITTED")
            ctx.reject("MESSAGE_TYPE_NOT_PERMITTED", detail)
            ctx.skip_remaining("Not evaluated: message type refused.")
            return

        if env.type is MessageType.COMMAND:
            self._handle_command(ctx)
            return
        if env.type is MessageType.FLOW_REPORT:
            report = FlowReportPayload.model_validate(env.payload)
            ctx.check(
                "policy",
                CheckStatus.PASS,
                f"{ctx.identity.asset_id} may submit flow reports; flows evaluated individually.",
            )
            if self.flow_analyzer is not None:
                ctx.extra["flow_analysis"] = self.flow_analyzer.analyze(ctx, report)
            ctx.check("model", CheckStatus.NOT_APPLICABLE, "Flow reports have no predicted state.")
            ctx.decision = TelemetryDecision.ACCEPTED
            ctx.reason_code = "OK"
            ctx.reason = "Flow report accepted; flows evaluated against policy."
            return

        ctx.check("policy", CheckStatus.PASS, f"{env.type.value} permitted for this identity.")
        self._model_and_accept(ctx)

    def _handle_command(self, ctx: Ingest) -> None:
        assert ctx.identity is not None and ctx.envelope is not None
        session = ctx.session
        command = CommandPayload.model_validate(ctx.envelope.payload)
        spec = COMMANDS[command.action]
        target = session.get(Asset, command.target)
        source_asset = ctx.asset
        if target is None or not target.is_active:
            detail = f"Command target {command.target} is not a known asset."
            ctx.check("policy", CheckStatus.FAIL, detail, "POLICY_DENIED")
            ctx.reject("POLICY_DENIED", detail)
            ctx.skip_remaining("Not evaluated: unknown target.")
            return
        if target.asset_type not in spec.target_types:
            evaluation = PolicyEvaluation(
                decision=PolicyEffect.DENY,
                outcome=DecisionOutcome.BLOCKED,
                matched_policy_id=None,
                reason=f"Action {command.action} is not supported by {target.asset_type} devices (command catalog).",
                explanation={
                    "matched": {"id": "BUILTIN-COMMAND-CATALOG", "effect": "DENY"},
                    "supported_targets": list(spec.target_types),
                },
            )
        else:
            engine = PolicyEngine.load(session)
            evaluation = engine.evaluate_command(
                endpoint_for_asset(source_asset, ctx.identity.asset_id),
                ctx.identity.trust_state,
                endpoint_for_asset(target),
                command.action,
            )
        decision = record_policy_decision(
            ctx,
            PolicyType.DEVICE_COMMAND,
            ctx.identity.asset_id,
            source_asset,
            command.target,
            target,
            command.action,
            evaluation,
        )
        ctx.extra["command"] = {
            "target": command.target,
            "action": command.action,
            "parameters": command.parameters,
            "policy_decision_id": decision.id,
            "outcome": evaluation.outcome.value,
        }
        if not evaluation.permitted:
            gate = evaluation.matched_policy_id is None and "Trust gate" in evaluation.reason
            code = "TRUST_GATE" if gate else "POLICY_DENIED"
            ctx.check("policy", CheckStatus.FAIL, evaluation.reason, code)
            ctx.reject(code, evaluation.reason)
            ctx.check(
                "model",
                CheckStatus.NOT_APPLICABLE,
                "Command not delivered; target state unchanged.",
            )
            ctx.extra["command"]["delivered"] = False
            ctx.uow.audit(
                actor_type=ActorType.DEVICE,
                actor_id=ctx.identity.asset_id,
                action="COMMAND_DENIED",
                target_type="asset",
                target_id=command.target,
                decision=AuditDecision.DENY,
                reason=evaluation.reason,
                details={
                    "action": command.action,
                    "policy_decision_id": decision.id,
                    "matched_policy": evaluation.matched_policy_id,
                },
                simulation_run_id=ctx.msg.simulation_run_id,
            )
            return
        ctx.check("policy", CheckStatus.PASS, evaluation.reason)
        delivery: dict[str, Any] = {"delivered": False, "note": "no command sink configured"}
        if self.command_sink is not None:
            delivery = self.command_sink.deliver(
                session, command.target, command.action, command.parameters
            )
        ctx.extra["command"]["delivered"] = bool(delivery.get("delivered"))
        ctx.extra["command"]["delivery"] = delivery
        ctx.check("model", CheckStatus.NOT_APPLICABLE, "Commands have no predicted state.")
        ctx.decision = TelemetryDecision.ACCEPTED
        ctx.reason_code = "OK"
        ctx.reason = f"Command {command.action} delivered to {command.target}."
        ctx.uow.audit(
            actor_type=ActorType.DEVICE,
            actor_id=ctx.identity.asset_id,
            action="COMMAND_EXECUTED",
            target_type="asset",
            target_id=command.target,
            decision=AuditDecision.ALLOW,
            reason=evaluation.reason,
            details={
                "action": command.action,
                "parameters": command.parameters,
                "policy_decision_id": decision.id,
            },
            simulation_run_id=ctx.msg.simulation_run_id,
        )
        ctx.uow.emit("command.delivered", {"source": ctx.identity.asset_id, **ctx.extra["command"]})

    def _model_and_accept(self, ctx: Ingest) -> None:
        assert ctx.identity is not None and ctx.envelope is not None
        session = ctx.session
        twin = session.get(TwinState, ctx.identity.asset_id)
        assert twin is not None
        profile = self._profile(ctx) if ctx.envelope.type is MessageType.TELEMETRY else None
        prediction = (
            twin_model.predict(session, ctx.identity.asset_id, profile.model, twin, ctx.now)
            if profile and profile.model
            else None
        )
        payload = ctx.envelope.payload
        if profile is None or profile.model is None:
            ctx.check(
                "model", CheckStatus.NOT_APPLICABLE, "No deterministic model for this asset type."
            )
        elif prediction is None:
            ctx.check(
                "model",
                CheckStatus.SKIPPED,
                "Model not initialised (needs trusted inputs); reading accepted to initialise it.",
            )
        else:
            comparisons = twin_model.compare(prediction, payload, twin.trusted)
            twin.predicted = prediction.values | {"_inputs": prediction.inputs}
            twin.predicted_at = ctx.now
            twin.model_name = prediction.model
            twin.discrepancy = {
                "evaluated_at": ctx.now.isoformat(),
                "model": prediction.model,
                "comparisons": [c.as_dict() for c in comparisons],
                "within_tolerance": all(c.within_tolerance for c in comparisons),
                "note": prediction.note,
            }
            off = [c for c in comparisons if not c.within_tolerance]
            if off:
                detail = "; ".join(
                    f"{c.metric}: reported {c.reported} vs predicted {c.predicted} (delta {c.delta:+}, tolerance ±{c.tolerance})"
                    for c in off
                )
                ctx.check("model", CheckStatus.WARN, detail, "MODEL_DISCREPANCY")
                ctx.decision = TelemetryDecision.HELD
                ctx.reason_code = "MODEL_DISCREPANCY"
                ctx.reason = "Held for review: " + detail
                ctx.extra["model_discrepancy"] = [c.as_dict() for c in off]
                self._update_reported(ctx)
                return
            ctx.check(
                "model",
                CheckStatus.PASS,
                "Within model tolerance: "
                + ", ".join(
                    f"{c.metric} {c.reported} vs {c.predicted} (±{c.tolerance})"
                    for c in comparisons
                ),
            )

        ctx.decision = TelemetryDecision.ACCEPTED
        ctx.reason_code = "OK"
        ctx.reason = "All checks passed."
        self._update_reported(ctx)
        twin.trusted = dict(payload)
        twin.trusted_at = ctx.now
        ctx.extra["_trusted_updated"] = True

    def _update_reported(self, ctx: Ingest) -> None:
        if ctx.envelope is None or ctx.identity is None or not (ctx.authenticated and ctx.fresh):
            return
        if ctx.envelope.type not in (MessageType.TELEMETRY, MessageType.HEARTBEAT):
            return
        twin = ctx.session.get(TwinState, ctx.identity.asset_id)
        if twin is None:
            return
        twin.reported = dict(ctx.envelope.payload)
        twin.reported_at = ctx.now
        ctx.extra["_reported_updated"] = True

    # =====================================================================================
    # Finalisation: persist the observation, alerts, trust, audit and events
    # =====================================================================================

    def _finalize(self, ctx: Ingest) -> None:
        session, uow, msg = ctx.session, ctx.uow, ctx.msg
        ctx.skip_remaining("Not evaluated.")
        env = ctx.envelope
        lenient = ctx.lenient or {}
        raw_text = msg.raw[:RAW_STORE_LIMIT].decode("utf-8", errors="replace")
        event = TelemetryEvent(
            received_at=ctx.now,
            claimed_device_id=ctx.claimed_id,
            asset_id=ctx.identity.asset_id if ctx.identity else None,
            message_type=env.type.value if env else _safe_str(lenient.get("type"), 24),
            sequence=env.sequence if env else _safe_int(lenient.get("sequence")),
            device_timestamp=env.timestamp if env else None,
            nonce=env.nonce if env else _safe_str(lenient.get("nonce"), 64),
            key_version=env.key_version if env else _safe_int(lenient.get("key_version")),
            message_digest=crypto.message_digest(msg.raw),
            raw_message=raw_text,
            presented_signature=crypto.parse_signature_header(msg.signature_header),
            integrity_verified=ctx.authenticated,
            decision=ctx.decision,
            reason_code=ctx.reason_code,
            reason=ctx.reason or ctx.reason_code,
            checks=[c.as_dict() for c in ctx.ordered_checks()],
            payload=env.payload if env else None,
            channel=msg.channel,
            simulation_run_id=msg.simulation_run_id,
            correlation_id=uow.correlation_id,
            epoch=uow.epoch,
        )
        if msg.transport_source:
            event.checks = [
                *event.checks,
                {
                    "check": "transport",
                    "status": "INFO",
                    "detail": f"Transport source {msg.transport_source}",
                },
            ]
        session.add(event)
        session.flush()
        ctx.event = event
        for decision_id in ctx.policy_decision_ids:
            decision = session.get(PolicyDecision, decision_id)
            if decision is not None:
                decision.telemetry_event_id = event.id
        nonce_row = ctx.extra.pop("_nonce", None)
        if nonce_row is not None:
            nonce_row.telemetry_event_id = event.id

        twin_changed = bool(ctx.extra.pop("_reported_updated", False))
        trusted_changed = bool(ctx.extra.pop("_trusted_updated", False))
        if ctx.identity is not None and (
            twin_changed or trusted_changed or ctx.decision is TelemetryDecision.HELD
        ):
            twin = session.get(TwinState, ctx.identity.asset_id)
            if twin is not None:
                if twin_changed:
                    twin.reported_event_id = event.id
                    twin.reported_decision = ctx.decision.value
                if trusted_changed:
                    twin.trusted_event_id = event.id
                twin.version += 1
                twin.updated_at = ctx.now

        # Trust: proof of key possession promotes REGISTERED/OFFLINE -> AUTHENTICATED,
        # unless this very message is the reason for suspicion.
        if ctx.identity is not None and ctx.authenticated and ctx.fresh:
            rule_id = REJECTION_RULES.get(ctx.reason_code)
            marks = rule_id is not None and get_rule(rule_id).marks_suspicious
            if not marks and ctx.decision is not TelemetryDecision.REJECTED:
                change = trust.mark_authenticated(ctx.identity, ctx.now)
                if change:
                    ctx.trust_changes.append(change)

        self._raise_alerts(ctx, event)
        self._emit_and_audit(ctx, event)

    def _raise_alerts(self, ctx: Ingest, event: TelemetryEvent) -> None:
        uow = ctx.uow
        evidence_base = {
            "telemetry_event_id": event.id,
            "claimed_device_id": ctx.claimed_id,
            "reason_code": ctx.reason_code,
            "reason": ctx.reason,
            "message_type": event.message_type,
            "sequence": event.sequence,
            "authenticated": ctx.authenticated,
            "transport_source": ctx.msg.transport_source,
            "checks": [
                c.as_dict() for c in ctx.checks if c.status in (CheckStatus.FAIL, CheckStatus.WARN)
            ],
        }
        if "original_event_id" in ctx.extra:
            evidence_base["original_event_id"] = ctx.extra["original_event_id"]

        to_raise: list[tuple[str, dict[str, Any], list[tuple[str, str]], int | None]] = []
        rule_id = REJECTION_RULES.get(ctx.reason_code)
        if ctx.reason_code in AUTH_FAILURE_CODES:
            to_raise.append(("MD-AUTH-001", {}, [], None))
            window_start = ctx.now - timedelta(seconds=ctx.settings.auth_failure_window_seconds)
            failures = (
                ctx.session.scalar(
                    select(func.count(TelemetryEvent.id)).where(
                        TelemetryEvent.claimed_device_id == ctx.claimed_id,
                        TelemetryEvent.reason_code.in_(AUTH_FAILURE_CODES),
                        TelemetryEvent.received_at >= window_start,
                    )
                )
                or 0
            )
            if failures >= ctx.settings.auth_failure_threshold:
                to_raise.append(
                    (
                        "MD-AUTH-002",
                        {
                            "failures_in_window": failures,
                            "window_s": ctx.settings.auth_failure_window_seconds,
                        },
                        [],
                        None,
                    )
                )
        elif rule_id is not None:
            # Validation failures only count against the device when the message was authentic.
            if rule_id.startswith("MD-VAL") and not ctx.authenticated:
                rule_id = None
            if rule_id is not None:
                related: list[tuple[str, str]] = []
                command = ctx.extra.get("command")
                if command:
                    related.append((command["target"], "TARGET"))
                extra = (
                    {"model_discrepancy": ctx.extra["model_discrepancy"]}
                    if "model_discrepancy" in ctx.extra
                    else {}
                )
                decision_id = command.get("policy_decision_id") if command else None
                to_raise.append((rule_id, extra, related, decision_id))
        if "rate_exceeded" in ctx.extra:
            to_raise.append(
                (
                    "MD-RATE-001",
                    {
                        "messages_in_window": ctx.extra["rate_exceeded"],
                        "window_s": ctx.settings.rate_limit_window_seconds,
                    },
                    [],
                    None,
                )
            )

        impersonated: list[tuple[str, str]] = []
        spoofed_claim = (
            ctx.source_asset is not None
            and ctx.source_asset.discovered
            and ctx.claimed_id
            and ctx.claimed_id != ctx.source_asset.id
        )
        if spoofed_claim and ctx.session.get(Asset, ctx.claimed_id) is not None:
            impersonated.append((ctx.claimed_id, "IMPERSONATED"))

        for rid, extra, related, decision_id in to_raise:
            subject = ctx.subject_ref
            asset_id = subject if ctx.session.get(Asset, subject) is not None else None
            outcome = incidents.raise_alert(
                uow,
                rid,
                subject_ref=subject,
                asset_id=asset_id,
                evidence=evidence_base | extra,
                telemetry_event_id=event.id,
                policy_decision_id=decision_id,
                related_assets=related + impersonated,
                simulation_run_id=ctx.msg.simulation_run_id,
            )
            if outcome.alert is not None:
                ctx.alert_ids.append(outcome.alert.id)
            if outcome.incident is not None and outcome.incident.reference not in ctx.incident_refs:
                ctx.incident_refs.append(outcome.incident.reference or str(outcome.incident.id))
            rule = get_rule(rid)
            if (
                rule.marks_suspicious
                and ctx.authenticated
                and ctx.identity is not None
                and subject == ctx.identity.asset_id
            ):
                change = trust.mark_suspicious(ctx.identity, f"{rule.id}: {rule.title}", ctx.now)
                if change:
                    ctx.trust_changes.append(change)

    def _emit_and_audit(self, ctx: Ingest, event: TelemetryEvent) -> None:
        uow = ctx.uow
        actor = ctx.claimed_id or ctx.msg.transport_source or "unknown-sender"
        if ctx.decision is not TelemetryDecision.ACCEPTED:
            uow.audit(
                actor_type=ActorType.DEVICE,
                actor_id=actor,
                action="TELEMETRY_HELD"
                if ctx.decision is TelemetryDecision.HELD
                else "TELEMETRY_REJECTED",
                target_type="telemetry_event",
                target_id=str(event.id),
                decision=AuditDecision.INFO
                if ctx.decision is TelemetryDecision.HELD
                else AuditDecision.DENY,
                reason=f"{ctx.reason_code}: {ctx.reason}",
                details={
                    "checks": [
                        c.as_dict() for c in ctx.checks if c.status is not CheckStatus.SKIPPED
                    ],
                    "authenticated": ctx.authenticated,
                    "channel": ctx.msg.channel.value,
                    "message_digest": event.message_digest,
                    "trusted_state_changed": False,
                },
                simulation_run_id=ctx.msg.simulation_run_id,
            )
        for change in ctx.trust_changes:
            uow.audit(
                actor_type=ActorType.SYSTEM,
                actor_id="ingestion-pipeline",
                action="TRUST_STATE_CHANGED",
                target_type="device_identity",
                target_id=change.asset_id,
                decision=AuditDecision.INFO,
                reason=change.reason,
                details={
                    "from": change.from_state.value,
                    "to": change.to_state.value,
                    "telemetry_event_id": event.id,
                },
                simulation_run_id=ctx.msg.simulation_run_id,
            )
            uow.emit(
                "trust.changed",
                {
                    "asset_id": change.asset_id,
                    "from": change.from_state.value,
                    "to": change.to_state.value,
                    "reason": change.reason,
                },
            )
        uow.emit(
            "telemetry.processed",
            {
                "telemetry_event_id": event.id,
                "asset_id": event.asset_id,
                "claimed_device_id": ctx.claimed_id,
                "message_type": event.message_type,
                "decision": ctx.decision.value,
                "reason_code": ctx.reason_code,
                "authenticated": ctx.authenticated,
                "channel": ctx.msg.channel.value,
                "received_at": event.received_at.isoformat(),
            },
        )
        if ctx.identity is not None:
            twin = ctx.session.get(TwinState, ctx.identity.asset_id)
            if twin is not None and twin.updated_at == ctx.now:
                uow.emit("twin.updated", twin_payload(twin, ctx.identity))


def record_policy_decision(
    ctx: Ingest,
    policy_type: PolicyType,
    source_ref: str,
    source_asset: Asset | None,
    destination_ref: str,
    destination_asset: Asset | None,
    service_or_action: str,
    evaluation: Any,
) -> PolicyDecision:
    decision = PolicyDecision(
        evaluated_at=ctx.now,
        policy_type=policy_type,
        source_ref=source_ref,
        source_asset_id=source_asset.id if source_asset else None,
        destination_ref=destination_ref,
        destination_asset_id=destination_asset.id if destination_asset else None,
        service_or_action=service_or_action,
        decision=evaluation.decision,
        outcome=evaluation.outcome,
        matched_policy_id=evaluation.matched_policy_id,
        reason=evaluation.reason,
        explanation=evaluation.explanation,
        simulation_run_id=ctx.msg.simulation_run_id,
        correlation_id=ctx.uow.correlation_id,
        epoch=ctx.uow.epoch,
    )
    ctx.session.add(decision)
    ctx.session.flush()
    ctx.policy_decision_ids.append(decision.id)
    ctx.uow.emit(
        "policy.decision",
        {
            "policy_decision_id": decision.id,
            "policy_type": policy_type.value,
            "source": source_ref,
            "destination": destination_ref,
            "service_or_action": service_or_action,
            "decision": evaluation.decision.value,
            "outcome": evaluation.outcome.value,
            "matched_policy_id": evaluation.matched_policy_id,
            "reason": evaluation.reason,
        },
    )
    return decision


def twin_payload(twin: TwinState, identity: DeviceIdentity | None) -> dict[str, Any]:
    return {
        "asset_id": twin.asset_id,
        "version": twin.version,
        "reported": twin.reported,
        "reported_at": twin.reported_at.isoformat() if twin.reported_at else None,
        "reported_decision": twin.reported_decision,
        "trusted": twin.trusted,
        "trusted_at": twin.trusted_at.isoformat() if twin.trusted_at else None,
        "predicted": twin.predicted,
        "predicted_at": twin.predicted_at.isoformat() if twin.predicted_at else None,
        "discrepancy": twin.discrepancy,
        "trust_state": identity.trust_state.value if identity else None,
    }


def _summarise_errors(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ())) or "body"
        out.append(f"{loc}: {err.get('msg', 'invalid')}")
    return out


def _safe_str(value: Any, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and -(2**63) < value < 2**63:
        return value
    return None
