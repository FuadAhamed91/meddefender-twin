"""Build the MedDefender Twin hospital scene from shared/hospital_layout.json and export GLB.

Run headless (Blender 4.2+ / 5.x):

    blender --background --factory-startup --python blender/build_hospital.py -- \
        --layout shared/hospital_layout.json \
        --out frontend/public/models/hospital.glb \
        --blend blender/out/hospital.blend

Design rules
* Deterministic: the same layout always produces the same scene.
* Every modeled asset is ONE node named ``AST_<ASSET-ID>`` carrying the custom property
  ``asset_id`` (exported as glTF ``extras``). The frontend resolves picks through it and
  verifies the mapping against the backend inventory; names are never parsed for meaning.
* Equipment templates are built once and shared by mesh data (instances reuse geometry).
* Walls are joined into one mesh per material to keep draw calls low.
* No lights, cameras or textures are exported: the viewer owns lighting and status display.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Build the MedDefender Twin hospital GLB")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--blend", default=None)
    return parser.parse_args(argv)


# --------------------------------------------------------------------------------------
# Materials (sRGB hex -> linear; PBR, no textures)
# --------------------------------------------------------------------------------------


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_color(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(srgb_to_linear(int(value[i : i + 2], 16) / 255.0) for i in (0, 2, 4))  # type: ignore[return-value]


def mix_hex(a: str, b: str, t: float) -> str:
    a, b = a.lstrip("#"), b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va, vb = int(a[i : i + 2], 16), int(b[i : i + 2], 16)
        out.append(round(va + (vb - va) * t))
    return "#" + "".join(f"{v:02x}" for v in out)


MATERIALS: dict[str, bpy.types.Material] = {}


def material(
    name: str,
    color: str,
    *,
    roughness: float = 0.75,
    metallic: float = 0.0,
    alpha: float = 1.0,
    emission: str | None = None,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    if name in MATERIALS:
        return MATERIALS[name]
    mat = bpy.data.materials.new(name)
    tree = mat.node_tree
    if tree is None:  # pragma: no cover - Blender < 5 without nodes
        mat.use_nodes = True
        tree = mat.node_tree
    nodes = tree.nodes
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        nodes.clear()
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        out = nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    rgb = hex_color(color)
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Alpha"].default_value = alpha
    if emission:
        for key in ("Emission Color", "Emission"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = (*hex_color(emission), 1.0)
                break
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emission_strength
    if alpha < 1.0 and hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    mat.diffuse_color = (*rgb, alpha)
    MATERIALS[name] = mat
    return mat


def build_palette(zones: list[dict]) -> None:
    material("M_Floor_Corridor", "#1d2633", roughness=0.92)
    for zone in zones:
        tint = mix_hex("#162030", zone["color"], 0.16)
        material(f"M_Floor_{zone['id']}", tint, roughness=0.9)
    material("M_Wall", "#9aa8b9", roughness=0.85)
    material("M_WallCap", "#c8d2de", roughness=0.7)
    material("M_Glass", "#7fd0e3", roughness=0.08, alpha=0.18)
    material("M_Shell", "#dfe5ec", roughness=0.55)
    material("M_ShellWarm", "#e8e2d6", roughness=0.6)
    material("M_Graphite", "#2a313d", roughness=0.6, metallic=0.2)
    material("M_Steel", "#8d97a5", roughness=0.35, metallic=0.85)
    material("M_Screen", "#0b1622", roughness=0.25, emission="#1aa8bb", emission_strength=0.35)
    material("M_Linen", "#d9e1ea", roughness=0.95)
    material("M_AccentTeal", "#22b8c8", roughness=0.4, emission="#22b8c8", emission_strength=0.6)
    material("M_AccentAmber", "#e0a335", roughness=0.4, emission="#e0a335", emission_strength=0.5)
    material("M_AccentRed", "#e05252", roughness=0.4, emission="#e05252", emission_strength=0.5)
    material("M_AccentBlue", "#4f9fe8", roughness=0.4, emission="#4f9fe8", emission_strength=0.5)


# --------------------------------------------------------------------------------------
# Geometry helpers (bmesh, no operator context required)
# --------------------------------------------------------------------------------------


class MeshBuilder:
    """Accumulates primitive parts into one bmesh with per-part material slots."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.bm = bmesh.new()
        self.slots: list[str] = []

    def _slot(self, material_name: str) -> int:
        if material_name not in self.slots:
            self.slots.append(material_name)
        return self.slots.index(material_name)

    def _tag_new_faces(self, start: int, material_name: str, smooth: bool = False) -> None:
        self.bm.faces.ensure_lookup_table()
        index = self._slot(material_name)
        for face in self.bm.faces[start:]:
            face.material_index = index
            face.smooth = smooth

    def box(self, center: tuple[float, float, float], size: tuple[float, float, float], mat: str) -> MeshBuilder:
        start = len(self.bm.faces)
        m = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*size, 1.0))
        bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        self._tag_new_faces(start, mat)
        return self

    def cylinder(
        self,
        center: tuple[float, float, float],
        radius: float,
        depth: float,
        mat: str,
        *,
        axis: str = "Z",
        segments: int = 20,
        radius_top: float | None = None,
    ) -> MeshBuilder:
        start = len(self.bm.faces)
        rot = {"Z": Matrix.Identity(4), "X": Matrix.Rotation(math.pi / 2, 4, "Y"), "Y": Matrix.Rotation(math.pi / 2, 4, "X")}[axis]
        m = Matrix.Translation(Vector(center)) @ rot
        bmesh.ops.create_cone(
            self.bm, cap_ends=True, cap_tris=False, segments=segments, radius1=radius,
            radius2=radius if radius_top is None else radius_top, depth=depth, matrix=m,
        )
        self._tag_new_faces(start, mat, smooth=True)
        return self

    def torus(
        self, center: tuple[float, float, float], major: float, minor: float, mat: str,
        *, axis: str = "Y", major_segments: int = 40, minor_segments: int = 14,
    ) -> MeshBuilder:
        start = len(self.bm.faces)
        rot = {"Z": Matrix.Identity(3), "Y": Matrix.Rotation(math.pi / 2, 3, "X"), "X": Matrix.Rotation(math.pi / 2, 3, "Y")}[axis]
        c = Vector(center)
        rings = []
        for i in range(major_segments):
            u = 2 * math.pi * i / major_segments
            ring = []
            for j in range(minor_segments):
                v = 2 * math.pi * j / minor_segments
                p = Vector(((major + minor * math.cos(v)) * math.cos(u), (major + minor * math.cos(v)) * math.sin(u), minor * math.sin(v)))
                ring.append(self.bm.verts.new(c + rot @ p))
            rings.append(ring)
        for i in range(major_segments):
            a, b = rings[i], rings[(i + 1) % major_segments]
            for j in range(minor_segments):
                k = (j + 1) % minor_segments
                self.bm.faces.new((a[j], b[j], b[k], a[k]))
        self._tag_new_faces(start, mat, smooth=True)
        return self

    def finish(self) -> bpy.types.Mesh:
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        mesh = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for slot in self.slots:
            mesh.materials.append(MATERIALS[slot])
        return mesh


