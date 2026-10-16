import { useGLTF } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { Color, type Material, Mesh, MeshStandardMaterial, type Object3D } from "three";
import type { AssetSummary } from "../api/types";
import { useTwinStore } from "../state/twin";

export const MODEL_URL = "/models/hospital.glb";

/** Walk up from a hit mesh to the node that carries the backend asset id (glTF extras). */
export function assetIdOf(object: Object3D | null): string | null {
  let current: Object3D | null = object;
  while (current) {
    const id = current.userData?.asset_id;
    if (typeof id === "string") return id;
    current = current.parent;
  }
  return null;
}

const ABNORMAL_TINT: Record<string, string> = {
  SUSPICIOUS: "#f5b945",
  QUARANTINED: "#f04452",
  REVOKED: "#d0647a",
  UNREGISTERED: "#c084fc",
  OFFLINE: "#334155",
};

function tintFor(asset: AssetSummary | undefined, selected: boolean, hovered: boolean): { color: string; intensity: number } | null {
  if (selected) return { color: "#22c3d6", intensity: 0.35 };
  if (asset?.containment_state === "ISOLATED") return { color: "#f04452", intensity: 0.45 };
  const state = asset?.trust_state ?? "";
  if (ABNORMAL_TINT[state]) return { color: ABNORMAL_TINT[state], intensity: state === "OFFLINE" ? 0.15 : 0.32 };
  if (hovered) return { color: "#67e0ec", intensity: 0.18 };
  return null;
}

export function HospitalModel() {
  const { scene } = useGLTF(MODEL_URL);
  const assets = useTwinStore((s) => s.assets);
  const selectedId = useTwinStore((s) => s.selectedId);
  const hoveredId = useTwinStore((s) => s.hoveredId);
  const select = useTwinStore((s) => s.select);
  const hover = useTwinStore((s) => s.hover);
  const setMappingIssues = useTwinStore((s) => s.setMappingIssues);

  // Index asset nodes and give each its own material instances so state tints never leak
  // into other instances that share the template's mesh data.
  const assetNodes = useMemo(() => {
    const nodes = new Map<string, Object3D>();
    scene.traverse((obj) => {
      const id = obj.userData?.asset_id;
      if (typeof id === "string") {
        nodes.set(id, obj);
        obj.traverse((child) => {
          if (child instanceof Mesh) {
            child.material = Array.isArray(child.material)
              ? child.material.map((m: Material) => m.clone())
              : (child.material as Material).clone();
          }
        });
      }
      if (obj instanceof Mesh) {
        obj.castShadow = false;
        obj.receiveShadow = false;
      }
    });
    return nodes;
  }, [scene]);

  // Verify the Blender <-> backend mapping on every inventory change.
  useEffect(() => {
    const issues: string[] = [];
    for (const asset of Object.values(assets)) {
      if (asset.twin_node && !assetNodes.has(asset.id)) issues.push(`${asset.id}: node ${asset.twin_node} missing from model`);
    }
    for (const id of assetNodes.keys()) {
      if (!assets[id]) issues.push(`${id}: model node has no backend asset`);
    }
    if (Object.keys(assets).length) setMappingIssues(issues);
  }, [assets, assetNodes, setMappingIssues]);

  // Apply backend-driven state tints (only abnormal states are tinted).
  useEffect(() => {
    for (const [id, node] of assetNodes) {
      const tint = tintFor(assets[id], id === selectedId, id === hoveredId);
      node.traverse((child) => {
        if (!(child instanceof Mesh)) return;
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        for (const material of materials) {
          if (!(material instanceof MeshStandardMaterial)) continue;
          const base = (material.userData.baseEmissive as Color | undefined) ?? material.emissive.clone();
          const baseIntensity = (material.userData.baseIntensity as number | undefined) ?? material.emissiveIntensity;
          material.userData.baseEmissive = base;
          material.userData.baseIntensity = baseIntensity;
          if (tint) {
            material.emissive.set(tint.color);
            material.emissiveIntensity = tint.intensity;
          } else {
            material.emissive.copy(base);
            material.emissiveIntensity = baseIntensity;
          }
        }
      });
    }
  }, [assets, assetNodes, selectedId, hoveredId]);

  const onClick = (event: ThreeEvent<MouseEvent>) => {
    const id = assetIdOf(event.object);
    if (id) {
      event.stopPropagation();
      select(id);
    }
  };
  const onOver = (event: ThreeEvent<PointerEvent>) => {
    const id = assetIdOf(event.object);
    if (id) {
      event.stopPropagation();
      hover(id);
      document.body.style.cursor = "pointer";
    }
  };
  const onOut = () => {
    hover(null);
    document.body.style.cursor = "";
  };

  return <primitive object={scene} onClick={onClick} onPointerOver={onOver} onPointerOut={onOut} />;
}

useGLTF.preload(MODEL_URL);
