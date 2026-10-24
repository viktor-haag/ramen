import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VInfiniteScroll, VLayout } from "vuetify/components";
import { api } from "@/api/client";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useFeedStore } from "@/stores/feed";
import FeedView from "@/views/FeedView.vue";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

function posting(id: number) {
  const now = new Date().toISOString();
  return {
    id, source: "x", external_id: String(id), url: `https://example.com/${id}`, title: `Job ${id}`, company: "ACME",
    location: "Berlin", lat: null, lon: null, description: "Line1\n<b>x</b>", published_at: null,
    first_seen_at: now, last_seen_at: now, employment_type: null, remote: null, contract_type: null,
    triage_status: "new", triaged_at: null, profile_ids: [], application_id: null, fit: null,
  };
}

beforeEach(() => {
  localStorage.clear();
  get.mockReset();
  post.mockReset();
  get.mockImplementation((async (path: string) => {
    if (path === "/feed") return { items: [posting(1), posting(2)], total: 2 };
    if (path === "/plugins" || path === "/profiles") return [];
    if (path.startsWith("/postings/")) return posting(Number(path.split("/")[2]));
    return [];
  }) as never);
  post.mockResolvedValue(undefined);
});

describe("FeedView", () => {
  it("shortcuts j/m/v/Enter work, not in input fields, not at all after unmount", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const Host = defineComponent({ render: () => h(VLayout, null, { default: () => h(FeedView) }) });
    const w = mount(Host, { global: { plugins: [pinia, i18n, vuetify], stubs: { RouterLink: true } }, attachTo: document.body });
    await flushPromises();
    const feed = useFeedStore();
    expect(feed.items).toHaveLength(2);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "j" }));
    expect(feed.selectedIndex).toBe(0);

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "j", bubbles: true }));
    expect(feed.selectedIndex).toBe(0);
    input.remove();

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "m" }));
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/postings/1/save");
    expect(feed.items[0]!.triage_status).toBe("saved");

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "v" }));
    await flushPromises();
    // a saved posting has an application: dismissing is not offered
    expect(post).not.toHaveBeenCalledWith("/postings/1/dismiss");
    expect(feed.items.map((i) => i.id)).toEqual([1, 2]);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "j" }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await flushPromises();
    expect(get.mock.calls.some((c) => c[0] === "/postings/2")).toBe(true);
    const desc = document.querySelector("[data-test='drawer-description']")!;
    expect(desc.textContent).toBe("Line1\n<b>x</b>");
    expect(desc.querySelector("b")).toBeNull();

    w.unmount();
    const before = feed.selectedIndex;
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k" }));
    expect(feed.selectedIndex).toBe(before);
  });

  it("infinite scroll: error -> done(error); key changes after reset", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const Host = defineComponent({ render: () => h(VLayout, null, { default: () => h(FeedView) }) });
    const w = mount(Host, { global: { plugins: [pinia, i18n, vuetify], stubs: { RouterLink: true } }, attachTo: document.body });
    await flushPromises();
    const feed = useFeedStore();
    const before = feed.resetCount;
    await feed.reset();
    await flushPromises();
    expect(feed.resetCount).toBe(before + 1);

    feed.total = 10; // more available
    get.mockRejectedValueOnce(new Error("boom"));
    const done = vi.fn();
    w.findComponent(VInfiniteScroll).vm.$emit("load", { done });
    await flushPromises();
    expect(done).toHaveBeenCalledWith("error");
    w.unmount();
  });

  it("dismissing is possible for postings with an application neither via button nor via v", async () => {
    get.mockImplementation((async (path: string) => {
      if (path === "/feed") return { items: [{ ...posting(1), triage_status: "saved", application_id: 7 }, posting(2)], total: 2 };
      if (path === "/plugins" || path === "/profiles") return [];
      return [];
    }) as never);
    setActivePinia(createPinia());
    const feed = useFeedStore();
    expect(feed.canDismiss({ triage_status: "saved", application_id: 7 })).toBe(false);
    expect(feed.canDismiss({ triage_status: "new", application_id: 7 })).toBe(false);
    expect(feed.canDismiss({ triage_status: "new", application_id: null })).toBe(true);
    await feed.toggleDismiss({ id: 1, triage_status: "new", application_id: 7 });
    expect(post).not.toHaveBeenCalled();
    await feed.toggleDismiss({ id: 2, triage_status: "new", application_id: null });
    expect(post).toHaveBeenCalledWith("/postings/2/dismiss");
  });

  it("feed rows are cards with a status edge class per triage status", async () => {
    get.mockImplementation((async (path: string) => {
      if (path === "/feed")
        return {
          items: [posting(1), { ...posting(2), triage_status: "saved" }, { ...posting(3), triage_status: "dismissed" }],
          total: 3,
        };
      if (path === "/plugins" || path === "/profiles") return [];
      return [];
    }) as never);
    const pinia = createPinia();
    setActivePinia(pinia);
    const Host = defineComponent({ render: () => h(VLayout, null, { default: () => h(FeedView) }) });
    const w = mount(Host, { global: { plugins: [pinia, i18n, vuetify], stubs: { RouterLink: true } }, attachTo: document.body });
    await flushPromises();
    const rows = w.findAll("[data-test='feed-row']");
    expect(rows).toHaveLength(3);
    const statuses = ["new", "saved", "dismissed"];
    rows.forEach((r, i) => {
      expect(r.classes()).toContain("feed-item");
      expect(r.classes()).toContain(`feed-item--${statuses[i]}`);
      expect(r.find(".v-chip").exists()).toBe(true);
    });
    w.unmount();
  });
});
