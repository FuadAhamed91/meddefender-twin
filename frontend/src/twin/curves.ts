import { QuadraticBezierCurve3, Vector3 } from "three";
import type { AssetSummary } from "../api/types";
import { planToWorld } from "../lib/coords";

export const LINK_HEIGHT = 2.6;

export function anchorOf(asset: AssetSummary | undefined, height = LINK_HEIGHT): Vector3 | null {
  if (!asset?.position) return null;
  return planToWorld(asset.position.x, asset.position.y, height);
}

/**
 * Curve between two anchors. The control point is lifted and pushed sideways depending on
 * direction, so A->B and B->A render as two distinct arcs.
 */
export function arc(start: Vector3, end: Vector3, lift: number, sourceId: string, destId: string): QuadraticBezierCurve3 {
  const mid = start.clone().add(end).multiplyScalar(0.5);
  const dir = end.clone().sub(start);
  const length = dir.length();
  const side = new Vector3(-dir.z, 0, dir.x).normalize().multiplyScalar(sourceId < destId ? 0.5 : -0.5);
  mid.add(side).add(new Vector3(0, lift + length * 0.08, 0));
  return new QuadraticBezierCurve3(start, mid, end);
}

export function arrowPose(curve: QuadraticBezierCurve3, t = 0.82): { position: Vector3; quaternionFrom: Vector3; direction: Vector3 } {
  const position = curve.getPoint(t);
  const direction = curve.getTangent(t).normalize();
  return { position, quaternionFrom: new Vector3(0, 1, 0), direction };
}
