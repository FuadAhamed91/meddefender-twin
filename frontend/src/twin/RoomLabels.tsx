import { useEffect, useState } from "react";
import { CanvasTexture, SRGBColorSpace } from "three";
import { useRooms } from "../api/queries";
import type { Room } from "../api/types";
import { planToWorld } from "../lib/coords";
import { useTwinStore } from "../state/twin";

const FONT_FAMILY = '"Inter Variable", ui-sans-serif, system-ui, sans-serif';
const FONT = `600 72px ${FONT_FAMILY}`;
const TEXT_HEIGHT = 0.42; // metres on the floor
const MARGIN = 0.55; // metres from the room's north-west corner

interface Label {
  room: Room;
  texture: CanvasTexture;
  width: number;
  height: number;
}

/** White text on a transparent canvas; tinted per view mode by the material color. */
function drawLabel(text: string): { texture: CanvasTexture; aspect: number } {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  ctx.font = FONT;
  ctx.letterSpacing = "6px";
  const width = Math.ceil(ctx.measureText(text).width) + 24;
  canvas.width = width;
  canvas.height = 96;
  ctx.font = FONT;
  ctx.letterSpacing = "6px";
  ctx.fillStyle = "#ffffff";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 12, 50);
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.anisotropy = 8;
  return { texture, aspect: canvas.width / canvas.height };
}

/**
 * Room names painted on the floor near each room's north-west corner, readable from the
 * default south-west view. Drawn in WebGL (not DOM) so they sit in the scene like signage.
 */
export function RoomLabels() {
  const { data: rooms = [] } = useRooms();
  const holo = useTwinStore((s) => s.viewMode === "holographic");
  const [labels, setLabels] = useState<Label[]>([]);

  useEffect(() => {
    if (!rooms.length) return;
    let cancelled = false;
    let built: Label[] = [];
    // Wait for the UI font so the canvas does not fall back to a system face.
    void document.fonts.load(FONT).finally(() => {
      if (cancelled) return;
      built = rooms
        .filter((room) => room.kind !== "corridor")
        .map((room) => {
          const { texture, aspect } = drawLabel(room.name.toUpperCase());
          const roomWidth = room.bounds.max[0] - room.bounds.min[0];
          let height = TEXT_HEIGHT * (96 / 72);
          let width = height * aspect;
          const available = roomWidth - MARGIN * 2;
          if (width > available) {
            height *= available / width;
            width = available;
          }
          return { room, texture, width, height };
        });
      setLabels(built);
    });
    return () => {
      cancelled = true;
      for (const label of built) label.texture.dispose();
    };
  }, [rooms]);

  return (
    <group>
      {labels.map(({ room, texture, width, height }) => {
        // North-west corner: from the south-west viewpoint the south wall would hide a label
        // placed along it, while the floor along the north wall stays in view.
        const x0 = room.bounds.min[0];
        const y1 = room.bounds.max[1];
        const position = planToWorld(x0 + MARGIN + width / 2, y1 - MARGIN - height / 2, 0.03);
        return (
          <mesh key={room.id} position={position} rotation={[-Math.PI / 2, 0, 0]} raycast={() => undefined} renderOrder={2}>
            <planeGeometry args={[width, height]} />
            <meshBasicMaterial
              map={texture}
              color={holo ? "#7cc4ff" : "#3b4a5e"}
              transparent
              opacity={holo ? 0.75 : 0.7}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        );
      })}
    </group>
  );
}
