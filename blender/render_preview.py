"""Render a quick preview of the built hospital (for documentation and visual checks).

    blender --background blender/out/hospital.blend --python blender/render_preview.py -- \
        --out docs/images/blender-preview.png
"""

from __future__ import annotations

import argparse
import math
import sys

import bpy
from mathutils import Vector


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    args = parser.parse_args(argv)

    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = 32
    cam = bpy.data.objects.new("PreviewCam", cam_data)
    scene.collection.objects.link(cam)
    target = Vector((28.0, 18.0, 0.0))
    cam.location = Vector((28.0, -22.0, 38.0))
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    sun_data = bpy.data.lights.new("PreviewSun", type="SUN")
    sun_data.energy = 3.0
    sun = bpy.data.objects.new("PreviewSun", sun_data)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    scene.collection.objects.link(sun)

    world = scene.world or bpy.data.worlds.new("PreviewWorld")
    scene.world = world
    world.color = (0.02, 0.03, 0.05)

    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_shadows = True
    shading.show_cavity = True
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)
    print(f"preview written to {args.out}")


if __name__ == "__main__":
    main()
