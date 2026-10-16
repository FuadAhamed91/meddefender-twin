import { describe, expect, it } from "vitest";
import type { AssetSummary } from "../api/types";
import { boundsCenter, boundsSize, FLOOR_BOUNDS, planToWorld } from "../lib/coords";
import { anchorOf, arc, LINK_HEIGHT } from "./curves";

const asset = (id: string, x: number, y: number) => ({ id, position: { x, y, rotation: 0 } }) as unknown as AssetSummary;

describe("plan to world coordinates", () => {
  it("maps plan (x east, y north, h up) to three.js (x, h, -y)", () => {
    const p = planToWorld(10, 20, 2);
    expect([p.x, p.y, p.z]).toEqual([10, 2, -20]);
  });

  it("computes room centres and sizes", () => {
    const bounds = { min: [4, 6] as [number, number], max: [10, 14] as [number, number] };
    const c = boundsCenter(bounds, 1);
    expect([c.x, c.y, c.z]).toEqual([7, 1, -10]);
    expect(boundsSize(bounds)).toEqual({ width: 6, depth: 8 });
  });

  it("matches the shared hospital layout footprint", () => {
    expect(FLOOR_BOUNDS).toEqual({ min: [0, 0], max: [56, 36] });
  });
});

describe("flow arcs", () => {
  it("anchors links above an asset, or nowhere without a position", () => {
    expect(anchorOf(undefined)).toBeNull();
    expect(anchorOf({ ...asset("A", 1, 2), position: null })).toBeNull();
    const anchor = anchorOf(asset("A", 1, 2))!;
    expect([anchor.x, anchor.y, anchor.z]).toEqual([1, LINK_HEIGHT, -2]);
  });

  it("keeps endpoints and lifts the control point", () => {
    const a = planToWorld(0, 0, 2);
    const b = planToWorld(10, 0, 2);
    const curve = arc(a, b, 1);
    expect(curve.v0.equals(a)).toBe(true);
    expect(curve.v2.equals(b)).toBe(true);
    expect(curve.v1.y).toBeGreaterThan(a.y);
  });

  it("draws A->B and B->A as two distinct arcs", () => {
    const a = planToWorld(0, 0, 2);
    const b = planToWorld(10, 0, 2);
    const forward = arc(a, b, 1);
    const backward = arc(b, a, 1);
    expect(forward.v1.distanceTo(backward.v1)).toBeGreaterThan(0.5);
  });
});
