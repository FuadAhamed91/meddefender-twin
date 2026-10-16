import { Bloom, EffectComposer, N8AO, Outline, ToneMapping, Vignette } from "@react-three/postprocessing";
import { ToneMappingMode } from "postprocessing";
import { useMemo } from "react";
import { Mesh, type Object3D } from "three";
import { useTwinStore } from "../state/twin";
import { assetNodeRegistry } from "./registry";

/**
 * Meshes of the selected and hovered devices. The outline effect enables its render layer only
 * on the objects it is given (not their descendants), so the meshes themselves are passed.
 */
function useSelectionObjects(): Object3D[] {
  const selectedId = useTwinStore((s) => s.selectedId);
  const hoveredId = useTwinStore((s) => s.hoveredId);
  return useMemo(() => {
    const out = new Set<Object3D>();
    for (const id of [selectedId, hoveredId]) {
      const node = id ? assetNodeRegistry.get(id) : undefined;
      node?.traverse((child) => {
        if (child instanceof Mesh) out.add(child);
      });
    }
    return [...out];
  }, [selectedId, hoveredId]);
}

/**
 * Post-processing. Holographic: bloom on HDR edges, beacons and live flows only (threshold
 * keeps ordinary surfaces crisp). Realistic: ambient occlusion for depth plus a light bloom on
 * screens and signage. Both: an outline around the selected or hovered device, a soft
 * vignette, and ACES tone mapping (the composer disables the renderer's own tone mapping).
 */
export function Effects() {
  const mode = useTwinStore((s) => s.viewMode);
  const selection = useSelectionObjects();
  if (mode === "realistic") {
    return (
      <EffectComposer key="realistic" multisampling={4} autoClear={false}>
        <N8AO aoRadius={2} distanceFalloff={1} intensity={3.2} quality="performance" halfRes />
        {/* Bloom runs before tone mapping, so a threshold above 1 catches only emissive signage. */}
        <Bloom intensity={0.5} luminanceThreshold={1.3} luminanceSmoothing={0.1} mipmapBlur radius={0.5} />
        <Outline selection={selection} visibleEdgeColor={0x22c3d6} hiddenEdgeColor={0x0e7490} edgeStrength={5} blur xRay />
        <Vignette offset={0.3} darkness={0.45} />
        <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      </EffectComposer>
    );
  }
  return (
    <EffectComposer key="holographic" multisampling={4} autoClear={false}>
      <Bloom intensity={1.1} luminanceThreshold={0.32} luminanceSmoothing={0.25} mipmapBlur radius={0.7} />
      <Outline selection={selection} visibleEdgeColor={0x67e0ec} hiddenEdgeColor={0x1f8fa0} edgeStrength={6} blur xRay />
      <Vignette offset={0.26} darkness={0.62} />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
    </EffectComposer>
  );
}
