import type { QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { LiveEvent, TwinSnapshot } from "../api/types";
import { useTwinStore } from "./twin";

/**
 * Live connection to /ws/events.
 *
 * - Loads the authoritative snapshot (GET /api/v1/twin/state) first.
 * - Connects with ?since=<last_event_id> so missed events are replayed by the server.
 * - Reconnects with exponential backoff; on "resync_required" refetches the snapshot.
 * - Never derives security state locally: every update comes from a persisted backend event.
 */
export class LiveConnection {
  private socket: WebSocket | null = null;
  private stopped = false;
  private attempt = 0;
  private retryTimer: number | null = null;
  private invalidateTimer: number | null = null;
  private pruneTimer: number | null = null;
  private readonly pending = new Set<string>();

  constructor(private readonly queryClient: QueryClient) {}

  async start(): Promise<void> {
    this.stopped = false;
    useTwinStore.getState().setConnection("connecting");
    await this.resync();
    this.connect();
    this.pruneTimer = window.setInterval(() => useTwinStore.getState().pruneTransient(Date.now()), 1500);
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer) window.clearTimeout(this.retryTimer);
    if (this.invalidateTimer) window.clearTimeout(this.invalidateTimer);
    if (this.pruneTimer) window.clearInterval(this.pruneTimer);
    this.socket?.close();
    this.socket = null;
  }

  private async resync(): Promise<void> {
    try {
      const snapshot = await api.get<TwinSnapshot>("/api/v1/twin/state");
      useTwinStore.getState().loadSnapshot(snapshot);
    } catch {
      useTwinStore.getState().setConnection("offline");
    }
  }

  private connect(): void {
    if (this.stopped) return;
    const since = useTwinStore.getState().lastEventId;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${window.location.host}/ws/events?since=${since}`);
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      useTwinStore.getState().setConnection("live");
    };
    socket.onmessage = (message) => {
      let event: LiveEvent;
      try {
        event = JSON.parse(message.data as string) as LiveEvent;
      } catch {
        return;
      }
      this.handle(event);
    };
    socket.onclose = (closeEvent) => {
      this.socket = null;
      if (this.stopped) return;
      if (closeEvent.code === 4401) {
        useTwinStore.getState().setConnection("offline");
        this.queryClient.setQueryData(["me"], null);
        return;
      }
      useTwinStore.getState().setConnection("reconnecting");
      const delay = Math.min(15000, 1000 * 2 ** this.attempt) + Math.random() * 400;
      this.attempt += 1;
      this.retryTimer = window.setTimeout(() => this.connect(), delay);
    };
  }

  private handle(event: LiveEvent): void {
    const store = useTwinStore.getState();
    if (event.type === "resync_required" || event.type === "simulation.reset") {
      void this.resync().then(() => {
        this.socket?.close();
      });
      this.invalidate(["incidents", "metrics", "simulation-status", "graph-network", "asset", "scenarios", "alerts"]);
      if (event.type === "simulation.reset") store.applyEvent(event);
      return;
    }
    if (event.type === "hello" || event.type === "heartbeat") return;
    store.applyEvent(event);

    switch (event.type) {
      case "twin.updated":
      case "trust.changed":
      case "asset.updated":
        this.invalidate([`asset:${String(event.payload?.asset_id ?? "")}`]);
        break;
      case "alert.created":
        this.invalidate(["metrics", "alerts"]);
        break;
      case "incident.created":
      case "incident.updated":
        this.invalidate(["incidents", "incident", "metrics"]);
        break;
      case "asset.discovered":
      case "containment.applied":
        void this.resync();
        this.invalidate(["incidents", "incident", "metrics", "graph-network", "attack-paths"]);
        break;
      case "network.flow_observed":
        if (event.payload?.new_path) this.invalidate(["graph-network"]);
        break;
      case "simulation.run_completed":
        this.invalidate(["runs", "scenarios", "incidents", "metrics"]);
        break;
      default:
        break;
    }
  }

  /** Debounced cache invalidation so bursts of events cause one refetch per query. */
  private invalidate(keys: string[]): void {
    keys.forEach((k) => this.pending.add(k));
    if (this.invalidateTimer) return;
    this.invalidateTimer = window.setTimeout(() => {
      this.invalidateTimer = null;
      const keysNow = [...this.pending];
      this.pending.clear();
      for (const key of keysNow) {
        if (key.startsWith("asset:")) {
          const id = key.slice(6);
          if (id) void this.queryClient.invalidateQueries({ queryKey: ["asset", id] });
        } else {
          void this.queryClient.invalidateQueries({ queryKey: [key] });
        }
      }
    }, 600);
  }
}
