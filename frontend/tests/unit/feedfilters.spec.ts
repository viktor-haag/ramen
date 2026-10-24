import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VTextField } from "vuetify/components";
import { api } from "@/api/client";
import FeedFilters from "@/components/FeedFilters.vue";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useFeedStore } from "@/stores/feed";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.get).mockResolvedValue([] as never);
});
afterEach(() => vi.useRealTimers());

describe("FeedFilters", () => {
  it("clearing search and location resets the filter and reloads (debounced)", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const feed = useFeedStore();
    feed.filter.q = "vue";
    feed.filter.location = "Berlin";
    feed.filter.radius_km = 25;
    const reset = vi.spyOn(feed, "reset").mockResolvedValue();
    const w = mount(FeedFilters, { global: { plugins: [pinia, i18n, vuetify] } });
    await flushPromises();
    vi.useFakeTimers();
    w.findComponent<typeof VTextField>('[data-test="filter-q"]').vm.$emit("update:modelValue", null);
    w.findComponent<typeof VTextField>('[data-test="filter-location"]').vm.$emit("update:modelValue", null);
    await vi.advanceTimersByTimeAsync(299);
    expect(reset).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(reset).toHaveBeenCalledTimes(1);
    expect(feed.filter.q).toBeNull();
    expect(feed.filter.location).toBeNull();
    expect(feed.filter.radius_km).toBeNull();
    w.unmount();
  });
});
