import { Edges } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { useRooms, useZones } from "../api/queries";
import { boundsCenter, boundsSize } from "../lib/coords";
import { useTwinStore } from "../state/twin";

/**
 * Fallback scene used when the Blender GLB cannot be loaded. It is built from the same
 * backend data (rooms, zones and asset positions), so the asset-id mapping still holds:
 * every box carries the backend asset id it represents.
 */
export function ProceduralHospital() {
  const { data: rooms = [] } = useRooms();
  const { data: zones = [] } = useZones();
  const assets = useTwinStore((s) => s.assets);
  const select = useTwinStore((s) => s.select);
  const colorOf = (zoneId: string | null) => zones.find((z) => z.id === zoneId)?.color ?? "#334155";

  return (
    <group>
      {rooms.map((room) => {
        const center = boundsCenter(room.bounds, -0.04);
        const { width, depth } = boundsSize(room.bounds);
        return (
          <mesh key={room.id} position={center}>
            <boxGeometry args={[width - 0.08, 0.08, depth - 0.08]} />
            <meshStandardMaterial color="#16202f" />
            <Edges color={colorOf(room.area_zone_id)} />
          </mesh>
        );
      })}
      {Object.values(assets)
        .filter((a) => a.position && !a.is_logical)
        .map((asset) => (
          <mesh
            key={asset.id}
            position={[asset.position!.x, 0.6, -asset.position!.y]}
            userData={{ asset_id: asset.id }}
            onClick={(e: ThreeEvent<MouseEvent>) => {
              e.stopPropagation();
              select(asset.id);
            }}
          >
            <boxGeometry args={[0.6, 1.2, 0.6]} />
            <meshStandardMaterial color={asset.discovered ? "#c084fc" : "#cbd5e1"} wireframe={asset.discovered} />
          </mesh>
        ))}
    </group>
  );
}
