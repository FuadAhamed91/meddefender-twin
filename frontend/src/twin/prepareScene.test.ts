import { BoxGeometry, Group, LineSegments, Mesh, MeshStandardMaterial } from "three";
import { describe, expect, it } from "vitest";
import { materialBaseOf, prepareScene } from "./prepareScene";

function model() {
  const scene = new Group();
  const shared = new MeshStandardMaterial({ color: "#336699" });
  const device = new Group();
  device.name = "AST_ICU-MONITOR-01";
  device.userData.asset_id = "ICU-MONITOR-01";
  device.add(new Mesh(new BoxGeometry(), shared));
  const walls = new Group();
  walls.name = "ARCH_Walls_Solid";
  walls.add(new Mesh(new BoxGeometry(), new MeshStandardMaterial()));
  scene.add(device, walls);
  return { scene, shared };
}

describe("prepareScene", () => {
  it("prepares the cached model once, however often the twin page mounts", () => {
    const { scene, shared } = model();
    const first = prepareScene(scene);
    expect([...first.assetNodes.keys()]).toEqual(["ICU-MONITOR-01"]);
    const device = first.parts.asset[0];
    const own = device.material;
    expect(own).not.toBe(shared); // each device gets its own material to tint
    const wall = first.parts.wallSolid[0];
    const original = wall.userData.originalMaterial;
    wall.material = new MeshStandardMaterial(); // what the holographic view does

    const second = prepareScene(scene);
    expect(second).toBe(first);
    expect(device.material).toBe(own);
    expect(wall.userData.originalMaterial).toBe(original);
    expect(wall.children.filter((c) => c instanceof LineSegments)).toHaveLength(1);
  });
});

describe("materialBaseOf", () => {
  it("keeps real colours for cloned device materials", () => {
    const material = new MeshStandardMaterial({ color: "#336699", emissive: "#112233", emissiveIntensity: 0.5 });
    materialBaseOf(material);
    const base = materialBaseOf(material.clone());
    expect(base.color.isColor).toBe(true);
    expect(base.color.getHexString()).toBe("336699");
    expect(base.emissive.getHexString()).toBe("112233");
    expect(base.ownGlow).toBe(true);
  });
});
