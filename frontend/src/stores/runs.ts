import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "@/api/client";
import type { RunOut, RunStartOut } from "@/api/types";
import { useFeedStore } from "@/stores/feed";
import { useNotifyStore } from "@/stores/notify";

export const POLL_INTERVAL_MS = 2000;

export interface RefreshResult {
  newCount: number;
  failed: number;
  alreadyRunning: boolean;
}

export const useRunsStore = defineStore("runs", () => {
  const active = ref<RunOut[]>([]);
  const starting = ref(false);
  const lastResult = ref<RefreshResult | null>(null);
  let generation = 0;

  const isRunning = computed(() => starting.value || active.value.length > 0);

  /** Cancel polling (component unmount / reset); the pending refreshAll() resolves without reloading the feed. */
  function stop() {
    generation++;
    starting.value = false;
    active.value = [];
  }

  const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

  /** Start runs for all active profiles, poll until done, reload the feed; returns the number of new postings. */
  async function refreshAll(): Promise<number> {
    if (isRunning.value) return 0;
    const mine = ++generation;
    starting.value = true;
    try {
      const started = await api.post<RunStartOut>("/runs");
      for (;;) {
        const current = await api.get<RunOut[]>("/runs/active");
        if (mine !== generation) return 0;
        active.value = current;
        starting.value = false;
        if (current.length === 0) break;
        await sleep(POLL_INTERVAL_MS);
        if (mine !== generation) return 0;
      }
      await useFeedStore().reset();
      let newCount = 0;
      let failed = 0;
      if (started.run_ids.length > 0) {
        const ids = new Set(started.run_ids);
        const runs = await api.get<RunOut[]>("/runs", { limit: 200 });
        for (const r of runs.filter((r) => ids.has(r.id))) {
          newCount += r.new_count;
          if (r.status === "error" || r.status === "timeout") failed++;
        }
      }
      if (mine !== generation) return 0;
      lastResult.value = { newCount, failed, alreadyRunning: started.already_running && started.run_ids.length === 0 };
      return newCount;
    } catch (e) {
      if (mine === generation) useNotifyStore().error(e);
      return 0;
    } finally {
      if (mine === generation) {
        starting.value = false;
        active.value = [];
      }
    }
  }

  /** Stop polling and forget the last result (data was wiped on the server). */
  function clear() {
    stop();
    lastResult.value = null;
  }

  return { active, lastResult, isRunning, refreshAll, stop, clear };
});
