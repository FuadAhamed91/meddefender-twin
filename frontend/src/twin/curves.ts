import { QuadraticBezierCurve3, Vector3 } from "three";
import type { AssetSummary } from "../api/types";
import { planToWorld } from "../lib/coords";

export const LINK_HEIGHT = 2.6;

export function anchorOf(asset: AssetSummary | undefined, height = LINK_HEIGHT): Vector3 | null {
  if (!asset?.position) return null;
  return planToWorld(asset.position.x, asset.position.y, height);
}

/**
 * Curve between two anchors. The control point is lifted and pushed to the same side of the
 * direction of travel every time, so A->B and B->A bow apart and render as two distinct arcs.
 */
export function arc(start: Vector3, end: Vector3, lift: number): QuadraticBezierCurve3 {
  const mid = start.clone().add(end).multiplyScalar(0.5);
  const dir = end.clone().sub(start);
  const length = dir.length();
  // Perpendicular in the ground plane; reversing the direction flips it to the other side.
  const side = new Vector3(-dir.z, 0, dir.x).normalize().multiplyScalar(0.5);
  mid.add(side).add(new Vector3(0, lift + length * 0.08, 0));
  return new QuadraticBezierCurve3(start, mid, end);
}