# --------------------------------------------------------------------------------------
# Equipment templates (origin at floor, front faces -Y)
# --------------------------------------------------------------------------------------


def rack(name: str, accent: str, bands: int = 3, panel: str = "M_Steel") -> bpy.types.Mesh:
    b = MeshBuilder(name)
    b.box((0, 0, 0.9), (0.6, 0.8, 1.8), "M_Graphite")
    for i in range(bands):
        z = 1.45 - i * 0.28
        b.box((0, -0.405, z), (0.52, 0.02, 0.16), panel)
        b.box((0.2, -0.418, z), (0.06, 0.01, 0.03), accent)
    b.box((0, -0.41, 1.72), (0.54, 0.02, 0.04), accent)
    return b.finish()


def workstation(name: str, screens: int) -> bpy.types.Mesh:
    width = 1.2 + 0.6 * (screens - 1)
    b = MeshBuilder(name)
    b.box((0, 0, 0.73), (width, 0.75, 0.04), "M_ShellWarm")
    for x in (-width / 2 + 0.06, width / 2 - 0.06):
        b.box((x, 0, 0.36), (0.05, 0.68, 0.72), "M_Graphite")
    offsets = [0.0] if screens == 1 else [(i - (screens - 1) / 2) * 0.6 for i in range(screens)]
    for x in offsets:
        b.box((x, 0.12, 0.78), (0.18, 0.12, 0.02), "M_Graphite")
        b.box((x, 0.14, 0.88), (0.04, 0.04, 0.2), "M_Graphite")
        b.box((x, 0.12, 1.08), (0.56, 0.04, 0.34), "M_Graphite")
        b.box((x, 0.098, 1.08), (0.52, 0.01, 0.3), "M_Screen")
    b.box((0, -0.18, 0.76), (0.46, 0.15, 0.02), "M_Graphite")
    return b.finish()


