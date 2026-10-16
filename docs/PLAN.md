# Implementation and Test Plan

## Stages

| Stage | Scope | Exit criteria | Status |
|---|---|---|---|
| 0 | Inspect tooling, architecture, threat model, layout | Docs committed; repository created | Done |
| 1 | Backend foundation: config, models, migrations, seed, simulator, telemetry generator | A simulated device message is persisted as an accepted observation and updates trusted state | Done |
| 2 | Security enforcement: identity, HMAC, replay, freshness, policy, audit, auth/RBAC | Replay vertical slice passes end-to-end with an incident and audit event | Done |
| 3 | Digital twin foundation: Blender scene -> GLB, asset mapping, R3F viewer | Selecting a 3D asset shows live backend data; mapping test passes | Done |
| 4 | Live updates: WebSockets with resync, inspector, dashboard metrics | Twin updates from persisted events; reconnect resynchronises | Done |
| 5 | Attack scenarios A-E through the real pipeline | Each scenario's expectations are evaluated against persisted state | Done |
| 6 | Graph analysis, containment planning (F), quarantine, recovery, incident replay | Plans compare impact; applying changes backend state; recovery keeps evidence | Done |
| 7 | Hardening, full test suite, CI, Docker Compose, documentation | All tests executed and reported; README startup verified | Done (see CI) |

## Acceptance criteria and the tests that cover them

Backend tests live in `backend/tests/`, end-to-end tests in `frontend/e2e/`.

| # | Acceptance criterion | Covered by |
|---|---|---|
| 1 | Valid device message accepted | `test_valid_message_is_accepted_and_becomes_trusted`, `test_valid_message_accepted_over_http` |
| 2 | Invalid HMAC rejected | `test_invalid_hmac_is_rejected_and_changes_nothing`, `test_bad_signature_and_unknown_device_look_identical` |
| 3 | Replayed message rejected | `test_replayed_message_is_rejected_audited_and_opens_incident`, `test_replay_over_http_is_409`, `test_concurrent_duplicates_are_accepted_at_most_once`, `test_replay_protection_survives_restart` |
| 4 | Rejected telemetry cannot overwrite trusted state | `test_invalid_hmac_is_rejected_and_changes_nothing`, scenario E in `test_scenario_meets_all_expectations` |
| 5 | Unauthorized command denied | `test_command_trust_gate_runs_before_policy`, scenario B |
| 6 | Rogue device gains no trust automatically | `test_unknown_identity_is_rejected`, scenario C |
| 7 | Unauthorized network path denied | `test_unlisted_path_is_denied_by_default`, `test_wrong_service_on_a_permitted_pair_is_denied`, `test_zone_boundary_rule_wins_over_lower_priority` |
| 8 | Attack-path analysis respects policies | `test_attack_paths_follow_only_permitted_flows`, `test_hypothetical_isolation_removes_paths_without_writing` |
| 9 | Network relationships and dependencies remain distinct | `test_network_and_dependency_graphs_are_distinct`, `test_relationship_status_reflects_current_policy` |
| 10 | Incident transitions follow rules | `test_incident_transitions_are_enforced`, `test_incident_timeline_is_append_only` |
| 11 | Containment changes backend state | `test_containment_apply_changes_backend_state_and_emits_events`, `test_scenario_f_compares_plans_after_d` |
| 12 | Twin receives resulting state updates | `test_websocket_streams_twin_updates`, `test_websocket_resync_replays_missed_events`, `test_open_incident_counts_reach_the_twin_live`; E2E "the live twin maps every backend asset..." |
| 13 | Audit events preserve decision and reason | `test_audit_events_record_decision_and_reason` |
| 14 | Users cannot exceed their roles | `test_viewer_cannot_run_scenarios_and_denial_is_audited`, `test_viewer_cannot_transition_incidents`, `test_operator_cannot_reset_or_manage_identities_or_policies`; E2E "a viewer can look but cannot run attack scenarios" |
| 15 | Refresh preserves incidents and state | `test_state_survives_application_restart` |
| 16 | Reset does not erase audit history | `test_reset_restores_baseline_without_erasing_history` |
| 17 | Invalid input yields safe, predictable errors | `test_invalid_input_returns_structured_error_without_echoing_values`, `test_oversized_and_malformed_bodies` |
| 18 | Clean install starts by following the README | CI job "Docker Compose stack": `.env` from `.env.example`, `docker compose up --build`, smoke checks and the E2E suite |

Additional security tests: concurrent duplicate submission accepted at most once, replay
protection survives an engine restart, secrets never appear in the database or responses
(`test_no_secret_material_anywhere_in_the_database`), audit rows cannot be updated or
deleted (`test_audit_rows_cannot_be_updated_or_deleted`), hash-chain verification detects
tampering, CSRF (`test_state_changing_requests_require_csrf_token`), WebSocket Origin and
session checks, security headers, account lockout and indistinguishable login failures.

## Suites

| Suite | Count | Where it runs |
|---|---|---|
| Backend (pytest, real PostgreSQL, schema from migrations) | 69 tests | Locally and in CI |
| Frontend unit and component (Vitest) | 56 tests | Locally and in CI |
| End to end (Playwright, Chromium with software WebGL) | 4 tests | Locally against the dev servers; in CI against the Compose stack |
