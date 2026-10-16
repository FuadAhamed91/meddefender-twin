import { describe, expect, it } from "vitest";
import {
  CHECK_STATUS,
  CLASSIFICATION,
  CONTAINMENT,
  DECISION,
  INCIDENT_FLOW,
  INCIDENT_STATUS,
  NO_IDENTITY,
  OUTCOME,
  PATH_CLASS,
  SEVERITY,
  type StatusStyle,
  TRUST,
  trustStyle,
} from "./status";

const MAPS: Record<string, Record<string, StatusStyle>> = {
  TRUST,
  SEVERITY,
  DECISION,
  OUTCOME,
  CLASSIFICATION,
  CONTAINMENT,
  INCIDENT_STATUS,
  CHECK_STATUS,
  PATH_CLASS,
};

describe("status styles", () => {
  it.each(Object.entries(MAPS))("%s never relies on color alone", (_name, map) => {
    for (const style of Object.values(map)) {
      expect(style.label.trim()).not.toBe("");
      expect(style.icon).toBeTruthy();
      expect(style.description.trim()).not.toBe("");
      expect(style.color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it.each(Object.entries(MAPS))("%s labels are distinct", (_name, map) => {
    const labels = Object.values(map).map((s) => s.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("covers every device trust state", () => {
    expect(Object.keys(TRUST).sort()).toEqual(
      ["AUTHENTICATED", "OFFLINE", "QUARANTINED", "REGISTERED", "REVOKED", "SUSPICIOUS", "UNREGISTERED"].sort(),
    );
  });

  it("falls back to a neutral style for assets without a device identity", () => {
    expect(trustStyle(null)).toBe(NO_IDENTITY);
    expect(trustStyle(undefined)).toBe(NO_IDENTITY);
    expect(trustStyle("SUSPICIOUS")).toBe(TRUST.SUSPICIOUS);
  });

  it("orders the incident lifecycle from detection to resolution", () => {
    expect(INCIDENT_FLOW).toEqual(["DETECTED", "INVESTIGATING", "CONTAINMENT_PROPOSED", "CONTAINED", "RECOVERY", "RESOLVED"]);
    expect(new Set(INCIDENT_FLOW)).toEqual(new Set(Object.keys(INCIDENT_STATUS)));
  });

  it("describes anomalies without claiming compromise", () => {
    expect(CLASSIFICATION.SUSPECTED_ANOMALY.description).toMatch(/benign explanations exist/);
  });
});