def build_templates() -> dict[str, bpy.types.Mesh]:
    t: dict[str, bpy.types.Mesh] = {}

    m = MeshBuilder("TPL_patient_monitor")
    m.cylinder((0, 0, 0.025), 0.26, 0.05, "M_Steel")
    m.cylinder((0, 0, 0.65), 0.022, 1.2, "M_Steel", segments=12)
    m.box((0, 0, 1.33), (0.44, 0.1, 0.34), "M_Shell")
    m.box((0, -0.052, 1.34), (0.36, 0.01, 0.24), "M_Screen")
    m.box((0.17, -0.054, 1.47), (0.04, 0.01, 0.02), "M_AccentTeal")
    t["patient_monitor"] = m.finish()

    p = MeshBuilder("TPL_infusion_pump")
    p.cylinder((0, 0, 0.025), 0.24, 0.05, "M_Steel")
    p.cylinder((0, 0, 0.85), 0.018, 1.6, "M_Steel", segments=12)
    p.box((0, -0.02, 1.05), (0.24, 0.16, 0.3), "M_Shell")
    p.box((0, -0.102, 1.11), (0.16, 0.01, 0.08), "M_Screen")
    p.box((0, 0, 1.62), (0.3, 0.02, 0.02), "M_Steel")
    p.box((0.12, 0, 1.52), (0.1, 0.05, 0.16), "M_Linen")
    t["infusion_pump"] = p.finish()

    t["gateway_rack"] = rack("TPL_gateway_rack", "M_AccentTeal", bands=2)
    t["switch_rack"] = rack("TPL_switch_rack", "M_AccentBlue", bands=4)
    t["firewall_rack"] = rack("TPL_firewall_rack", "M_AccentRed", bands=2)
    t["server_rack"] = rack("TPL_server_rack", "M_AccentBlue", bands=5)
    t["sensor_rack"] = rack("TPL_sensor_rack", "M_AccentAmber", bands=2)
    t["rack_blank"] = rack("TPL_rack_blank", "M_Graphite", bands=0)
    t["workstation"] = workstation("TPL_workstation", 1)
    t["workstation_dual"] = workstation("TPL_workstation_dual", 2)
    t["workstation_triple"] = workstation("TPL_workstation_triple", 3)

    s = MeshBuilder("TPL_wall_sensor")
    s.box((0, 0.02, 1.5), (0.16, 0.02, 0.16), "M_Graphite")
    s.box((0, -0.01, 1.5), (0.12, 0.05, 0.12), "M_Shell")
    s.box((0, -0.037, 1.53), (0.06, 0.005, 0.03), "M_Screen")
    s.box((0.04, -0.038, 1.47), (0.015, 0.005, 0.015), "M_AccentAmber")
    t["wall_sensor"] = s.finish()

    ct = MeshBuilder("TPL_ct_scanner")
    ct.box((0, 0, 0.35), (1.9, 0.9, 0.7), "M_Shell")
    ct.torus((0, 0, 1.25), 0.78, 0.32, "M_Shell", axis="Y")
    ct.box((0, -0.46, 1.25), (0.5, 0.02, 0.08), "M_AccentTeal")
    t["ct_scanner"] = ct.finish()

    w = MeshBuilder("TPL_wall_panel")
    w.box((0, 0, 1.2), (0.62, 0.22, 0.82), "M_Shell")
    w.box((0, -0.115, 1.38), (0.3, 0.01, 0.16), "M_Screen")
    w.box((-0.2, -0.116, 1.0), (0.05, 0.01, 0.05), "M_AccentAmber")
    t["wall_panel"] = w.finish()

    c = MeshBuilder("TPL_control_cabinet")
    c.box((0, 0, 0.8), (0.85, 0.5, 1.6), "M_Shell")
    c.box((0, -0.255, 1.25), (0.32, 0.01, 0.2), "M_Screen")
    c.box((0.3, -0.256, 0.9), (0.06, 0.01, 0.06), "M_AccentAmber")
    t["control_cabinet"] = c.finish()

    # ---- decor -----------------------------------------------------------------------
    bed = MeshBuilder("TPL_bed")
    bed.box((0, 0, 0.35), (0.95, 2.1, 0.18), "M_Steel")
    bed.box((0, -0.05, 0.53), (0.9, 1.9, 0.18), "M_Linen")
    bed.box((0, 1.02, 0.7), (0.95, 0.06, 0.6), "M_Shell")
    bed.box((0, 0.7, 0.66), (0.6, 0.35, 0.08), "M_Linen")
    for x in (-0.4, 0.4):
        for y in (-0.9, 0.9):
            bed.cylinder((x, y, 0.13), 0.035, 0.26, "M_Graphite", segments=10)
    t["bed"] = bed.finish()

    desk = MeshBuilder("TPL_nurse_desk")
    desk.box((0, 0, 0.53), (3.0, 0.75, 1.06), "M_ShellWarm")
    desk.box((0, -0.2, 1.07), (3.0, 0.4, 0.04), "M_Graphite")
    t["nurse_desk"] = desk.finish()

    table = MeshBuilder("TPL_ct_table")
    table.box((0, 0, 0.45), (0.45, 0.6, 0.9), "M_Shell")
    table.box((0, 0.7, 0.93), (0.5, 2.3, 0.08), "M_Linen")
    t["ct_table"] = table.finish()

    ahu = MeshBuilder("TPL_ahu")
    ahu.box((0, 0, 1.3), (6.0, 3.0, 2.6), "M_Steel")
    ahu.box((-3.02, 0, 1.2), (0.04, 2.4, 1.8), "M_Graphite")
    for x in (-1.5, 0.0, 1.5):
        ahu.cylinder((x, 0, 2.66), 0.5, 0.12, "M_Graphite", segments=18)
    t["ahu"] = ahu.finish()

    duct = MeshBuilder("TPL_duct")
    duct.box((0, 0, 2.2), (8.0, 0.6, 0.5), "M_Steel")
    t["duct"] = duct.finish()

    seats = MeshBuilder("TPL_seating")
    for i in range(4):
        x = (i - 1.5) * 0.62
        seats.box((x, 0, 0.45), (0.55, 0.55, 0.08), "M_ShellWarm")
        seats.box((x, 0.25, 0.75), (0.55, 0.06, 0.55), "M_ShellWarm")
    seats.box((0, 0, 0.2), (2.5, 0.4, 0.06), "M_Steel")
    t["seating"] = seats.finish()
    return t


