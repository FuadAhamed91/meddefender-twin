# MedDefender Twin — Threat Model

This threat model covers the **simulated** hospital and the MedDefender platform itself.
It documents what the controls do, what they do not do, and which conclusions the
simulation cannot support.

## 1. Protected assets

| Asset | Why it matters |
|---|---|
| Trusted twin state | Drives investigation decisions; must not be steerable by unverified reports |
| Device identities and keys | Message authenticity depends on them |
| Policy set | Defines which communication and commands are permitted |
| Audit trail | Evidence of decisions; must not be silently altered through the app |
| Incident records | Investigation history; must survive recovery and simulation reset |
| User accounts and sessions | Gate every privileged action |
| Simulated clinical/operational services | Containment decisions trade risk against their availability |

## 2. Trust boundaries

| ID | Boundary | Controls |
|---|---|---|
| TB1 | Simulated device -> ingestion endpoint | Body size limit, identity lookup, schema validation, HMAC-SHA-256 over raw body, sequence, freshness, nonce, range/consistency checks, policy, model check |
| TB2 | Browser -> API | argon2id passwords, server-side sessions (HttpOnly, SameSite=Strict cookie, hashed at rest), CSRF double-submit header, server-side RBAC on every sensitive route, login throttling |
| TB3 | Simulator ground truth -> twin | Twin state is built only from messages that crossed TB1; nothing reads `sim_devices` except the simulator |
| TB4 | Application -> database | Append-only audit enforced by ORM guard and DB trigger; hash chain for tamper evidence; transactions for multi-row decisions |
| TB5 | Secret material -> everything else | Per-device keys derived at runtime from a master secret in the backend environment; DB stores key version + fingerprint only; secrets never appear in API responses, logs, events or frontend bundles |
| TB6 | Network sensor -> platform | Flow reports are signed by the sensor's own identity and processed by the same pipeline |

## 3. Attacker model

**In scope (simulated):**

* An on-path attacker who can capture and replay device messages but does not hold device keys.
* A low-privilege device identity that attempts commands outside its permission set.
* An unregistered (rogue) endpoint that appears on a clinical network segment.
* A compromised gateway that originates traffic outside its permitted communication policy.
* A faulty or manipulated sensor that reports values conflicting with schema, limits or the model.
* An authenticated platform user attempting actions above their role.

**Assumptions:**

* Device keys are shared secrets known only to the device and the platform (the
  simulator stands in for the device).
* The platform host, its environment variables and the database server are not compromised.
* The network sensor is trustworthy; its observations are attributed to source assets by
  synthetic IP address, which a real attacker could spoof.

## 4. Controls and their limitations

| Control | Protects against | Does **not** protect against |
|---|---|---|
| HMAC-SHA-256 per device | Tampering, forgery without the key | Payload disclosure (no encryption); a compromised device or stolen key; a malicious-but-authentic device |
| Sequence numbers (monotonic, max gap) | Replays, out-of-order injection, counter exhaustion | A device that legitimately loses its counter (would need re-provisioning) |
| Freshness window (past 30 s / future skew 5 s) | Delayed or stale replays | Attacks inside the window (covered by sequence + nonce) |
| Nonce uniqueness | Duplicate submission, even if counters were reset | Nothing beyond the retention of stored nonces |
| Row lock on replay state | Concurrent duplicate acceptance | Multi-database deployments (out of scope) |
| Range/consistency checks | Physically implausible or malformed values | Plausible-but-false values (covered partially by the model check) |
| Model discrepancy check | Values inconsistent with the deterministic model | Model error, unmodelled heat sources, slow drifts within tolerance |
| Default-deny policy engine | Unlisted flows and commands | Abuse of a *permitted* channel (e.g. malformed payloads over an allowed service) |
| Trust-state gating | Commands from suspicious, quarantined or revoked identities | Data-plane abuse by an identity that has not yet triggered any rule |
| Append-only audit + hash chain | Modification through normal application paths; makes silent edits detectable | A database superuser who disables triggers and rewrites the whole chain (anchoring the head hash externally would be a future extension) |
| RBAC (viewer < operator < security_admin) | Privilege misuse through the API | Compromise of an admin account |
| Uniform ingest rejections (every unauthenticated rejection returns 401 with the same body shape; only malformed or oversized bodies differ) | Enumerating which device IDs exist through the ingest endpoint | Timing side channels (not measured) |
| Indistinguishable login failures + account lockout | Username enumeration and online password guessing | Credential stuffing across many accounts below the per-account threshold |
| Security headers (API: `default-src 'none'`, no-store; console: same-origin CSP, `frame-ancestors 'none'`) | Clickjacking, content sniffing, script injection from other origins, caching of API data | A compromised build pipeline or server |

