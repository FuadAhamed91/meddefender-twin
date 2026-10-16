import { Color, EdgesGeometry, LineBasicMaterial, LineSegments, type Material, Mesh, type MeshStandardMaterial, type Object3D } from "three";
import { addFloorTiles } from "./materials";

export type Part = "floor" | "wallSolid" | "wallGlass" | "decor" | "site" | "asset";

function classify(topName: string): Part | null {
  if (topName.startsWith("AST_")) return "asset";
  if (topName.startsWith("ROOM_")) return "floor";
  if (topName === "ARCH_Walls_Solid") return "wallSolid";
  if (topName === "ARCH_Walls_Glass") return "wallGlass";
  if (topName === "ARCH_Site") return "site";
  if (topName.startsWith("DECOR_")) return "decor";
  return null;
}

/** Realistic view: walls, furniture and equipment cast shadows; glass and floors only receive. */
function shadowFlags(part: Part, material: Material): { cast: boolean; receive: boolean } {
  const opaque = !material.transparent;
  return {
    cast: opaque && (part === "wallSolid" || part === "decor" || part === "asset"),
    receive: part !== "wallGlass",
  };
}

export interface PreparedScene {
  assetNodes: Map<string, Object3D>;
  parts: Record<Part, Mesh[]>;
  edges: LineSegments[];
}

// useGLTF caches the parsed model for the life of the page, so every visit to the Twin page
// gets the same objects back. Prepare them exactly once: doing it again cloned the device
// materials anew and recorded the current view's materials as the "original" ones.
const preparedScenes = new WeakMap<Object3D, PreparedScene>();

/**
 * One pass over the model: index asset nodes, classify architecture, remember original
 * materials, give each asset its own material instances and build edge overlays.
 */
export function prepareScene(scene: Object3D): PreparedScene {
  const cached = preparedScenes.get(scene);
  if (cached) return cached;
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
    if (part === "wallSolid" || part === "decor") {
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
      edges.push(line);
    }
  });
  const result = { assetNodes, parts, edges };
  preparedScenes.set(scene, result);
  return result;
}

export interface MaterialBase {
  color: Color;
  emissive: Color;
  emissiveIntensity: number;
  ownGlow: boolean;
}

// Kept out of material.userData, which three.js copies through JSON when a material is cloned:
// that turned these Colors into plain numbers, the tints became NaN, and bloom spread the NaN
// pixels over the whole frame.
const materialBases = new WeakMap<Material, MaterialBase>();

/** A device material's own look before any tint, captured the first time it is seen. */
export function materialBaseOf(material: MeshStandardMaterial): MaterialBase {
  let base = materialBases.get(material);
  if (!base) {
    base = {
      color: material.color.clone(),
      emissive: material.emissive.clone(),
      emissiveIntensity: material.emissiveIntensity,
      ownGlow: material.emissiveIntensity > 0 && material.emissive.getHex() !== 0,
    };
    materialBases.set(material, base);
  }
  return base;
}
