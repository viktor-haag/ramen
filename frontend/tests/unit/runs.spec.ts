import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import type { RunOut } from "@/api/types";
import { useFeedStore } from "@/stores/feed";
import { useRunsStore } from "@/stores/runs";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

function run(id: number, status: RunOut["status"], new_count = 0): RunOut {
  return {
    id, profile_id: 1, profile_name: "P", plugin: "p", trigger: "manual", started_at: "2026-10-22T10:00:00Z",
    finished_at: null, status, new_count, total_count: 0, invalid_count: 0, error: null,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  setActivePinia(createPinia());
  get.mockReset();
  post.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("runs store", () => {
  it("refreshAll polls until no runs are active and reloads the feed", async () => {
    post.mockResolvedValue({ run_ids: [1, 2], already_running: false });
    let activeCalls = 0;
    get.mockImplementation((async (path: string) => {
      if (path === "/runs/active") return ++activeCalls <= 2 ? [run(1, "running")] : [];
      if (path === "/runs") return [run(1, "ok", 3), run(2, "error", 5), run(9, "ok", 100)];
      return { items: [], total: 0 };
    }) as never);
    const runs = useRunsStore();
    const feed = useFeedStore();
    const reset = vi.spyOn(feed, "reset").mockResolvedValue();
    const p = runs.refreshAll();
    await vi.advanceTimersByTimeAsync(0);
    expect(runs.isRunning).toBe(true);
    expect(reset).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1999);
    expect(activeCalls).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(activeCalls).toBe(2);
    await vi.advanceTimersByTimeAsync(2000);
    expect(await p).toBe(8);
    expect(activeCalls).toBe(3);
    expect(reset).toHaveBeenCalledTimes(1);
    expect(runs.isRunning).toBe(false);
    expect(runs.lastResult).toEqual({ newCount: 8, failed: 1, alreadyRunning: false });
    expect(get).toHaveBeenCalledWith("/runs", { limit: 200 });
  });

  it("already_running without ids still polls and reports it", async () => {
    post.mockResolvedValue({ run_ids: [], already_running: true });
    let n = 0;
    get.mockImplementation((async () => (++n === 1 ? [run(5, "running")] : [])) as never);
    const runs = useRunsStore();
    vi.spyOn(useFeedStore(), "reset").mockResolvedValue();
    const p = runs.refreshAll();
    await vi.advanceTimersByTimeAsync(2000);
    expect(await p).toBe(0);
    expect(runs.lastResult).toEqual({ newCount: 0, failed: 0, alreadyRunning: true });
    expect(get).not.toHaveBeenCalledWith("/runs", expect.anything());
  });

  it("stop ends polling without a feed reload", async () => {
    post.mockResolvedValue({ run_ids: [1], already_running: false });
    get.mockResolvedValue([run(1, "running")] as never);
    const runs = useRunsStore();
    const reset = vi.spyOn(useFeedStore(), "reset").mockResolvedValue();
    const p = runs.refreshAll();
    await vi.advanceTimersByTimeAsync(0);
    runs.stop();
    await vi.advanceTimersByTimeAsync(10000);
    await p;
    expect(get).toHaveBeenCalledTimes(1);
    expect(reset).not.toHaveBeenCalled();
    expect(runs.isRunning).toBe(false);
  });
});
