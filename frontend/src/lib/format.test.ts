import { describe, expect, it } from "vitest";
import { ago, formatValue, shortHash, titleCase } from "./format";

describe("ago", () => {
  const now = Date.parse("2026-10-16T12:00:00Z");
  it.each([
    ["2026-10-16T11:59:30Z", "30s ago"],
    ["2026-10-16T11:58:30Z", "2m ago"],
    ["2026-10-16T10:00:00Z", "2h ago"],
    ["2026-10-13T12:00:00Z", "3d ago"],
  ])("%s -> %s", (value, expected) => {
    expect(ago(value, now)).toBe(expected);
  });

  it("handles missing timestamps and clock skew", () => {
    expect(ago(null, now)).toBe("never");
    expect(ago("2026-10-16T12:00:05Z", now)).toBe("0s ago");
  });
});

describe("titleCase", () => {
  it("turns enum values into labels", () => {
    expect(titleCase("CONTAINMENT_PROPOSED")).toBe("Containment Proposed");
    expect(titleCase("rate limited")).toBe("Rate Limited");
  });
});

describe("formatValue", () => {
  it("formats numbers with units", () => {
    expect(formatValue(72, "bpm")).toBe("72 bpm");
    expect(formatValue(21.456, "°C")).toBe("21.46 °C");
  });

  it("keeps non-numeric strings and serialises objects", () => {
    expect(formatValue("RUNNING", "°C")).toBe("RUNNING");
    expect(formatValue("12.5", "mL/h")).toBe("12.5 mL/h");
    expect(formatValue({ mode: "auto" })).toBe('{"mode":"auto"}');
  });

  it("renders missing values as a dash", () => {
    expect(formatValue(null)).toBe("–");
    expect(formatValue(undefined, "bpm")).toBe("–");
  });
});

describe("shortHash", () => {
  it("truncates hashes for display", () => {
    expect(shortHash("0123456789abcdef")).toBe("0123456789");
    expect(shortHash("0123456789abcdef", 4)).toBe("0123");
    expect(shortHash(null)).toBe("–");
  });
});
