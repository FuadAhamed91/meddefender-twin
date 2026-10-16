import { create } from "zustand";
import type {
  AssetSummary,
  AttackPathResult,
  ContainmentPlan,
  LiveEvent,
  PolicyOutcome,
  Severity,
  TwinSnapshot,
  TwinState,
} from "../api/types";

export type ConnectionState = "connecting" | "live" | "reconnecting" | "offline";
export type ViewMode = "holographic" | "realistic";

export interface Overlays {
  network: boolean;
  dependencies: boolean;
  topology: boolean;
  labels: boolean;
  zones: boolean;
}

export interface TransientEdge {
  key: string;
  source: string;
  destination: string;
  service: string;
  outcome: PolicyOutcome;
  at: number;
}

export interface FocusRequest {
  kind: "asset" | "zone" | "overview" | "assets";
  ids: string[];
  nonce: number;
}

export interface HighlightSet {
  assets: string[];
  label: string;
  edges?: { source: string; destination: string; outcome: PolicyOutcome }[];
}

interface TwinStore {
  ready: boolean;
  epoch: number;
  lastEventId: number;
  assets: Record<string, AssetSummary>;
  twin: Record<string, TwinState>;
  selectedId: string | null;
  hoveredId: string | null;
  overlays: Overlays;
  attackPath: AttackPathResult | null;
  planPreview: ContainmentPlan | null;
  highlight: HighlightSet | null;
  flashes: Record<string, { at: number; severity: Severity }>;
  transientEdges: TransientEdge[];
  feed: LiveEvent[];
  counters: { accepted: number; held: number; rejected: number };
  connection: ConnectionState;
  focus: FocusRequest;
  mappingIssues: string[];
  viewMode: ViewMode;

  loadSnapshot: (snapshot: TwinSnapshot) => void;
  applyEvent: (event: LiveEvent) => void;
  select: (id: string | null) => void;
  hover: (id: string | null) => void;
  toggleOverlay: (key: keyof Overlays) => void;
  setAttackPath: (result: AttackPathResult | null) => void;
  setPlanPreview: (plan: ContainmentPlan | null) => void;
  setHighlight: (highlight: HighlightSet | null) => void;
  setConnection: (state: ConnectionState) => void;
  requestFocus: (kind: FocusRequest["kind"], ids?: string[]) => void;
  setMappingIssues: (issues: string[]) => void;
  pruneTransient: (now: number) => void;
  setViewMode: (mode: ViewMode) => void;
}

const FEED_LIMIT = 120;
export const EDGE_TTL_MS = 9000;
const FLASH_TTL_MS = 12000;

