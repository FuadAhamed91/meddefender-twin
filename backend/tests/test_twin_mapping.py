"""The exported GLB and the backend inventory must agree on stable asset identity.

Parses the committed ``frontend/public/models/hospital.glb`` directly (GLB header + JSON
chunk, no 3D libraries) and checks that every physical asset's ``twin_node`` exists, carries
``extras.asset_id`` equal to the backend ID, and that the scene contains no asset nodes the
backend does not know about.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Asset

GLB = Path(__file__).resolve().parents[2] / "frontend" / "public" / "models" / "hospital.glb"


def read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2 and length == len(data)
    chunk_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    assert chunk_type == b"JSON"
    return json.loads(data[20 : 20 + chunk_length])


@pytest.mark.skipif(not GLB.exists(), reason="hospital.glb has not been built")
def test_every_backend_asset_maps_to_exactly_one_glb_node(services):
    gltf = read_glb_json(GLB)
    nodes = {n.get("name"): n for n in gltf["nodes"]}
    tagged = {n["extras"]["asset_id"]: n for n in gltf["nodes"] if "asset_id" in n.get("extras", {})}
    with services.session_factory() as session:
        physical = session.scalars(
            select(Asset).where(Asset.is_logical.is_(False), Asset.twin_node.is_not(None))
        ).all()
    assert len(physical) == 21
    for asset in physical:
        node = nodes.get(asset.twin_node)
        assert node is not None, f"{asset.id}: node {asset.twin_node} missing from GLB"
        assert node["extras"]["asset_id"] == asset.id
    assert set(tagged) == {a.id for a in physical}, "GLB contains asset nodes unknown to the backend"


@pytest.mark.skipif(not GLB.exists(), reason="hospital.glb has not been built")
def test_glb_is_lean_and_reuses_template_geometry():
    gltf = read_glb_json(GLB)
    asset_nodes = [n for n in gltf["nodes"] if "asset_id" in n.get("extras", {})]
    meshes_used = {n["mesh"] for n in asset_nodes}
    assert len(meshes_used) < len(asset_nodes), "templates should be shared between instances"
    assert "cameras" not in gltf and "KHR_lights_punctual" not in gltf.get("extensionsUsed", [])
    assert len(gltf["materials"]) <= 24
    assert GLB.stat().st_size < 2_000_000
