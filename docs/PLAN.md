# Implementation and Test Plan

## Stages

| Stage | Scope | Exit criteria |
|---|---|---|
| 0 | Inspect tooling, architecture, threat model, layout | Docs committed; repository created |
| 1 | Backend foundation: config, models, migrations, seed, simulator, telemetry generator | A simulated device message is persisted as an accepted observation and updates trusted state |
| 2 | Security enforcement: identity, HMAC, replay, freshness, policy, audit, auth/RBAC | Replay vertical slice passes end-to-end with an incident and audit event |
| 3 | Digital twin foundation: Blender scene -> GLB, asset mapping, R3F viewer | Selecting a 3D asset shows live backend data; mapping test passes |
| 4 | Live updates: WebSockets with resync, inspector, dashboard metrics | Twin updates from persisted events; reconnect resynchronises |
| 5 | Attack scenarios A-E through the real pipeline | Each scenario's expectations are evaluated against persisted state |
| 6 | Graph analysis, containment planning (F), quarantine, recovery, incident replay | Plans compare impact; applying changes backend state; recovery keeps evidence |
| 7 | Hardening, full test suite, CI, Docker Compose, documentation | All tests executed and reported; README startup verified |

## Test plan

| # | Acceptance criterion | Test type |
|---|---|---|
| 1 | Valid device message accepted | Integration (pipeline + API) |
| 2 | Invalid HMAC rejected | Security |
| 3 | Replayed message rejected | Security |
| 4 | Rejected telemetry cannot overwrite trusted state | Security |
| 5 | Unauthorized command denied | Security |
| 6 | Rogue device gains no trust automatically | Security |
| 7 | Unauthorized network path denied | Unit (policy engine) |
| 8 | Attack-path analysis respects policies | Unit (graph engine) |
| 9 | Network relationships and dependencies remain distinct | Unit + API |
| 10 | Incident transitions follow rules | Unit + API |
| 11 | Containment changes backend state | Integration |
| 12 | Twin receives resulting state updates | Integration (WebSocket) + E2E |
| 13 | Audit events preserve decision and reason | Integration |
| 14 | Users cannot exceed their roles | Security (API) |
| 15 | Refresh preserves incidents and state | Integration + E2E |
| 16 | Reset does not erase audit history | Integration |
| 17 | Invalid input yields safe, predictable errors | API |
| 18 | Clean install starts by following the README | CI (Compose smoke test) |

Additional security tests: concurrent duplicate submission accepted at most once, replay
protection survives an engine restart, secrets never appear in responses, audit rows
cannot be updated or deleted (trigger), hash-chain verification detects tampering, CSRF
and WebSocket Origin checks.
