import { useGLTF } from "@react-three/drei";
import { type ThreeEvent, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import {
  Color,
  EdgesGeometry,
  LineBasicMaterial,
  LineSegments,
  type Material,
  Mesh,
  MeshStandardMaterial,
  type Object3D,
} from "three";
import type { AssetSummary } from "../api/types";
import { useTwinStore, type ViewMode } from "../state/twin";
import { addFloorTiles, floorGridMaterial, hologramMaterial } from "./materials";
import { assetNodeRegistry } from "./registry";

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

type Part = "floor" | "wallSolid" | "wallGlass" | "decor" | "site" | "asset";

function classify(topName: string): Part | null {
  if (topName.startsWith("AST_")) return "asset";
  if (topName.startsWith("ROOM_")) return "floor";
  if (topName === "ARCH_Walls_Solid") return "wallSolid";
  if (topName === "ARCH_Walls_Glass") return "wallGlass";
  if (topName === "ARCH_Site") return "site";
  if (topName.startsWith("DECOR_")) return "decor";
  return null;
}

/** Holographic look (security view): fresnel-lit translucent architecture on a gridded floor. */
function holoMaterials(): Record<Exclude<Part, "asset">, Material> {
  return {
    floor: floorGridMaterial("#081a33", "#2563eb"),
    wallSolid: hologramMaterial("#3b82f6", { opacity: 0.12, rim: 1.3, top: 1.5, height: 2.5 }),
    wallGlass: hologramMaterial("#38bdf8", { opacity: 0.07, rim: 1.1, top: 1.1, height: 2.5 }),
    decor: hologramMaterial("#8cbcff", { opacity: 0.2, rim: 1.1, top: 0.5, height: 2 }),
    site: new MeshStandardMaterial({ color: "#040b18", roughness: 1 }),
  };
}

/** Realistic view: walls, furniture and equipment cast shadows; glass and floors only receive. */
function shadowFlags(part: Part, material: Material): { cast: boolean; receive: boolean } {
  const opaque = !material.transparent;
  return {
    cast: opaque && (part === "wallSolid" || part === "decor" || part === "asset"),
    receive: part !== "wallGlass",
  };
}

const ABNORMAL_TINT: Record<string, string> = {
  SUSPICIOUS: "#f5b945",
  QUARANTINED: "#f04452",
  REVOKED: "#d0647a",
  UNREGISTERED: "#c084fc",
  OFFLINE: "#334155",
};

function tintFor(asset: AssetSummary | undefined, selected: boolean, hovered: boolean): { color: string; intensity: number } | null {
  if (selected) return { color: "#22c3d6", intensity: 0.45 };
  if (asset?.containment_state === "ISOLATED") return { color: "#f04452", intensity: 0.5 };
  const state = asset?.trust_state ?? "";
  if (ABNORMAL_TINT[state]) return { color: ABNORMAL_TINT[state], intensity: state === "OFFLINE" ? 0.15 : 0.4 };
  if (hovered) return { color: "#67e0ec", intensity: 0.22 };
  return null;
}

interface MaterialBase {
  color: Color;
  emissive: Color;
  emissiveIntensity: number;
  ownGlow: boolean;
}

export function HospitalModel() {
  const { scene } = useGLTF(MODEL_URL);
  const assets = useTwinStore((s) => s.assets);
  const selectedId = useTwinStore((s) => s.selectedId);
  const hoveredId = useTwinStore((s) => s.hoveredId);
  const viewMode = useTwinStore((s) => s.viewMode);
  const select = useTwinStore((s) => s.select);
  const hover = useTwinStore((s) => s.hover);
  const setMappingIssues = useTwinStore((s) => s.setMappingIssues);
  const invalidate = useThree((s) => s.invalidate);
  const gl = useThree((s) => s.gl);

  // One pass over the scene: index asset nodes, classify architecture, remember original
  // materials, give each asset its own material instances and build edge overlays.
  const index = useMemo(() => {
    const assetNodes = new Map<string, Object3D>();
    const parts: Record<Part, Mesh[]> = { floor: [], wallSolid: [], wallGlass: [], decor: [], site: [], asset: [] };
    const edges: LineSegments[] = [];
    const topOf = (obj: Object3D): Object3D => {
      let current = obj;
      while (current.parent && current.parent !== scene) current = current.parent;
      return current;
    };
    scene.traverse((obj) => {
      const id = obj.userData?.asset_id;
      if (typeof id === "string") assetNodes.set(id, obj);
      if (!(obj instanceof Mesh)) return;
      const part = classify(topOf(obj).name);
      if (!part) return;
      parts[part].push(obj);
      if (part === "asset") {
        obj.material = Array.isArray(obj.material) ? obj.material.map((m: Material) => m.clone()) : (obj.material as Material).clone();
      }
      if (part === "floor") addFloorTiles(obj.material as Material);
      obj.userData.originalMaterial = obj.material;
      const flags = shadowFlags(part, Array.isArray(obj.material) ? obj.material[0] : obj.material);
      obj.castShadow = flags.cast;
      obj.receiveShadow = flags.receive;
      if ((part === "wallSolid" || part === "decor") && !obj.userData.edges) {
        // HDR-bright edge colors (above 1.0, not tone-mapped) so the bloom pass makes the
        // architecture glow while dark surfaces stay crisp.
        const edgeMaterial = new LineBasicMaterial({
          color: new Color(part === "decor" ? "#7dd3fc" : "#60a5fa").multiplyScalar(part === "decor" ? 1.1 : 1.6),
          transparent: true,
          opacity: part === "decor" ? 0.3 : 0.7,
          toneMapped: false,
        });
        const line = new LineSegments(new EdgesGeometry(obj.geometry, part === "decor" ? 40 : 30), edgeMaterial);
        line.raycast = () => undefined; // edges never steal picks
        obj.add(line);
        obj.userData.edges = line;
        edges.push(line);
      }
    });
    assetNodeRegistry.clear();
    for (const [id, node] of assetNodes) assetNodeRegistry.set(id, node);
    return { assetNodes, parts, edges };
  }, [scene]);

  const holo = useMemo(holoMaterials, []);
  useEffect(() => () => Object.values(holo).forEach((m) => m.dispose()), [holo]);

  // Verify the Blender <-> backend mapping on every inventory change.
  useEffect(() => {
    const issues: string[] = [];
    for (const asset of Object.values(assets)) {
      if (asset.twin_node && !index.assetNodes.has(asset.id)) issues.push(`${asset.id}: node ${asset.twin_node} missing from model`);
    }
    for (const id of index.assetNodes.keys()) {
      if (!assets[id]) issues.push(`${id}: model node has no backend asset`);
    }
    if (Object.keys(assets).length) setMappingIssues(issues);
  }, [assets, index, setMappingIssues]);

  // View style: swap architecture materials, show glowing edges only in holographic mode.
  useEffect(() => {
    applyViewMode(viewMode, index.parts, holo);
    for (const line of index.edges) line.visible = viewMode === "holographic";
    // The static shadow map (see SunLight) must be redrawn once the model or its materials change.
    gl.shadowMap.needsUpdate = true;
    invalidate();
  }, [viewMode, index, holo, invalidate, gl]);

  // Device materials: a per-mode baseline, then backend-driven tints for abnormal states.
  useEffect(() => {
    for (const [id, node] of index.assetNodes) {
      const tint = tintFor(assets[id], id === selectedId, id === hoveredId);
      node.traverse((child) => {
        if (!(child instanceof Mesh)) return;
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        for (const material of materials) {
          if (!(material instanceof MeshStandardMaterial)) continue;
          const base = (material.userData.base as MaterialBase | undefined) ?? {
            color: material.color.clone(),
            emissive: material.emissive.clone(),
            emissiveIntensity: material.emissiveIntensity,
            ownGlow: material.emissiveIntensity > 0 && material.emissive.getHex() !== 0,
          };
          material.userData.base = base;
          if (viewMode === "holographic") {
            material.color.copy(base.color).lerp(new Color("#d4e8ff"), base.ownGlow ? 0 : 0.55);
          } else {
            material.color.copy(base.color);
          }
          if (tint) {
            material.emissive.set(tint.color);
            material.emissiveIntensity = tint.intensity;
          } else if (base.ownGlow) {
            material.emissive.copy(base.emissive);
            material.emissiveIntensity = base.emissiveIntensity;
          } else if (viewMode === "holographic") {
            material.emissive.set("#1d4ed8");
            material.emissiveIntensity = 0.16;
          } else {
            material.emissive.copy(base.emissive);
            material.emissiveIntensity = base.emissiveIntensity;
          }
        }
      });
    }
    invalidate();
  }, [assets, index, selectedId, hoveredId, viewMode, invalidate]);

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

function applyViewMode(mode: ViewMode, parts: Record<Part, Mesh[]>, holo: Record<Exclude<Part, "asset">, Material>) {
  (Object.keys(holo) as Exclude<Part, "asset">[]).forEach((part) => {
    for (const mesh of parts[part]) {
      mesh.material = mode === "holographic" ? holo[part] : (mesh.userData.originalMaterial as Material);
    }
  });
}

useGLTF.preload(MODEL_URL);
