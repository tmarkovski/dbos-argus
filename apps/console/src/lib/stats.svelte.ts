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

  async refresh() {
    try {
      const res = await fetch("/api/stats");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.data = (await res.json()) as Stats;
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    }
  }
}

export const statsState = new StatsState();