# --------------------------------------------------------------------------------------
# Scene assembly
# --------------------------------------------------------------------------------------


def reset_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            block.remove(item)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def collection(name: str) -> bpy.types.Collection:
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def place(obj: bpy.types.Object, x: float, y: float, rotation_deg: float, z: float = 0.0) -> None:
    obj.location = (x, y, z)
    obj.rotation_euler = (0.0, 0.0, math.radians(rotation_deg))


def build_floors(layout: dict, coll: bpy.types.Collection) -> int:
    count = 0
    for room in layout["rooms"]:
        (x0, y0), (x1, y1) = room["bounds"]["min"], room["bounds"]["max"]
        zone = room["area_zone"]
        mat = f"M_Floor_{zone}" if zone else "M_Floor_Corridor"
        b = MeshBuilder(f"FLOOR_{room['id']}")
        inset = 0.03
        b.box(((x0 + x1) / 2, (y0 + y1) / 2, -0.04), (x1 - x0 - inset * 2, y1 - y0 - inset * 2, 0.08), mat)
        obj = bpy.data.objects.new(f"ROOM_{room['id']}", b.finish())
        obj["room_id"] = room["id"]
        obj["room_name"] = room["name"]
        if zone:
            obj["area_zone_id"] = zone
        obj["kind"] = room["kind"]
        coll.objects.link(obj)
        count += 1
    # base slab under everything
    (fx0, fy0), (fx1, fy1) = layout["floor"]["min"], layout["floor"]["max"]
    base = MeshBuilder("FLOOR_BASE")
    base.box(((fx0 + fx1) / 2, (fy0 + fy1) / 2, -0.14), (fx1 - fx0 + 0.6, fy1 - fy0 + 0.6, 0.12), "M_Graphite")
    coll.objects.link(bpy.data.objects.new("ARCH_BaseSlab", base.finish()))
    return count


