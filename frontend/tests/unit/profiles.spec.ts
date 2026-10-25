import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import type { PluginOut } from "@/api/types";
import { HISTORY_LIMIT, normalizeKeywords, splitKeywords, toPayload, useProfilesStore, type ProfileForm } from "@/stores/profiles";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

const plugin = (name: string, over: Partial<PluginOut> = {}): PluginOut => ({
  name, display_name: name, capabilities: ["search"], url_patterns: [], enabled: true, settings: {}, settings_schema: null, error: null, ...over,
});
const plugins = [
  plugin("a"), plugin("b"), plugin("off", { enabled: false }), plugin("broken", { error: "boom", capabilities: [] }), plugin("fetcher", { capabilities: ["fetch"] }),
];
const form: ProfileForm = {
  name: "  Dev ", keywords: [" vue ", "Vue", "Python"], location: "", radius_km: 30, employment_type: null, remote: false, enabled: true, schedule_hours: 6,
};

describe("keywords helpers", () => {
  it("splitKeywords splits at commas, trims and drops empties", () => {
    expect(splitKeywords("Python, Data Engineer,,  ")).toEqual(["Python", "Data Engineer"]);
    expect(splitKeywords("   ")).toEqual([]);
  });

  it("normalizeKeywords trims, drops empties and case-insensitive duplicates (first wins)", () => {
    expect(normalizeKeywords(["  Vue ", "", "vue", "Python", "PYTHON", "Go"])).toEqual(["Vue", "Python", "Go"]);
  });

  it("normalizeKeywords folds case like casefold for German sharp s", () => {
    expect(normalizeKeywords(["Straße", "STRASSE", "strasse", "Maß"])).toEqual(["Straße", "Maß"]);
  });
});

describe("toPayload", () => {
  it("stores an empty plugin list when all enabled plugins are selected", () => {
    const p = toPayload(form, ["a", "b"], plugins);
    expect(p.plugins).toEqual([]);
    expect(p).toMatchObject({ name: "Dev", keywords: ["vue", "Python"], location: null, radius_km: null, remote: null, schedule_hours: 6 });
  });

  it("stores the selection otherwise", () => {
    expect(toPayload({ ...form, location: "Berlin", remote: true }, ["b"], plugins)).toMatchObject({
      plugins: ["b"], location: "Berlin", radius_km: 30, remote: true,
    });
  });

  it("empty or invalid radius becomes null, not 0", () => {
    const f = { ...form, location: "Berlin" };
    expect(toPayload({ ...f, radius_km: "" as never }, ["a", "b"], plugins).radius_km).toBeNull();
    expect(toPayload({ ...f, radius_km: Number.NaN }, ["a", "b"], plugins).radius_km).toBeNull();
    expect(toPayload({ ...f, radius_km: 0 }, ["a", "b"], plugins).radius_km).toBe(0);
  });

  it("ignores disabled, unloadable and fetch-only plugins", () => {
    expect(toPayload(form, ["a", "b", "off", "broken", "fetcher"], plugins).plugins).toEqual([]);
    expect(toPayload(form, ["a", "off"], plugins).plugins).toEqual(["a"]);
  });
});

describe("runNow", () => {
  it("polls /runs/active until the profile is done, then loads the history and shows the result", async () => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    const get = vi.mocked(api.get);
    const post = vi.mocked(api.post);
    post.mockResolvedValue({ run_ids: [5], already_running: false });
    const run = { id: 5, profile_id: 1, plugin: "a", status: "ok", new_count: 3, total_count: 9, invalid_count: 0, error: null, started_at: "2026-10-22T10:00:00Z" };
    let activeCalls = 0;
    get.mockImplementation((async (path: string) => {
      if (path === "/runs/active") return ++activeCalls < 3 ? [{ ...run, status: "running" }] : [];
      if (path === "/runs") return [run];
      return null;
    }) as never);
    const store = useProfilesStore();
    const p = store.runNow(1);
    await vi.advanceTimersByTimeAsync(5000);
    await p;
    expect(activeCalls).toBe(3);
    expect(store.running[1]).toBe(false);
    expect(store.results[1]).toEqual({ newCount: 3, failed: 0, alreadyRunning: false });
    expect(store.history[1]).toHaveLength(1);
    vi.useRealTimers();
  });
});

describe("profile history", () => {
  it("keeps only the newest HISTORY_LIMIT runs per profile", async () => {
    setActivePinia(createPinia());
    const runs = Array.from({ length: 25 }, (_, i) => ({
      id: i + 1, profile_id: 1, profile_name: "p", plugin: "a", trigger: "manual", status: "ok",
      started_at: new Date(Date.UTC(2026, 9, 1, 0, i)).toISOString(), finished_at: null,
      new_count: 0, total_count: 0, invalid_count: 0, error: null,
    }));
    vi.mocked(api.get).mockImplementation((async (path: string) => (path === "/runs" ? runs : [])) as never);
    const store = useProfilesStore();
    await store.load();
    expect(store.history[1]).toHaveLength(HISTORY_LIMIT);
    expect(store.history[1][0].id).toBe(25);
  });
});
