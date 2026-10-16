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
* Asset templates are built once and shared by mesh data (instances reuse geometry).
* Non-interactive furniture is merged into one multi-material mesh, and walls into one mesh
  per material, so the scene stays at a low draw-call count despite the extra detail.
* No lights, cameras or textures are exported: the viewer owns lighting and status display.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
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


MATERIALS: dict[str, bpy.types.Material] = {}


def material(
    name: str,
    color: str,
    *,
    roughness: float = 0.7,
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


def build_palette() -> None:
    # Architecture
    material("M_Floor_Clinical", "#cdd6df", roughness=0.55)
    material("M_Floor_Technical", "#a3adb9", roughness=0.7)
    material("M_Floor_Corridor", "#dfe5eb", roughness=0.5)
    material("M_Floor_Plant", "#8f979f", roughness=0.9)
    material("M_Floor_Public", "#d8d2c6", roughness=0.6)
    material("M_Wall", "#e9edf1", roughness=0.85)
    material("M_WallCap", "#b9c3ce", roughness=0.6)
    material("M_ExtWall", "#d2d9e0", roughness=0.85)
    material("M_Window", "#8fc6dc", roughness=0.05, alpha=0.32)
    material("M_Glass", "#a9d6e8", roughness=0.05, alpha=0.2)
    material("M_Steel", "#98a3af", roughness=0.35, metallic=0.85)
    material("M_DoorFrame", "#7c8896", roughness=0.4, metallic=0.6)
    material("M_Base", "#39414c", roughness=0.9)
    material("M_Asphalt", "#262c34", roughness=0.95)
    material("M_Sidewalk", "#5d6670", roughness=0.9)
    material("M_Stripe", "#e2e8f0", roughness=0.6)
    material("M_Canopy", "#e9eef3", roughness=0.5)
    # Equipment
    material("M_Shell", "#eef2f5", roughness=0.45)
    material("M_ShellWarm", "#e4ddd0", roughness=0.55)
    material("M_Graphite", "#2b323d", roughness=0.55, metallic=0.25)
    material("M_RackDoor", "#1f252e", roughness=0.5, metallic=0.4)
    material("M_Screen", "#0d1824", roughness=0.2, emission="#2bb3c9", emission_strength=0.45)
    material("M_TileBlue", "#1e40af", roughness=0.3, emission="#3b82f6", emission_strength=0.9)
    material("M_TileTeal", "#0f766e", roughness=0.3, emission="#2dd4bf", emission_strength=0.8)
    material("M_TileAmber", "#92400e", roughness=0.3, emission="#f59e0b", emission_strength=0.7)
    material("M_Lightbox", "#e6f2fb", roughness=0.3, emission="#dbeafe", emission_strength=0.9)
    material("M_AccentTeal", "#22b8c8", roughness=0.4, emission="#22b8c8", emission_strength=0.6)
    material("M_AccentAmber", "#e0a335", roughness=0.4, emission="#e0a335", emission_strength=0.5)
    material("M_AccentRed", "#e05252", roughness=0.4, emission="#e05252", emission_strength=0.5)
    material("M_AccentBlue", "#4f9fe8", roughness=0.4, emission="#4f9fe8", emission_strength=0.5)
    # Furnishings
    material("M_Mattress", "#5d7d9f", roughness=0.85)
    material("M_Linen", "#eef2f6", roughness=0.95)
    material("M_Upholstery", "#5f7389", roughness=0.9)
    material("M_Sofa", "#a3a9b1", roughness=0.95)
    material("M_Wood", "#b38f66", roughness=0.7)
    material("M_Plant", "#3f8f55", roughness=0.9)
    material("M_Pot", "#4a525c", roughness=0.8)
    material("M_CartRed", "#c43c3c", roughness=0.6)
    material("M_FireRed", "#d63a3a", roughness=0.5)
    material("M_PipeGreen", "#3d8a5b", roughness=0.6)
    material("M_PipeWhite", "#dfe5ea", roughness=0.6)
    material("M_IVBag", "#e8f6ff", roughness=0.2, alpha=0.6)
    material("M_SignRed", "#ff4d55", roughness=0.4, emission="#ff4d55", emission_strength=2.0)
    material("M_SignWhite", "#ffffff", roughness=0.4, emission="#ffffff", emission_strength=1.2)


# --------------------------------------------------------------------------------------
# Geometry helpers (bmesh with a transform stack; no operator context required)
# --------------------------------------------------------------------------------------


class MeshBuilder:
    """Accumulates primitives into one bmesh with per-part material slots."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.bm = bmesh.new()
        self.slots: list[str] = []
        self.stack: list[Matrix] = [Matrix.Identity(4)]

    # -- transforms ----------------------------------------------------------------------
    @property
    def xf(self) -> Matrix:
        return self.stack[-1]

    def push(self, matrix: Matrix) -> None:
        self.stack.append(self.xf @ matrix)

    def pop(self) -> None:
        self.stack.pop()

    # -- primitives ----------------------------------------------------------------------
    def _slot(self, material_name: str) -> int:
        if material_name not in self.slots:
            self.slots.append(material_name)
        return self.slots.index(material_name)

    def _tag(self, start: int, mat: str, smooth: bool = False) -> None:
        self.bm.faces.ensure_lookup_table()
        index = self._slot(mat)
        for face in self.bm.faces[start:]:
            face.material_index = index
            face.smooth = smooth

    def box(self, center: tuple[float, float, float], size: tuple[float, float, float], mat: str) -> MeshBuilder:
        start = len(self.bm.faces)
        m = self.xf @ Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*size, 1.0))
        bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        self._tag(start, mat)
        return self

    def cylinder(
        self, center: tuple[float, float, float], radius: float, depth: float, mat: str,
        *, axis: str = "Z", segments: int = 16, radius_top: float | None = None,
    ) -> MeshBuilder:
        start = len(self.bm.faces)
        rot = {"Z": Matrix.Identity(4), "X": Matrix.Rotation(math.pi / 2, 4, "Y"), "Y": Matrix.Rotation(math.pi / 2, 4, "X")}[axis]
        m = self.xf @ Matrix.Translation(Vector(center)) @ rot
        bmesh.ops.create_cone(
            self.bm, cap_ends=True, cap_tris=False, segments=segments, radius1=radius,
            radius2=radius if radius_top is None else radius_top, depth=depth, matrix=m,
        )
        self._tag(start, mat, smooth=True)
        return self

    def sphere(self, center: tuple[float, float, float], radius: float, mat: str, subdivisions: int = 1) -> MeshBuilder:
        start = len(self.bm.faces)
        m = self.xf @ Matrix.Translation(Vector(center))
        bmesh.ops.create_icosphere(self.bm, subdivisions=subdivisions, radius=radius, matrix=m)
        self._tag(start, mat, smooth=True)
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
                ring.append(self.bm.verts.new(self.xf @ (c + rot @ p)))
            rings.append(ring)
        for i in range(major_segments):
            a, b = rings[i], rings[(i + 1) % major_segments]
            for j in range(minor_segments):
                k = (j + 1) % minor_segments
                self.bm.faces.new((a[j], b[j], b[k], a[k]))
        self._tag(start, mat, smooth=True)
        return self

    def append_mesh(self, mesh: bpy.types.Mesh, mat_names: list[str]) -> None:
        """Merge an existing mesh (e.g. converted text) under the current transform."""
        tmp = bmesh.new()
        tmp.from_mesh(mesh)
        bmesh.ops.transform(tmp, matrix=self.xf, verts=tmp.verts[:])
        vmap = {v: self.bm.verts.new(v.co) for v in tmp.verts}
        for f in tmp.faces:
            nf = self.bm.faces.new([vmap[v] for v in f.verts])
            nf.material_index = self._slot(mat_names[min(f.material_index, len(mat_names) - 1)])
        tmp.free()
        self.bm.faces.ensure_lookup_table()

    def finish(self) -> bpy.types.Mesh:
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        mesh = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for slot in self.slots:
            mesh.materials.append(MATERIALS[slot])
        return mesh


def at(x: float, y: float, rotation_deg: float = 0.0, z: float = 0.0) -> Matrix:
    return Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(rotation_deg), 4, "Z")


# --------------------------------------------------------------------------------------
# Templates (local coordinates: origin at floor centre of footprint, front faces -Y)
# --------------------------------------------------------------------------------------

Template = Callable[[MeshBuilder, dict], None]


def screen(b: MeshBuilder, center: tuple[float, float, float], w: float, h: float, depth: float = 0.05) -> None:
    x, y, z = center
    b.box((x, y, z), (w + 0.04, depth, h + 0.04), "M_Graphite")
    b.box((x, y - depth / 2 - 0.004, z), (w, 0.008, h), "M_Screen")


def t_patient_monitor(b: MeshBuilder, _: dict) -> None:
    b.cylinder((0, 0, 0.025), 0.27, 0.05, "M_Steel", segments=20)
    for a in range(5):
        ang = a * 2 * math.pi / 5
        b.box((0.18 * math.cos(ang), 0.18 * math.sin(ang), 0.04), (0.06, 0.06, 0.05), "M_Graphite")
    b.cylinder((0, 0, 0.66), 0.022, 1.22, "M_Steel", segments=10)
    b.box((0, 0, 1.34), (0.46, 0.11, 0.36), "M_Shell")
    b.box((0, -0.058, 1.35), (0.38, 0.008, 0.26), "M_Screen")
    b.box((0, 0, 1.55), (0.2, 0.05, 0.03), "M_Graphite")
    b.box((0.18, -0.06, 1.49), (0.04, 0.008, 0.02), "M_AccentTeal")


def t_infusion_pump(b: MeshBuilder, _: dict) -> None:
    b.cylinder((0, 0, 0.03), 0.28, 0.06, "M_Steel", segments=20)
    b.cylinder((0, 0, 0.95), 0.018, 1.85, "M_Steel", segments=10)
    for z in (0.95, 1.27):
        b.box((0, -0.03, z), (0.24, 0.17, 0.28), "M_Shell")
        b.box((0, -0.118, z + 0.05), (0.16, 0.008, 0.09), "M_Screen")
        b.box((0.08, -0.118, z - 0.08), (0.03, 0.008, 0.03), "M_AccentTeal")
    b.box((0, 0, 1.86), (0.42, 0.025, 0.025), "M_Steel")
    for x in (-0.15, 0.15):
        b.box((x, 0, 1.72), (0.12, 0.04, 0.22), "M_IVBag")


def t_rack(b: MeshBuilder, p: dict) -> None:
    accent = p.get("accent", "M_AccentBlue")
    bands = int(p.get("bands", 3))
    b.box((0, 0, 1.0), (0.6, 0.8, 2.0), "M_Graphite")
    b.box((0, -0.402, 1.0), (0.54, 0.01, 1.9), "M_RackDoor")
    for i in range(12):
        b.box((0, -0.41, 0.25 + i * 0.13), (0.44, 0.006, 0.012), "M_Graphite")
    for i in range(bands):
        z = 1.62 - i * 0.24
        b.box((0, -0.413, z), (0.48, 0.008, 0.12), "M_Steel")
        b.box((0.19, -0.42, z), (0.05, 0.006, 0.025), accent)
    b.box((0, -0.418, 1.9), (0.5, 0.006, 0.03), accent)
    b.box((0, 0, 2.02), (0.56, 0.7, 0.04), "M_Steel")


def t_rack_blank(b: MeshBuilder, _: dict) -> None:
    t_rack(b, {"accent": "M_Graphite", "bands": 0})


def t_chair(b: MeshBuilder, _: dict) -> None:
    b.cylinder((0, 0, 0.03), 0.28, 0.04, "M_Graphite", segments=10)
    b.cylinder((0, 0, 0.25), 0.03, 0.4, "M_Steel", segments=8)
    b.box((0, 0, 0.47), (0.5, 0.48, 0.08), "M_Upholstery")
    b.box((0, 0.22, 0.82), (0.46, 0.06, 0.6), "M_Upholstery")


def t_workstation(b: MeshBuilder, p: dict) -> None:
    screens = int(p.get("screens", 1))
    with_chair = p.get("chair", True)
    width = 1.2 + 0.6 * (screens - 1)
    b.box((0, 0, 0.73), (width, 0.75, 0.04), "M_ShellWarm")
    for x in (-width / 2 + 0.06, width / 2 - 0.06):
        b.box((x, 0, 0.36), (0.05, 0.68, 0.72), "M_Graphite")
    b.box((0, 0.3, 0.45), (width - 0.2, 0.03, 0.5), "M_ShellWarm")
    offsets = [0.0] if screens == 1 else [(i - (screens - 1) / 2) * 0.6 for i in range(screens)]
    for x in offsets:
        b.box((x, 0.14, 0.78), (0.2, 0.14, 0.02), "M_Graphite")
        b.box((x, 0.16, 0.89), (0.04, 0.04, 0.2), "M_Graphite")
        screen(b, (x, 0.12, 1.09), 0.54, 0.32, 0.035)
    b.box((0, -0.16, 0.76), (0.46, 0.15, 0.02), "M_Graphite")
    b.box((0.36, -0.16, 0.76), (0.07, 0.11, 0.02), "M_Graphite")
    if with_chair:
        b.push(at(0, -0.75, 180))
        t_chair(b, {})
        b.pop()


def t_wall_sensor(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0.02, 1.5), (0.16, 0.02, 0.16), "M_Graphite")
    b.box((0, -0.01, 1.5), (0.12, 0.05, 0.12), "M_Shell")
    b.box((0, -0.037, 1.53), (0.06, 0.005, 0.03), "M_Screen")
    b.box((0.04, -0.038, 1.47), (0.015, 0.005, 0.015), "M_AccentAmber")


def t_ct_scanner(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.32), (2.1, 0.95, 0.64), "M_Shell")
    b.box((0, 0, 0.66), (2.2, 1.0, 0.06), "M_Graphite")
    b.torus((0, 0, 1.3), 0.86, 0.34, "M_Shell", axis="Y", major_segments=48, minor_segments=16)
    b.torus((0, -0.32, 1.3), 0.55, 0.03, "M_AccentTeal", axis="Y", major_segments=40, minor_segments=6)
    b.box((0.75, -0.5, 1.95), (0.32, 0.02, 0.18), "M_Screen")


def t_wall_panel(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 1.25), (0.64, 0.22, 0.86), "M_Shell")
    b.box((0, -0.115, 1.42), (0.3, 0.01, 0.16), "M_Screen")
    b.box((-0.2, -0.116, 1.05), (0.05, 0.01, 0.05), "M_AccentAmber")
    b.box((0, -0.112, 1.25), (0.004, 0.006, 0.8), "M_Graphite")


def t_control_cabinet(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.85), (0.9, 0.5, 1.7), "M_Shell")
    b.box((0, -0.255, 1.3), (0.34, 0.01, 0.22), "M_Screen")
    b.box((0.32, -0.256, 0.95), (0.06, 0.01, 0.06), "M_AccentAmber")
    b.box((0, -0.253, 0.85), (0.004, 0.006, 1.6), "M_Graphite")
    b.box((0, 0, 0.04), (0.92, 0.52, 0.08), "M_Graphite")


# ---- furnishings ------------------------------------------------------------------------


def t_bed(b: MeshBuilder, _: dict) -> None:
    for x in (-0.42, 0.42):
        for y in (-0.95, 0.95):
            b.cylinder((x, y, 0.07), 0.06, 0.05, "M_Graphite", axis="X", segments=10)
            b.cylinder((x, y, 0.2), 0.025, 0.24, "M_Steel", segments=8)
    b.box((0, 0, 0.36), (0.98, 2.15, 0.1), "M_Steel")
    b.box((0, -0.05, 0.5), (0.92, 1.95, 0.18), "M_Mattress")
    b.box((0, 0.72, 0.64), (0.62, 0.36, 0.1), "M_Linen")
    b.box((0, -0.35, 0.6), (0.9, 1.05, 0.03), "M_Linen")
    b.box((0, 1.07, 0.78), (0.98, 0.06, 0.62), "M_Shell")
    b.box((0, -1.07, 0.6), (0.98, 0.06, 0.4), "M_Shell")
    for x in (-0.5, 0.5):
        b.box((x, 0.45, 0.74), (0.03, 0.85, 0.22), "M_Shell")
    b.box((0.52, -0.2, 0.62), (0.02, 0.25, 0.12), "M_Graphite")


def t_bedside_cabinet(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.4), (0.46, 0.46, 0.8), "M_Shell")
    for z in (0.25, 0.5):
        b.box((0, -0.232, z), (0.4, 0.006, 0.006), "M_Graphite")
    b.box((0, -0.235, 0.66), (0.12, 0.01, 0.02), "M_Steel")
    b.box((0, 0, 0.81), (0.5, 0.5, 0.03), "M_ShellWarm")


def t_overbed_table(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0.3, 0.04), (0.08, 0.7, 0.06), "M_Graphite")
    b.box((0.38, 0.3, 0.04), (0.08, 0.7, 0.06), "M_Graphite")
    b.box((0.19, 0.3, 0.04), (0.46, 0.08, 0.06), "M_Graphite")
    b.cylinder((0.38, 0.3, 0.48), 0.03, 0.86, "M_Steel", segments=8)
    b.box((0, 0.3, 0.92), (0.95, 0.42, 0.03), "M_ShellWarm")


def t_visitor_chair(b: MeshBuilder, _: dict) -> None:
    for x in (-0.24, 0.24):
        for y in (-0.22, 0.22):
            b.box((x, y, 0.2), (0.04, 0.04, 0.4), "M_Steel")
    b.box((0, 0, 0.44), (0.56, 0.52, 0.09), "M_Upholstery")
    b.box((0, 0.24, 0.78), (0.56, 0.08, 0.6), "M_Upholstery")
    for x in (-0.29, 0.29):
        b.box((x, 0, 0.62), (0.05, 0.48, 0.05), "M_Steel")


def t_wall_tv(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0.02, 1.75), (1.06, 0.04, 0.64), "M_Graphite")
    b.box((0, -0.002, 1.75), (1.0, 0.006, 0.58), "M_TileBlue")


def t_tall_cabinet(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 1.0), (0.9, 0.5, 2.0), "M_Shell")
    b.box((0, -0.252, 1.0), (0.006, 0.006, 1.9), "M_Graphite")
    for x in (-0.06, 0.06):
        b.box((x, -0.26, 1.05), (0.02, 0.015, 0.22), "M_Steel")


def t_plant(b: MeshBuilder, _: dict) -> None:
    b.cylinder((0, 0, 0.22), 0.2, 0.44, "M_Pot", segments=14, radius_top=0.24)
    b.cylinder((0, 0, 0.45), 0.21, 0.02, "M_Base", segments=14)
    for (x, y, z, r) in ((0, 0, 0.85, 0.3), (0.13, 0.06, 1.08, 0.22), (-0.12, -0.05, 1.12, 0.2), (0.02, -0.12, 1.3, 0.17), (-0.05, 0.1, 1.38, 0.15)):
        b.sphere((x, y, z), r, "M_Plant", subdivisions=1)


def t_nurse_desk(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.53), (3.0, 0.75, 1.06), "M_ShellWarm")
    b.box((0, -0.2, 1.08), (3.0, 0.4, 0.04), "M_Wood")
    b.box((0, 0.2, 0.74), (2.9, 0.5, 0.03), "M_ShellWarm")
    for x in (-0.8, 0.8):
        screen(b, (x, 0.3, 1.0), 0.5, 0.3, 0.035)
    b.box((0, -0.38, 0.5), (2.9, 0.01, 0.12), "M_AccentTeal")


def t_nurse_desk_return(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.375), (2.0, 0.6, 0.75), "M_ShellWarm")
    b.box((0, 0, 0.76), (2.0, 0.62, 0.03), "M_Wood")


def t_crash_cart(b: MeshBuilder, _: dict) -> None:
    for x in (-0.25, 0.25):
        for y in (-0.2, 0.2):
            b.cylinder((x, y, 0.05), 0.045, 0.04, "M_Graphite", axis="X", segments=8)
    b.box((0, 0, 0.55), (0.62, 0.5, 0.9), "M_CartRed")
    for z in (0.3, 0.5, 0.7, 0.85):
        b.box((0, -0.252, z), (0.56, 0.006, 0.01), "M_Graphite")
    b.box((0, 0, 1.02), (0.66, 0.54, 0.04), "M_Graphite")
    b.box((0.1, 0.05, 1.15), (0.3, 0.25, 0.22), "M_Shell")


def t_ups_cabinet(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.9), (0.6, 0.9, 1.8), "M_Graphite")
    b.box((0, -0.452, 1.4), (0.22, 0.008, 0.12), "M_Screen")
    b.box((0, -0.452, 0.8), (0.5, 0.006, 0.9), "M_RackDoor")


def t_handrail(b: MeshBuilder, p: dict) -> None:
    length = float(p.get("length", 4.0))
    b.cylinder((0, 0, 0.9), 0.025, length, "M_Steel", axis="X", segments=8)
    n = max(2, int(length // 2) + 1)
    for i in range(n):
        x = -length / 2 + i * (length / (n - 1))
        b.box((x, 0.04, 0.88), (0.03, 0.08, 0.06), "M_Steel")


def t_ct_table(b: MeshBuilder, _: dict) -> None:
    b.box((0, -0.2, 0.42), (0.5, 0.7, 0.84), "M_Shell")
    b.box((0, -0.2, 0.06), (0.62, 0.9, 0.12), "M_Graphite")
    b.box((0, 0.55, 0.92), (0.52, 2.4, 0.09), "M_Linen")
    b.box((0, 1.5, 0.97), (0.3, 0.3, 0.05), "M_Linen")


def t_injector(b: MeshBuilder, _: dict) -> None:
    b.cylinder((0, 0, 0.03), 0.25, 0.06, "M_Steel", segments=12)
    b.cylinder((0, 0, 0.6), 0.025, 1.1, "M_Steel", segments=8)
    b.box((0, 0, 1.2), (0.28, 0.2, 0.18), "M_Shell")
    b.cylinder((0.08, -0.1, 1.25), 0.04, 0.24, "M_IVBag", axis="Y", segments=10)


def t_lightbox(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0.02, 1.6), (1.3, 0.05, 0.85), "M_Graphite")
    b.box((0, -0.006, 1.6), (1.22, 0.008, 0.77), "M_Lightbox")


def t_reception_desk(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.55), (2.6, 0.7, 1.1), "M_ShellWarm")
    b.box((0, -0.36, 0.55), (2.5, 0.02, 0.9), "M_Wood")
    b.box((0, 0.1, 1.12), (2.7, 0.55, 0.04), "M_Shell")
    screen(b, (0.5, 0.25, 1.0), 0.48, 0.28, 0.035)


def t_sofa(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.22), (2.1, 0.85, 0.3), "M_Sofa")
    b.box((0, 0.03, 0.43), (1.8, 0.75, 0.12), "M_Sofa")
    b.box((0, 0.36, 0.7), (2.1, 0.2, 0.62), "M_Sofa")
    for x in (-0.98, 0.98):
        b.box((x, 0, 0.5), (0.16, 0.85, 0.5), "M_Sofa")


def t_coffee_table(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.4), (1.1, 0.55, 0.04), "M_Wood")
    for x in (-0.48, 0.48):
        for y in (-0.22, 0.22):
            b.box((x, y, 0.2), (0.04, 0.04, 0.38), "M_Steel")


def t_seating(b: MeshBuilder, _: dict) -> None:
    for i in range(4):
        x = (i - 1.5) * 0.62
        b.box((x, 0, 0.45), (0.55, 0.55, 0.08), "M_Upholstery")
        b.box((x, 0.25, 0.75), (0.55, 0.06, 0.55), "M_Upholstery")
    b.box((0, 0, 0.2), (2.5, 0.4, 0.06), "M_Steel")
    for x in (-1.1, 1.1):
        b.box((x, 0, 0.1), (0.06, 0.4, 0.2), "M_Steel")


def t_bench(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.44), (1.8, 0.45, 0.06), "M_Wood")
    for x in (-0.75, 0.75):
        b.box((x, 0, 0.22), (0.06, 0.4, 0.44), "M_Steel")


def t_crac_unit(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 1.0), (1.8, 0.9, 2.0), "M_Shell")
    for i in range(6):
        b.box((-0.6 + i * 0.24, -0.452, 1.55), (0.18, 0.006, 0.5), "M_Graphite")
    b.box((0.6, -0.452, 0.9), (0.24, 0.008, 0.14), "M_Screen")


def t_fire_cylinders(b: MeshBuilder, _: dict) -> None:
    for x in (-0.35, 0.0, 0.35):
        b.cylinder((x, 0, 0.7), 0.15, 1.4, "M_FireRed", segments=14)
        b.cylinder((x, 0, 1.45), 0.05, 0.12, "M_Steel", segments=8)


def t_video_wall(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0.03, 1.65), (5.2, 0.06, 1.75), "M_Graphite")
    tiles = ["M_TileBlue", "M_TileTeal", "M_TileBlue", "M_TileAmber", "M_TileBlue", "M_TileTeal"]
    for i, mat in enumerate(tiles):
        col, row = i % 3, i // 3
        b.box((-1.68 + col * 1.68, -0.004, 2.08 - row * 0.85), (1.62, 0.008, 0.8), mat)


def t_desk_dual(b: MeshBuilder, _: dict) -> None:
    t_workstation(b, {"screens": 2, "chair": False})


def t_chiller(b: MeshBuilder, _: dict) -> None:
    for y in (-0.8, 0.8):
        b.box((0, y, 0.25), (1.1, 0.25, 0.5), "M_Graphite")
    b.cylinder((0, 0, 0.95), 0.62, 2.6, "M_PipeWhite", axis="Y", segments=24)
    b.box((0.75, 0, 0.6), (0.35, 0.5, 0.9), "M_Shell")
    b.box((0.93, 0, 0.75), (0.006, 0.2, 0.12), "M_Screen")


def t_pump_unit(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 0.1), (0.9, 0.5, 0.2), "M_Graphite")
    b.cylinder((-0.1, 0, 0.42), 0.18, 0.55, "M_PipeGreen", axis="X", segments=14)
    b.cylinder((0.3, 0, 0.42), 0.14, 0.25, "M_Steel", axis="X", segments=12)


def t_pipe_run(b: MeshBuilder, p: dict) -> None:
    length = float(p.get("length", 10.0))
    b.cylinder((0, 0, 2.05), 0.1, length, "M_PipeGreen", axis="X", segments=12)
    b.cylinder((0, 0.25, 1.75), 0.08, length, "M_PipeWhite", axis="X", segments=12)
    n = max(2, int(length // 3) + 1)
    for i in range(n):
        x = -length / 2 + i * (length / (n - 1))
        b.box((x, 0.12, 1.4), (0.06, 0.06, 1.6), "M_Steel")
        b.box((x, 0.12, 2.18), (0.06, 0.4, 0.04), "M_Steel")


def t_electrical_panel(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 1.25), (0.85, 0.25, 1.3), "M_Steel")
    b.box((0, -0.127, 1.25), (0.004, 0.006, 1.2), "M_Graphite")
    b.box((0.3, -0.13, 1.6), (0.08, 0.006, 0.05), "M_AccentAmber")


def t_ahu(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 1.3), (6.0, 3.0, 2.6), "M_Steel")
    b.box((-3.02, 0, 1.2), (0.04, 2.4, 1.8), "M_Graphite")
    for x in (-1.5, 0.0, 1.5):
        b.cylinder((x, 0, 2.66), 0.55, 0.12, "M_Graphite", segments=20)
        b.cylinder((x, 0, 2.73), 0.12, 0.04, "M_Steel", segments=12)
    for x in (-2.0, -0.5, 1.0, 2.5):
        b.box((x, -1.502, 1.3), (0.006, 0.006, 2.4), "M_Graphite")


def t_duct(b: MeshBuilder, _: dict) -> None:
    b.box((0, 0, 2.2), (8.0, 0.6, 0.5), "M_Steel")
    for x in (-3.5, -1.0, 1.5, 3.5):
        b.box((x, 0, 2.2), (0.08, 0.64, 0.54), "M_DoorFrame")


TEMPLATES: dict[str, tuple[Template, dict]] = {
    # assets (shared meshes)
    "patient_monitor": (t_patient_monitor, {}),
    "infusion_pump": (t_infusion_pump, {}),
    "gateway_rack": (t_rack, {"accent": "M_AccentTeal", "bands": 2}),
    "switch_rack": (t_rack, {"accent": "M_AccentBlue", "bands": 4}),
    "firewall_rack": (t_rack, {"accent": "M_AccentRed", "bands": 2}),
    "server_rack": (t_rack, {"accent": "M_AccentBlue", "bands": 5}),
    "sensor_rack": (t_rack, {"accent": "M_AccentAmber", "bands": 2}),
    "workstation": (t_workstation, {"screens": 1}),
    "workstation_dual": (t_workstation, {"screens": 2}),
    "workstation_triple": (t_workstation, {"screens": 3}),
    "wall_sensor": (t_wall_sensor, {}),
    "ct_scanner": (t_ct_scanner, {}),
    "wall_panel": (t_wall_panel, {}),
    "control_cabinet": (t_control_cabinet, {}),
    # furnishings (merged)
    "rack_blank": (t_rack_blank, {}),
    "bed": (t_bed, {}),
    "bedside_cabinet": (t_bedside_cabinet, {}),
    "overbed_table": (t_overbed_table, {}),
    "visitor_chair": (t_visitor_chair, {}),
    "wall_tv": (t_wall_tv, {}),
    "tall_cabinet": (t_tall_cabinet, {}),
    "plant": (t_plant, {}),
    "nurse_desk": (t_nurse_desk, {}),
    "nurse_desk_return": (t_nurse_desk_return, {}),
    "office_chair": (t_chair, {}),
    "crash_cart": (t_crash_cart, {}),
    "ups_cabinet": (t_ups_cabinet, {}),
    "handrail": (t_handrail, {}),
    "ct_table": (t_ct_table, {}),
    "injector": (t_injector, {}),
    "lightbox": (t_lightbox, {}),
    "reception_desk": (t_reception_desk, {}),
    "sofa": (t_sofa, {}),
    "coffee_table": (t_coffee_table, {}),
    "seating": (t_seating, {}),
    "bench": (t_bench, {}),
    "crac_unit": (t_crac_unit, {}),
    "fire_cylinders": (t_fire_cylinders, {}),
    "video_wall": (t_video_wall, {}),
    "desk_dual": (t_desk_dual, {}),
    "chiller": (t_chiller, {}),
    "pump_unit": (t_pump_unit, {}),
    "pipe_run": (t_pipe_run, {}),
    "electrical_panel": (t_electrical_panel, {}),
    "ahu": (t_ahu, {}),
    "duct": (t_duct, {}),
}


# --------------------------------------------------------------------------------------
# Scene assembly
# --------------------------------------------------------------------------------------


def reset_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights, bpy.data.curves):
        for item in list(block):
            block.remove(item)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def collection(name: str) -> bpy.types.Collection:
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


FLOOR_BY_KIND = {"clinical": "M_Floor_Clinical", "technical": "M_Floor_Technical", "corridor": "M_Floor_Corridor", "public": "M_Floor_Public"}


def build_floors(layout: dict, coll: bpy.types.Collection) -> int:
    for room in layout["rooms"]:
        (x0, y0), (x1, y1) = room["bounds"]["min"], room["bounds"]["max"]
        mat = "M_Floor_Plant" if room["id"] == "BMS-PLANT-ROOM" else FLOOR_BY_KIND.get(room["kind"], "M_Floor_Corridor")
        b = MeshBuilder(f"FLOOR_{room['id']}")
        b.box(((x0 + x1) / 2, (y0 + y1) / 2, -0.04), (x1 - x0 - 0.04, y1 - y0 - 0.04, 0.08), mat)
        obj = bpy.data.objects.new(f"ROOM_{room['id']}", b.finish())
        obj["room_id"] = room["id"]
        obj["room_name"] = room["name"]
        if room["area_zone"]:
            obj["area_zone_id"] = room["area_zone"]
        obj["kind"] = room["kind"]
        coll.objects.link(obj)
    (fx0, fy0), (fx1, fy1) = layout["floor"]["min"], layout["floor"]["max"]
    site = MeshBuilder("ARCH_Site")
    site.box(((fx0 + fx1) / 2, (fy0 + fy1) / 2, -0.14), (fx1 - fx0 + 0.6, fy1 - fy0 + 0.6, 0.12), "M_Base")
    site.box(((fx0 + fx1) / 2, (fy0 + fy1) / 2, -0.23), (fx1 - fx0 + 5, fy1 - fy0 + 5, 0.06), "M_Sidewalk")
    site.box(((fx0 + fx1) / 2 + 3, (fy0 + fy1) / 2 + 2, -0.27), (fx1 - fx0 + 22, fy1 - fy0 + 18, 0.04), "M_Asphalt")
    for i in range(7):
        site.box((fx1 + 6.5, fy0 + 2.5 + i * 2.6, -0.24), (4.6, 0.1, 0.01), "M_Stripe")
    for i in range(10):
        site.box((fx0 + 6 + i * 5, fy1 + 5.0, -0.24), (2.4, 0.12, 0.01), "M_Stripe")
    coll.objects.link(bpy.data.objects.new("ARCH_Site", site.finish()))
    return len(layout["rooms"])


def is_exterior(wall: dict, layout: dict) -> bool:
    (fx0, fy0), (fx1, fy1) = layout["floor"]["min"], layout["floor"]["max"]
    (x0, y0), (x1, y1) = wall["from"], wall["to"]
    return (y0 == y1 and y0 in (fy0, fy1)) or (x0 == x1 and x0 in (fx0, fx1))


def wall_box(b: MeshBuilder, wall: dict, thick: float, z0: float, z1: float, mat: str, extend: bool = True) -> None:
    (x0, y0), (x1, y1) = wall["from"], wall["to"]
    length = math.hypot(x1 - x0, y1 - y0) + (thick if extend else 0.0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    horizontal = abs(y1 - y0) < 1e-6
    sx, sy = (length, thick) if horizontal else (thick, length)
    b.box((cx, cy, (z0 + z1) / 2), (sx, sy, z1 - z0), mat)


def build_walls(layout: dict, coll: bpy.types.Collection) -> dict[str, int]:
    height = float(layout["wall_height"])
    ext_height = float(layout.get("exterior_wall_height", height))
    thick = float(layout["wall_thickness"])
    solid = MeshBuilder("ARCH_Walls_Solid")
    glass = MeshBuilder("ARCH_Walls_Glass")
    sill, head = 0.9, 2.25
    stats = {"interior": 0, "exterior": 0, "glass": 0, "doorways": 0}
    for wall in layout["walls"]:
        if is_exterior(wall, layout):
            stats["exterior"] += 1
            wall_box(solid, wall, thick + 0.08, 0.0, sill, "M_ExtWall")
            wall_box(solid, wall, thick + 0.08, head, ext_height, "M_ExtWall")
            wall_box(solid, wall, thick + 0.12, ext_height, ext_height + 0.05, "M_WallCap")
            wall_box(glass, wall, 0.04, sill, head, "M_Window", extend=False)
            (x0, y0), (x1, y1) = wall["from"], wall["to"]
            length = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(length // 2.4))
            for i in range(n + 1):
                t = i / n
                mx, my = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                horizontal = abs(y1 - y0) < 1e-6
                solid.box((mx, my, (sill + head) / 2), (0.08, thick + 0.1, head - sill) if horizontal else (thick + 0.1, 0.08, head - sill), "M_DoorFrame")
        elif wall["type"] == "glass":
            stats["glass"] += 1
            wall_box(glass, wall, 0.05, 0.08, height - 0.06, "M_Glass")
            wall_box(solid, wall, 0.1, 0.0, 0.08, "M_Steel")
            wall_box(solid, wall, 0.1, height - 0.06, height, "M_Steel")
        else:
            stats["interior"] += 1
            wall_box(solid, wall, thick, 0.0, height, "M_Wall")
            wall_box(solid, wall, thick + 0.01, height, height + 0.03, "M_WallCap")

    # Doorways: gaps between collinear wall segments get a lintel and frame posts.
    lines: dict[tuple[str, float], list[tuple[float, float, bool]]] = {}
    for wall in layout["walls"]:
        (x0, y0), (x1, y1) = wall["from"], wall["to"]
        ext = is_exterior(wall, layout)
        if abs(y1 - y0) < 1e-6:
            lines.setdefault(("h", y0), []).append((min(x0, x1), max(x0, x1), ext))
        else:
            lines.setdefault(("v", x0), []).append((min(y0, y1), max(y0, y1), ext))
    for (orient, coord), spans in lines.items():
        spans.sort()
        for (a0, a1, ext_a), (b0, _b1, _ext_b) in zip(spans, spans[1:], strict=False):
            gap = b0 - a1
            if not 0.6 < gap <= 6.5:
                continue
            stats["doorways"] += 1
            mid = (a1 + b0) / 2
            top = ext_height if ext_a else height
            lintel_bottom = 2.25 if ext_a else 2.1
            if orient == "h":
                solid.box((mid, coord, (lintel_bottom + top) / 2), (gap, thick + (0.08 if ext_a else 0), top - lintel_bottom), "M_ExtWall" if ext_a else "M_Wall")
                for x in (a1 + 0.03, b0 - 0.03):
                    solid.box((x, coord, lintel_bottom / 2), (0.06, thick + 0.04, lintel_bottom), "M_DoorFrame")
            else:
                solid.box((coord, mid, (lintel_bottom + top) / 2), (thick + (0.08 if ext_a else 0), gap, top - lintel_bottom), "M_ExtWall" if ext_a else "M_Wall")
                for y in (a1 + 0.03, b0 - 0.03):
                    solid.box((coord, y, lintel_bottom / 2), (thick + 0.04, 0.06, lintel_bottom), "M_DoorFrame")
    coll.objects.link(bpy.data.objects.new("ARCH_Walls_Solid", solid.finish()))
    coll.objects.link(bpy.data.objects.new("ARCH_Walls_Glass", glass.finish()))
    return stats


def text_mesh(text: str, size: float) -> bpy.types.Mesh:
    curve = bpy.data.curves.new(f"TXT_{text[:12]}", type="FONT")
    curve.body = text
    curve.size = size
    curve.extrude = 0.02
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    obj = bpy.data.objects.new("TMP_text", curve)
    bpy.context.scene.collection.objects.link(obj)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.curves.remove(curve)
    return mesh


def build_entrances(layout: dict, decor: MeshBuilder) -> int:
    facing_rot = {"north": 180.0, "south": 0.0, "east": 90.0, "west": 270.0}
    for entrance in layout.get("entrances", []):
        cx, cy = entrance["center"]
        width = float(entrance["width"])
        rot = facing_rot[entrance["facing"]]
        # Local frame: entrance opening along X, outside is -Y (front faces -Y).
        decor.push(at(cx, cy, rot))
        depth = 3.2
        decor.box((0, -depth / 2, 3.05), (width + 2.4, depth, 0.18), "M_Canopy")
        decor.box((0, -depth + 0.05, 2.85), (width + 2.4, 0.1, 0.25), "M_DoorFrame")
        for x in (-(width + 2.2) / 2, (width + 2.2) / 2):
            decor.cylinder((x, -depth + 0.25, 1.48), 0.08, 2.96, "M_Steel", segments=12)
        decor.box((0, -depth / 2, -0.2), (width + 2.4, depth, 0.06), "M_Sidewalk")
        mat = "M_SignRed" if entrance["color"].lower().startswith("#e5") else "M_SignWhite"
        mesh = text_mesh(entrance["label"], 0.42 if len(entrance["label"]) < 12 else 0.3)
        # Text is built in the XY plane facing +Z; +90 deg about X makes it face -Y (outside),
        # upright and reading left-to-right for someone approaching the entrance.
        decor.push(Matrix.Translation((0, -depth - 0.03, 2.86)) @ Matrix.Rotation(math.radians(90), 4, "X"))
        decor.append_mesh(mesh, [mat])
        decor.pop()
        bpy.data.meshes.remove(mesh)
        decor.pop()
    return len(layout.get("entrances", []))


def build_assets(layout: dict, coll: bpy.types.Collection) -> list[dict]:
    meshes: dict[str, bpy.types.Mesh] = {}
    mapping = []
    for asset in layout["assets"]:
        name_t = asset["template"]
        if name_t not in meshes:
            fn, params = TEMPLATES[name_t]
            b = MeshBuilder(f"TPL_{name_t}")
            fn(b, params)
            meshes[name_t] = b.finish()
        obj = bpy.data.objects.new(f"AST_{asset['id']}", meshes[name_t])  # shared mesh data
        x, y = asset["position"]
        obj.location = (x, y, 0.0)
        obj.rotation_euler = (0.0, 0.0, math.radians(asset["rotation"]))
        obj["asset_id"] = asset["id"]
        obj["asset_type"] = asset["type"]
        obj["label_height"] = float(asset["label_height"])
        obj["simulated"] = True
        coll.objects.link(obj)
        mapping.append({"asset_id": asset["id"], "node": obj.name, "template": name_t, "position": [x, y]})
    return mapping


def build_decor(layout: dict, coll: bpy.types.Collection) -> tuple[int, int]:
    decor = MeshBuilder("DECOR_Merged")
    for item in layout["decor"]:
        fn, params = TEMPLATES[item["template"]]
        x, y = item["position"]
        decor.push(at(x, y, item.get("rotation", 0)))
        fn(decor, {**params, **{k: v for k, v in item.items() if k not in ("template", "position", "rotation")}})
        decor.pop()
    entrances = build_entrances(layout, decor)
    obj = bpy.data.objects.new("DECOR_Merged", decor.finish())
    obj["decor"] = True
    coll.objects.link(obj)
    return len(layout["decor"]), entrances


def main() -> None:
    args = parse_args()
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    reset_scene()
    build_palette()
    arch = collection("Architecture")
    assets = collection("Assets")
    decor_coll = collection("Decor")
    rooms = build_floors(layout, arch)
    walls = build_walls(layout, arch)
    mapping = build_assets(layout, assets)
    decor_count, entrances = build_decor(layout, decor_coll)

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
    triangles = sum(sum(len(p.vertices) - 2 for p in m.polygons) for m in bpy.data.meshes)
    print(
        json.dumps(
            {
                "result": "ok",
                "rooms": rooms,
                "walls": walls,
                "assets": len(mapping),
                "decor_items": decor_count,
                "entrances": entrances,
                "meshes": len(bpy.data.meshes),
                "materials": len(bpy.data.materials),
                "objects": len(bpy.data.objects),
                "triangles_unique_meshes": triangles,
                "glb": str(out),
                "glb_bytes": out.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