Application-level append-only storage is **not** equivalent to tamper-proof external
logging (WORM storage, a SIEM, or a transparency log).

## 5. Secret provisioning

* `DEVICE_KEY_MASTER_SECRET` (env var, at least 32 bytes) stands in for a KMS root key.
* Device key = `HMAC-SHA-256(master, "meddefender-device-key|v1|" + device_id + "|" + key_version)`.
* The database stores `key_version`, `algorithm`, `fingerprint` (first 16 hex characters of
  SHA-256 of the key) and status, which is enough to identify a key without revealing it.
* Rotation increments `key_version`; messages signed with retired versions are rejected.
* Tests assert that API responses never contain key material.

## 6. Replay-state persistence across restarts

`device_replay_state` (last accepted sequence) and the stored nonces live in PostgreSQL and
are updated in the same transaction that accepts or rejects the message. A restart does not
reset them. Simulation resets do **not** reset replay state or device-side counters,
otherwise previously captured messages would become replayable.

## 7. Detection rules and confidence

All detections are deterministic rules, not machine learning. Each alert records its rule,
evidence, timestamp, affected asset, severity, classification and a confidence note.

| Classification | Meaning |
|---|---|
| `CONFIRMED_POLICY_VIOLATION` | An action was evaluated against an explicit policy and denied |
| `PROTOCOL_VIOLATION` | A message violated the protocol (replay, sequence, freshness) |
| `VALIDATION_FAILURE` | A message failed schema or physical-limit checks |
| `SUSPECTED_ANOMALY` | Behaviour deviates from a model or baseline; benign explanations exist |

An anomaly is never reported as proof of compromise. For example, a model discrepancy may
come from sensor fault, delayed HVAC state or model inaccuracy, and the alert says so.

**Known false positives:** legitimate retransmissions (the simulated protocol never
retransmits with the same sequence, but real devices might); genuine environmental changes
outside the model; new but legitimate communication paths after maintenance.

**Known false negatives:** abuse of permitted channels; slow manipulation within model
tolerance; attacks by a party holding a valid device key; anything the network sensor
does not observe.

## 8. Scenarios covered

| Scenario | Exercised controls |
|---|---|
| A — Replayed telemetry | HMAC (passes), sequence, nonce, freshness, trusted-state protection, incident correlation |
| B — Unauthorized command | Command policy, trust gating, explainable denial, simulated physical state unchanged |
| C — Rogue device | Identity registry, failed authentication handling, enrollment pending approval, default-deny flows |
| D — Compromised gateway | Flow policy, new-path detection, policy-aware attack paths, reachable vs nearby |
| E — Telemetry manipulation | Schema and limit validation vs model discrepancy, reported/trusted/predicted separation |
| F — Containment planning | Plan comparison, dependency impact, authorized application, recovery |

## 9. Intentionally excluded

Real exploitation, malware, credential theft, scanning of real or external networks,
payload encryption (TLS/DTLS would be used in practice), compromised-key scenarios beyond
documentation, physical attacks, denial of service against the platform, supply-chain
attacks, and anything that interacts with real medical devices.

## 10. Deployment assumptions (Docker Compose demo)

* The stack is a **local demo**: the web port is bound to 127.0.0.1 and the seed creates
  accounts whose passwords sit in `.env`. Exposing it beyond the local machine requires new
  passwords, TLS in front of nginx and `COOKIE_SECURE=true`.
* `DEVICE_KEY_MASTER_SECRET` must be supplied; the backend refuses the placeholder value,
  and `ENVIRONMENT=production` additionally refuses insecure cookies and development
  secrets.
* The console, API and WebSocket share one origin through nginx. The backend container is
  not published to the host, so the forwarded client address it trusts can only come from
  that proxy.
* The database runs with the application's own role as owner, which is exactly the
  "database owner can bypass application-level immutability" limitation in section 4.

## 11. What the simulation does not establish

The simulation does not establish clinical safety, regulatory compliance (e.g. FDA,
IEC 62443, IEC 80001, HIPAA), compatibility with any real hospital architecture, or the
behaviour of any real medical device. Clinical names and value ranges are synthetic and
are used only to make the security scenarios legible.
