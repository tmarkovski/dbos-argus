import { realtimeClient, type SubscriptionHandle } from "$lib/realtime";

export type Stats = {
  total: number;
  in_flight: number;
  enqueued: number;
  failed_recent: number;
  pending_notifications: number;
  active_schedules: number;
};

class StatsState {
  data = $state<Stats | null>(null);
  error = $state<string | null>(null);

  private handle: SubscriptionHandle | null = null;
  // Reference count so multiple components can call start()/stop() without
  // tearing each other's subscription down. The layout currently owns the
  // single starter — but counting cheaply guards against future callers.
  private refs = 0;

  /** Subscribe to the realtime `stats` channel. Idempotent. */
  start(): void {
    this.refs += 1;
    if (this.handle) return;
    this.handle = realtimeClient.subscribe("stats", undefined, {
      onSnapshot: (data) => {
        this.data = data as Stats;
        this.error = null;
      },
      onUpdate: (data) => {
        this.data = data as Stats;
        this.error = null;
      },
      onError: (_code, message) => {
        this.error = message;
      },
    });
  }

  stop(): void {
    if (this.refs > 0) this.refs -= 1;
    if (this.refs > 0) return;
    this.handle?.dispose();
    this.handle = null;
  }
}

export const statsState = new StatsState();
