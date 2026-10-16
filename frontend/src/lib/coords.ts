import { Vector3 } from "three";
import type { AssetSummary, Bounds } from "../api/types";

/**
 * Layout plan coordinates (x = east, y = north, metres) -> Three.js world coordinates.
 * The Blender exporter converts Z-up to Y-up, so plan (x, y, h) becomes (x, h, -y).
 */
export function planToWorld(x: number, y: number, height = 0): Vector3 {
  return new Vector3(x, height, -y);
}

export function assetAnchor(asset: AssetSummary, height?: number): Vector3 {
  const p = asset.position ?? { x: 0, y: 0, rotation: 0 };
  return planToWorld(p.x, p.y, height ?? asset.label_height ?? 1.8);
}

export function boundsCenter(bounds: Bounds, height = 0): Vector3 {
  return planToWorld((bounds.min[0] + bounds.max[0]) / 2, (bounds.min[1] + bounds.max[1]) / 2, height);
}

export function boundsSize(bounds: Bounds): { width: number; depth: number } {
  return { width: bounds.max[0] - bounds.min[0], depth: bounds.max[1] - bounds.min[1] };
}

export const FLOOR_BOUNDS: Bounds = { min: [0, 0], max: [56, 36] };