export const useTwinStore = create<TwinStore>((set, get) => ({
  ready: false,
  epoch: 1,
  lastEventId: 0,
  assets: {},
  twin: {},
  selectedId: null,
  hoveredId: null,
  overlays: { network: true, dependencies: false, topology: false, labels: false, zones: true },
  attackPath: null,
  planPreview: null,
  highlight: null,
  flashes: {},
  transientEdges: [],
  feed: [],
  counters: { accepted: 0, held: 0, rejected: 0 },
  connection: "connecting",
  focus: { kind: "overview", ids: [], nonce: 0 },
  mappingIssues: [],
  viewMode: (() => {
    try {
      return (localStorage.getItem("md.viewMode") as ViewMode | null) ?? "holographic";
    } catch {
      return "holographic";
    }
  })(),

  loadSnapshot: (snapshot) =>
    set({
      ready: true,
      epoch: snapshot.epoch,
      lastEventId: snapshot.last_event_id,
      assets: Object.fromEntries(snapshot.assets.map((a) => [a.id, a])),
      twin: Object.fromEntries(snapshot.twin_states.map((t) => [t.asset_id, t])),
    }),

  applyEvent: (event) => {
    const state = get();
    const payload = (event.payload ?? {}) as Record<string, unknown>;
    const patch: Partial<TwinStore> = {};
    if (typeof event.id === "number" && event.id > state.lastEventId) patch.lastEventId = event.id;
    const now = Date.now();

    switch (event.type) {
      case "twin.updated": {
        const id = String(payload.asset_id);
        patch.twin = { ...state.twin, [id]: payload as unknown as TwinState };
        const trust = payload.trust_state as AssetSummary["trust_state"] | undefined;
        if (state.assets[id] && trust) {
          patch.assets = {
            ...state.assets,
            [id]: { ...state.assets[id], trust_state: trust, twin_version: Number(payload.version ?? 0), reported_decision: (payload.reported_decision as AssetSummary["reported_decision"]) ?? null },
          };
        }
        break;
      }
      case "trust.changed": {
        const id = String(payload.asset_id);
        if (state.assets[id]) {
          patch.assets = { ...state.assets, [id]: { ...state.assets[id], trust_state: payload.to as AssetSummary["trust_state"] } };
        }
        break;
      }
      case "asset.updated": {
        const id = String(payload.asset_id);
        if (state.assets[id]) {
          patch.assets = {
            ...state.assets,
            [id]: { ...state.assets[id], containment_state: payload.containment_state as AssetSummary["containment_state"] },
          };
        }
        break;
      }
      case "alert.created": {
        const target = (payload.asset_id as string | null) ?? (payload.subject_ref as string);
        if (target) patch.flashes = { ...state.flashes, [target]: { at: now, severity: payload.severity as Severity } };
        break;
      }
      case "telemetry.processed": {
        const decision = payload.decision as string;
        patch.counters = {
          accepted: state.counters.accepted + (decision === "ACCEPTED" ? 1 : 0),
          held: state.counters.held + (decision === "HELD" ? 1 : 0),
          rejected: state.counters.rejected + (decision === "REJECTED" ? 1 : 0),
        };
        break;
      }
      case "network.flow_observed":
      case "policy.decision": {
        if (event.type === "policy.decision" && payload.policy_type !== "NETWORK_FLOW") break;
        const source = String(payload.source);
        const destination = String(payload.destination);
        const service = String(payload.service ?? payload.service_or_action ?? "");
        const key = `${source}>${destination}:${service}`;
        const outcome = (payload.outcome as PolicyOutcome) ?? "PERMITTED";
        patch.transientEdges = [
          ...state.transientEdges.filter((e) => e.key !== key && now - e.at < EDGE_TTL_MS),
          { key, source, destination, service, outcome, at: now },
        ].slice(-40);
        break;
      }
      default:
        break;
    }

    const routine = event.type === "telemetry.processed" && payload.decision === "ACCEPTED";
    if (!routine && event.type !== "heartbeat" && event.type !== "hello" && event.type !== "twin.updated") {
      patch.feed = [event, ...state.feed].slice(0, FEED_LIMIT);
    }
    set(patch);
  },

  select: (id) => set({ selectedId: id }),
  hover: (id) => set({ hoveredId: id }),
  toggleOverlay: (key) => set((s) => ({ overlays: { ...s.overlays, [key]: !s.overlays[key] } })),
  setAttackPath: (result) => set({ attackPath: result }),
  setPlanPreview: (plan) => set({ planPreview: plan }),
  setHighlight: (highlight) => set({ highlight }),
  setConnection: (connection) => set({ connection }),
  requestFocus: (kind, ids = []) => set((s) => ({ focus: { kind, ids, nonce: s.focus.nonce + 1 } })),
  setMappingIssues: (mappingIssues) => set({ mappingIssues }),
  setViewMode: (viewMode) => {
    try {
      localStorage.setItem("md.viewMode", viewMode);
    } catch {
      /* storage may be unavailable; the choice still applies for this session */
    }
    set({ viewMode });
  },
  pruneTransient: (now) =>
    set((s) => {
      const edges = s.transientEdges.filter((e) => now - e.at < EDGE_TTL_MS);
      const flashes = Object.fromEntries(Object.entries(s.flashes).filter(([, f]) => now - f.at < FLASH_TTL_MS));
      if (edges.length === s.transientEdges.length && Object.keys(flashes).length === Object.keys(s.flashes).length) return s;
      return { transientEdges: edges, flashes };
    }),
}));
