import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "@/api/client";
import type { PluginOut, ProfileIn, ProfileOut, RunOut, RunStartOut } from "@/api/types";
import { POLL_INTERVAL_MS } from "@/stores/runs";
import { useNotifyStore } from "@/stores/notify";

export const SCHEDULE_HOURS = [null, 1, 3, 6, 12, 24] as const;

export interface ProfileForm {
  name: string;
  keywords: string[];
  location: string;
  radius_km: number | null;
  employment_type: string | null;
  remote: boolean;
  enabled: boolean;
  schedule_hours: number | null;
}

export const MAX_KEYWORDS = 20;
export const MAX_KEYWORD_LENGTH = 100;

/** Split free text at commas into trimmed, non-empty terms. */
export function splitKeywords(input: string): string[] {
  return input.split(",").map((s) => s.trim()).filter((s) => s !== "");
}

/**
 * Same rules as the backend: trim, drop empties, case-insensitive dedupe (first occurrence wins, order kept).
 * The backend uses Python's casefold(); toLowerCase() plus "ß" -> "ss" matches it for the common case
 * (casefold maps "ß" to "ss", toLowerCase leaves it alone, so "Straße" and "STRASSE" must collide here too).
 */
export function normalizeKeywords(list: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of list) {
    const k = raw.trim();
    const key = k.toLowerCase().replaceAll("ß", "ss");
    if (k === "" || seen.has(key)) continue;
    seen.add(key);
    out.push(k);
  }
  return out;
}

export interface ProfileRunResult {
  newCount: number;
  failed: number;
  alreadyRunning: boolean;
}

/** A plugin that can be selected as extractor: SEARCH capability, globally enabled and loadable. */
export function isUsableSearch(p: PluginOut): boolean {
  return p.capabilities.includes("search") && p.enabled && p.error === null;
}

/** Form -> API payload. `plugins: []` means "all enabled", stored when exactly all usable plugins are checked. */
export function toPayload(form: ProfileForm, checked: string[], plugins: PluginOut[]): ProfileIn {
  const usable = plugins.filter(isUsableSearch).map((p) => p.name);
  const selected = usable.filter((n) => checked.includes(n));
  const all = selected.length === usable.length;
  const text = (s: string) => s.trim() || null;
  const location = text(form.location);
  const raw: unknown = form.radius_km;
  const num = typeof raw === "number" ? raw : typeof raw === "string" && raw.trim() !== "" ? Number(raw) : NaN;
  const radius = Number.isFinite(num) ? num : null;
  return {
    name: form.name.trim(),
    keywords: normalizeKeywords(form.keywords),
    location,
    radius_km: location ? radius : null,
    employment_type: form.employment_type || null,
    remote: form.remote ? true : null,
    enabled: form.enabled,
    schedule_hours: form.schedule_hours,
    plugins: all ? [] : selected,
  };
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const failedStatus = (r: RunOut) => r.status === "error" || r.status === "timeout";

export const useProfilesStore = defineStore("profiles", () => {
  const items = ref<ProfileOut[]>([]);
  const history = ref<Record<number, RunOut[]>>({});
  const running = ref<Record<number, boolean>>({});
  const results = ref<Record<number, ProfileRunResult>>({});
  let generation = 0;

  const notify = () => useNotifyStore();

  async function load() {
    try {
      const [profiles, runs] = await Promise.all([
        api.get<ProfileOut[]>("/profiles"),
        api.get<RunOut[]>("/runs", { limit: 200 }),
      ]);
      items.value = profiles;
      const grouped: Record<number, RunOut[]> = {};
      for (const r of runs) if (r.profile_id !== null) (grouped[r.profile_id] ??= []).push(r);
      for (const list of Object.values(grouped)) list.sort((a, b) => b.started_at.localeCompare(a.started_at));
      history.value = grouped;
    } catch (e) {
      notify().error(e);
    }
  }

  async function loadHistory(id: number): Promise<RunOut[]> {
    try {
      const runs = await api.get<RunOut[]>("/runs", { profile_id: id, limit: 20 });
      history.value = { ...history.value, [id]: runs };
      return runs;
    } catch (e) {
      notify().error(e);
      return [];
    }
  }

  function replace(p: ProfileOut) {
    items.value = items.value.some((x) => x.id === p.id) ? items.value.map((x) => (x.id === p.id ? p : x)) : [...items.value, p];
  }

  /** Create (id null) or update a profile; errors are reported via notify. */
  async function save(id: number | null, payload: ProfileIn): Promise<boolean> {
    try {
      replace(id === null ? await api.post<ProfileOut>("/profiles", payload) : await api.put<ProfileOut>(`/profiles/${id}`, payload));
      return true;
    } catch (e) {
      notify().error(e);
      return false;
    }
  }

  async function setEnabled(p: ProfileOut, enabled: boolean): Promise<void> {
    const { id: _id, last_run_at: _last, ...rest } = p;
    await save(p.id, { ...rest, enabled });
  }

  async function remove(id: number): Promise<boolean> {
    try {
      await api.del(`/profiles/${id}`);
      items.value = items.value.filter((p) => p.id !== id);
      return true;
    } catch (e) {
      notify().error(e);
      return false;
    }
  }

  /** Start runs for one profile, poll until none of its runs is active, then refresh its history and result. */
  async function runNow(id: number): Promise<void> {
    if (running.value[id]) return;
    const mine = generation;
    running.value = { ...running.value, [id]: true };
    const { [id]: _drop, ...others } = results.value;
    results.value = others;
    try {
      const started = await api.post<RunStartOut>(`/profiles/${id}/run`);
      for (;;) {
        const active = await api.get<RunOut[]>("/runs/active");
        if (mine !== generation) return;
        if (!active.some((r) => r.profile_id === id)) break;
        await sleep(POLL_INTERVAL_MS);
        if (mine !== generation) return;
      }
      const runs = await loadHistory(id);
      if (mine !== generation) return;
      const ids = new Set(started.run_ids);
      const mineRuns = runs.filter((r) => ids.has(r.id));
      results.value = {
        ...results.value,
        [id]: {
          newCount: mineRuns.reduce((n, r) => n + r.new_count, 0),
          failed: mineRuns.filter(failedStatus).length,
          alreadyRunning: started.already_running && started.run_ids.length === 0,
        },
      };
      const fresh = await api.get<ProfileOut>(`/profiles/${id}`).catch(() => null);
      if (fresh && mine === generation) replace(fresh);
    } catch (e) {
      if (mine === generation) notify().error(e);
    } finally {
      if (mine === generation) running.value = { ...running.value, [id]: false };
    }
  }

  /** Cancel polling (view unmount). */
  function stop() {
    generation++;
    running.value = {};
  }

  /** Cancel polling and drop all loaded profiles and run history (data was wiped on the server). */
  function clear() {
    stop();
    items.value = [];
    history.value = {};
    results.value = {};
  }

  /** Drop loaded run history and results only (runs were deleted on the server, profiles remain). */
  function clearRunData() {
    history.value = {};
    results.value = {};
  }

  return { items, history, running, results, load, loadHistory, save, setEnabled, remove, runNow, stop, clear, clearRunData };
});
