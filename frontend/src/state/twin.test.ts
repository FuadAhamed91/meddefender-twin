import { beforeEach, describe, expect, it } from "vitest";
import type { AssetSummary, LiveEvent, TwinSnapshot } from "../api/types";
import { EDGE_TTL_MS, useTwinStore } from "./twin";

const initial = useTwinStore.getState();

function asset(id: string, overrides: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id,
    display_name: id,
    asset_kind: "MEDICAL_DEVICE",
    asset_type: "patient_monitor",
    is_logical: false,
    network_zone_id: "ZONE-ICU",
    room_id: "ICU-BAY-1",
    twin_node: `AST_${id}`,
    position: { x: 5, y: 30, rotation: 0 },
    label_height: 2,
    ip_address: "10.20.110.11",
    criticality: "HIGH",
    discovered: false,
    is_active: true,
    containment_state: "NONE",
    trust_state: "AUTHENTICATED",
    registration_status: "REGISTERED",
    open_incident_count: 0,
    last_seen_at: null,
    twin_version: 1,
    reported_decision: "ACCEPTED",
    ...overrides,
  };
}

function snapshot(): TwinSnapshot {
  return {
    last_event_id: 40,
    epoch: 2,
    generated_at: "2026-10-16T12:00:00Z",
    assets: [asset("ICU-MONITOR-01"), asset("ICU-GATEWAY-01", { asset_type: "gateway" })],
    twin_states: [],
  };
}

const apply = (event: LiveEvent) => useTwinStore.getState().applyEvent(event);

beforeEach(() => {
  useTwinStore.setState(initial, true);
  localStorage.clear();
});

describe("twin store", () => {
  it("loads a snapshot keyed by backend asset id", () => {
    useTwinStore.getState().loadSnapshot(snapshot());
    const s = useTwinStore.getState();
    expect(s.ready).toBe(true);
    expect(s.epoch).toBe(2);
    expect(s.lastEventId).toBe(40);
    expect(Object.keys(s.assets)).toEqual(["ICU-MONITOR-01", "ICU-GATEWAY-01"]);
  });

  it("only moves the event cursor forward", () => {
    useTwinStore.getState().loadSnapshot(snapshot());
    apply({ id: 45, type: "heartbeat" });
    apply({ id: 43, type: "heartbeat" });
    expect(useTwinStore.getState().lastEventId).toBe(45);
  });

  it("projects backend trust changes onto the asset", () => {
    useTwinStore.getState().loadSnapshot(snapshot());
    apply({ id: 41, type: "trust.changed", payload: { asset_id: "ICU-GATEWAY-01", from: "AUTHENTICATED", to: "SUSPICIOUS" } });
    expect(useTwinStore.getState().assets["ICU-GATEWAY-01"].trust_state).toBe("SUSPICIOUS");
    // Events for unknown assets are ignored rather than inventing state.
    apply({ id: 42, type: "trust.changed", payload: { asset_id: "NOT-AN-ASSET", to: "QUARANTINED" } });
    expect(useTwinStore.getState().assets["NOT-AN-ASSET"]).toBeUndefined();
  });

  it("keeps containment and open-incident counts live without dropping the other", () => {
    useTwinStore.getState().loadSnapshot(snapshot());
    apply({ id: 41, type: "asset.updated", payload: { asset_id: "ICU-GATEWAY-01", open_incident_count: 1 } });
    apply({ id: 42, type: "asset.updated", payload: { asset_id: "ICU-GATEWAY-01", containment_state: "RESTRICTED" } });
    expect(useTwinStore.getState().assets["ICU-GATEWAY-01"]).toMatchObject({ open_incident_count: 1, containment_state: "RESTRICTED" });
    apply({ id: 43, type: "asset.updated", payload: { asset_id: "ICU-GATEWAY-01", open_incident_count: 0 } });
    expect(useTwinStore.getState().assets["ICU-GATEWAY-01"]).toMatchObject({ open_incident_count: 0, containment_state: "RESTRICTED" });
  });

  it("counts telemetry decisions", () => {
    apply({ id: 1, type: "telemetry.processed", payload: { decision: "ACCEPTED" } });
    apply({ id: 2, type: "telemetry.processed", payload: { decision: "HELD" } });
    apply({ id: 3, type: "telemetry.processed", payload: { decision: "REJECTED" } });
    const s = useTwinStore.getState();
    expect(s.counters).toEqual({ accepted: 1, held: 1, rejected: 1 });
  });

  it("draws network policy decisions as short-lived flows, but not device commands", () => {
    apply({
      id: 1,
      type: "policy.decision",
      payload: { policy_type: "NETWORK_FLOW", source: "ICU-GATEWAY-01", destination: "IAM-SERVER-01", service: "LDAPS", outcome: "BLOCKED" },
    });
    apply({
      id: 2,
      type: "policy.decision",
      payload: { policy_type: "DEVICE_COMMAND", source: "IMG-WS-01", destination: "ICU-PUMP-01", service_or_action: "SET_RATE", outcome: "BLOCKED" },
    });
    const edges = useTwinStore.getState().transientEdges;
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({ source: "ICU-GATEWAY-01", destination: "IAM-SERVER-01", outcome: "BLOCKED" });
  });

  it("expires transient flows after their time to live", () => {
    apply({ id: 1, type: "network.flow_observed", payload: { source: "A", destination: "B", service: "HL7", outcome: "PERMITTED" } });
    const at = useTwinStore.getState().transientEdges[0].at;
    useTwinStore.getState().pruneTransient(at + EDGE_TTL_MS - 1);
    expect(useTwinStore.getState().transientEdges).toHaveLength(1);
    useTwinStore.getState().pruneTransient(at + EDGE_TTL_MS + 1);
    expect(useTwinStore.getState().transientEdges).toHaveLength(0);
  });

  it("flashes the asset an alert refers to", () => {
    apply({ id: 1, type: "alert.created", payload: { asset_id: "ICU-PUMP-01", severity: "HIGH" } });
    expect(useTwinStore.getState().flashes["ICU-PUMP-01"]?.severity).toBe("HIGH");
  });

  it("issues a new focus request each time, even for the same target", () => {
    const { requestFocus } = useTwinStore.getState();
    requestFocus("asset", ["ICU-PUMP-01"]);
    const first = useTwinStore.getState().focus.nonce;
    requestFocus("asset", ["ICU-PUMP-01"]);
    expect(useTwinStore.getState().focus).toEqual({ kind: "asset", ids: ["ICU-PUMP-01"], nonce: first + 1 });
  });

  it("remembers the chosen view style in this browser", () => {
    useTwinStore.getState().setViewMode("realistic");
    expect(useTwinStore.getState().viewMode).toBe("realistic");
    expect(localStorage.getItem("md.viewMode")).toBe("realistic");
  });
});