def build_walls(layout: dict, coll: bpy.types.Collection) -> int:
    height = float(layout["wall_height"])
    thick = float(layout["wall_thickness"])
    solid = MeshBuilder("ARCH_Walls_Solid")
    glass = MeshBuilder("ARCH_Walls_Glass")
    count = 0
    for wall in layout["walls"]:
        (x0, y0), (x1, y1) = wall["from"], wall["to"]
        length = math.hypot(x1 - x0, y1 - y0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        horizontal = abs(y1 - y0) < 1e-6
        sx, sy = (length + thick, thick) if horizontal else (thick, length + thick)
        if wall["type"] == "glass":
            glass.box((cx, cy, height * 0.42), (sx, sy, height * 0.84), "M_Glass")
            glass.box((cx, cy, 0.04), (sx, sy, 0.08), "M_Steel")
        else:
            solid.box((cx, cy, height / 2), (sx, sy, height), "M_Wall")
            solid.box((cx, cy, height + 0.015), (sx + 0.01, sy + 0.01, 0.03), "M_WallCap")
        count += 1
    coll.objects.link(bpy.data.objects.new("ARCH_Walls_Solid", solid.finish()))
    coll.objects.link(bpy.data.objects.new("ARCH_Walls_Glass", glass.finish()))
    return count


def build_assets(layout: dict, templates: dict[str, bpy.types.Mesh], coll: bpy.types.Collection) -> list[dict]:
    mapping = []
    for asset in layout["assets"]:
        mesh = templates[asset["template"]]
        name = f"AST_{asset['id']}"
        obj = bpy.data.objects.new(name, mesh)  # shares mesh data with other instances
        x, y = asset["position"]
        place(obj, x, y, asset["rotation"])
        obj["asset_id"] = asset["id"]
        obj["asset_type"] = asset["type"]
        obj["label_height"] = float(asset["label_height"])
        obj["simulated"] = True
        coll.objects.link(obj)
        mapping.append({"asset_id": asset["id"], "node": name, "template": asset["template"], "position": [x, y]})
    return mapping


def build_decor(layout: dict, templates: dict[str, bpy.types.Mesh], coll: bpy.types.Collection) -> int:
    for i, item in enumerate(layout["decor"], start=1):
        obj = bpy.data.objects.new(f"DECOR_{item['template']}_{i:02d}", templates[item["template"]])
        x, y = item["position"]
        place(obj, x, y, item["rotation"])
        obj["decor"] = True
        coll.objects.link(obj)
    return len(layout["decor"])


def main() -> None:
    args = parse_args()
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    reset_scene()
    build_palette(layout["zones"])
    templates = build_templates()

    arch = collection("Architecture")
    assets = collection("Assets")
    decor = collection("Decor")
    rooms = build_floors(layout, arch)
    walls = build_walls(layout, arch)
    mapping = build_assets(layout, templates, assets)
    decor_count = build_decor(layout, templates, decor)

    scene = bpy.context.scene
    scene["meddefender_layout_version"] = layout["version"]
    scene["meddefender_note"] = "Synthetic hospital for a security simulation; not a real facility."

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.blend:
        blend = Path(args.blend)
        blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend.resolve()))
    bpy.ops.export_scene.gltf(
        filepath=str(out.resolve()),
        export_format="GLB",
        export_extras=True,
        export_yup=True,
        export_apply=True,
        export_cameras=False,
        export_lights=False,
        export_materials="EXPORT",
        export_texcoords=False,
        export_normals=True,
        export_animations=False,
        export_copyright="MedDefender Twin (synthetic scene)",
    )
    mapping_path = out.with_name("hospital.mapping.json")
    mapping_path.write_text(json.dumps({"layout_version": layout["version"], "assets": mapping}, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "ok",
                "rooms": rooms,
                "wall_segments": walls,
                "assets": len(mapping),
                "decor": decor_count,
                "meshes": len(bpy.data.meshes),
                "materials": len(bpy.data.materials),
                "objects": len(bpy.data.objects),
                "glb": str(out),
                "glb_bytes": out.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
