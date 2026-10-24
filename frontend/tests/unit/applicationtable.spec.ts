import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { createMemoryHistory, createRouter } from "vue-router";
import { api } from "@/api/client";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import ApplicationTable from "@/components/ApplicationTable.vue";
import { useApplicationsStore } from "@/stores/applications";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);

beforeEach(() => {
  localStorage.clear();
  get.mockReset();
  get.mockResolvedValue([]);
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

async function setup() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useApplicationsStore();
  store.items = [
    {
      id: 7, status: "applied", created_at: "2026-10-01T10:00:00Z", updated_at: "", salary_expectation: null, channel: null,
      notes: null, last_status_change_at: null, posting: { id: 1, title: "Vue Dev", company: "ACME", location: "Berlin" },
    } as never,
  ];
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { render: () => null } }] });
  const push = vi.spyOn(router, "push");
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(ApplicationTable)) });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n, router] }, attachTo: document.body });
  await flushPromises();
  return { w, store, push };
}

describe("ApplicationTable", () => {
  it("search: 300 ms debounce, trim, clearable sets null -> empty q", async () => {
    const { w, store } = await setup();
    const input = w.find("input[type=text]");
    await input.setValue("  vue ");
    vi.advanceTimersByTime(299);
    expect(get).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    await flushPromises();
    expect(get).toHaveBeenCalledTimes(1);
    expect((get.mock.calls[0]![1] as { q: string }).q).toBe("vue");
    expect(store.q).toBe("vue");

    await w.find(".v-field__clearable .v-icon").trigger("click"); // clearable -> null
    vi.advanceTimersByTime(300);
    await flushPromises();
    expect(get).toHaveBeenCalledTimes(2);
    expect(store.q).toBe("");
    w.unmount();
  });

  it("row click navigates to the detail page", async () => {
    const { w, push } = await setup();
    await w.find("tbody tr").trigger("click");
    expect(push).toHaveBeenCalledWith("/applications/7");
    w.unmount();
  });
});
