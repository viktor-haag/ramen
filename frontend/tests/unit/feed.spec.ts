import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import type { PostingOut } from "@/api/types";
import { useFeedStore } from "@/stores/feed";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

function posting(id: number, triage: PostingOut["triage_status"] = "new"): PostingOut {
  return {
    id, source: "x", external_id: String(id), url: null, title: `T${id}`, company: null, location: null,
    lat: null, lon: null, description: null, published_at: null, first_seen_at: "2026-10-22T10:00:00Z",
    last_seen_at: "2026-10-22T10:00:00Z", employment_type: null, remote: null, contract_type: null,
    triage_status: triage, triaged_at: null, profile_ids: [], application_id: null, fit: null,
  };
}

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  get.mockReset();
  post.mockReset();
});

describe("feed store", () => {
  it("reset loads with the filter query", async () => {
    get.mockResolvedValue({ items: [posting(1)], total: 1 });
    const feed = useFeedStore();
    feed.filter.q = "vue";
    feed.filter.source = ["a", "b"];
    await feed.reset();
    const [path, params] = get.mock.calls[0]!;
    expect(path).toBe("/feed");
    expect(params).toMatchObject({ triage: ["new", "saved"], q: "vue", source: ["a", "b"], offset: 0 });
    expect(feed.items).toHaveLength(1);
    expect(feed.total).toBe(1);
  });

  it("maps the period to found_after and omits it for all", async () => {
    get.mockResolvedValue({ items: [], total: 0 });
    const feed = useFeedStore();
    feed.foundRange = "7d";
    await feed.reset();
    const after = new Date((get.mock.calls[0]![1] as { found_after: string }).found_after).getTime();
    expect(Date.now() - after).toBeGreaterThan(7 * 86400_000 - 5000);
    expect(Date.now() - after).toBeLessThan(7 * 86400_000 + 5000);
    feed.foundRange = "all";
    await feed.reset();
    expect((get.mock.calls[1]![1] as Record<string, unknown>).found_after).toBeUndefined();
  });

  it("loadMore appends and stops at total", async () => {
    get.mockResolvedValueOnce({ items: [posting(1), posting(2)], total: 3 });
    const feed = useFeedStore();
    await feed.reset();
    get.mockResolvedValueOnce({ items: [posting(3)], total: 3 });
    await feed.loadMore();
    expect((get.mock.calls[1]![1] as { offset: number }).offset).toBe(2);
    expect(feed.items.map((i) => i.id)).toEqual([1, 2, 3]);
    await feed.loadMore();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("dismiss removes the item with the default filter", async () => {
    get.mockResolvedValue({ items: [posting(1), posting(2)], total: 2 });
    post.mockResolvedValue(undefined);
    const feed = useFeedStore();
    await feed.reset();
    await feed.dismiss(1);
    expect(post).toHaveBeenCalledWith("/postings/1/dismiss");
    expect(feed.items.map((i) => i.id)).toEqual([2]);
    expect(feed.total).toBe(1);
  });

  it("dismiss keeps the item when the filter includes dismissed", async () => {
    get.mockResolvedValue({ items: [posting(1)], total: 1 });
    post.mockResolvedValue(undefined);
    const feed = useFeedStore();
    feed.filter.triage = ["new", "dismissed"];
    await feed.reset();
    await feed.dismiss(1);
    expect(feed.items).toHaveLength(1);
    expect(feed.items[0]!.triage_status).toBe("dismissed");
  });

  it("selectNext stops at the last row, selectPrev at the first", async () => {
    get.mockResolvedValue({ items: [posting(1), posting(2)], total: 2 });
    const feed = useFeedStore();
    await feed.reset();
    feed.selectNext();
    feed.selectNext();
    feed.selectNext();
    expect(feed.selectedIndex).toBe(1);
    feed.selectPrev();
    feed.selectPrev();
    feed.selectPrev();
    expect(feed.selectedIndex).toBe(0);
  });

  it("remembers the filter in localStorage and ignores broken json", async () => {
    get.mockResolvedValue({ items: [], total: 0 });
    const feed = useFeedStore();
    feed.filter.q = "abc";
    await feed.reset();
    expect(JSON.parse(localStorage.getItem("jobtracker.feedFilter")!).filter.q).toBe("abc");
    localStorage.setItem("jobtracker.feedFilter", "{nope");
    setActivePinia(createPinia());
    expect(useFeedStore().filter.triage).toEqual(["new", "saved"]);
    localStorage.setItem("jobtracker.feedFilter", JSON.stringify({ filter: { q: "x" }, foundRange: "30d" }));
    setActivePinia(createPinia());
    const restored = useFeedStore();
    expect(restored.filter.q).toBe("x");
    expect(restored.foundRange).toBe("30d");
  });

  it("discards stale responses after a new reset", async () => {
    let resolveFirst!: (v: unknown) => void;
    get.mockReturnValueOnce(new Promise((r) => (resolveFirst = r)) as never);
    get.mockResolvedValueOnce({ items: [posting(2)], total: 1 });
    const feed = useFeedStore();
    const first = feed.reset();
    await feed.reset();
    resolveFirst({ items: [posting(1)], total: 1 });
    await first;
    expect(feed.items.map((i) => i.id)).toEqual([2]);
  });
});

describe("feed store: fix round 1", () => {
  it("empty triage selection sends all three statuses and discards nothing", async () => {
    get.mockResolvedValue({ items: [posting(1)], total: 1 });
    post.mockResolvedValue(undefined);
    const feed = useFeedStore();
    feed.filter.triage = [];
    await feed.reset();
    expect((get.mock.calls[0]![1] as { triage: string[] }).triage).toEqual(["new", "saved", "dismissed"]);
    await feed.dismiss(1);
    expect(feed.items).toHaveLength(1);
  });

  it("resetCount increases after reset, loadError is set on failure", async () => {
    get.mockResolvedValueOnce({ items: [posting(1)], total: 5 });
    const feed = useFeedStore();
    await feed.reset();
    expect(feed.resetCount).toBe(1);
    get.mockRejectedValueOnce(new Error("boom"));
    await feed.loadMore();
    expect(feed.loadError).toBe(true);
    expect(feed.resetCount).toBe(1);
  });
});
