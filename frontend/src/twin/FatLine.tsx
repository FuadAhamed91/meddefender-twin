import { useThree } from "@react-three/fiber";
import { type Ref, useEffect, useLayoutEffect, useMemo } from "react";
import type { Vector3 } from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";

export interface FatLineProps {
  points: Vector3[];
  color: string;
  /** Width in CSS pixels. */
  width: number;
  opacity: number;
  dashed?: boolean;
  dashSize?: number;
  gapSize?: number;
  ref?: Ref<Line2>;
}

/**
 * Screen-space wide line for overlays (three's Line2). Unlike drei's <Line>, which disposes its
 * material whenever the points change, the material here lives as long as the component and
 * geometry is updated in place. Live updates therefore never force a shader program to be
 * released and recompiled: on a cold shader cache or a software renderer that recompilation
 * blocked the page for seconds at a time.
 */
export function FatLine({ points, color, width, opacity, dashed = false, dashSize = 0.35, gapSize = 0.25, ref }: FatLineProps) {
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);
  const line = useMemo(() => {
    const material = new LineMaterial({ transparent: true, depthWrite: false, dashed });
    return new Line2(new LineGeometry(), material);
  }, [dashed]);

  useLayoutEffect(() => {
    line.geometry.setPositions(points.flatMap((p) => [p.x, p.y, p.z]));
    line.computeLineDistances();
    invalidate();
  }, [line, points, invalidate]);

  useLayoutEffect(() => {
    const material = line.material;
    material.color.set(color);
    material.linewidth = width;
    material.opacity = opacity;
    material.dashSize = dashSize;
    material.gapSize = gapSize;
    material.resolution.set(size.width, size.height);
    invalidate();
  }, [line, color, width, opacity, dashSize, gapSize, size, invalidate]);

  // The geometry owns GPU buffers and is released. The material is intentionally not disposed:
  // it holds no GPU memory itself, and keeping its program reference alive means the next
  // overlay line of the same kind reuses the compiled shader instead of compiling it again.
  useEffect(() => () => line.geometry.dispose(), [line]);

  return <primitive ref={ref} object={line} raycast={() => undefined} />;
}
