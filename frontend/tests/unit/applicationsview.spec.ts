import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { createMemoryHistory, createRouter } from "vue-router";
import { api } from "@/api/client";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import ApplicationsView from "@/views/ApplicationsView.vue";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);

beforeEach(() => {
  localStorage.clear();
  get.mockReset();
  get.mockResolvedValue([
    {
      id: 7, status: "applied", created_at: "2026-10-01T10:00:00Z", updated_at: "", salary_expectation: null, channel: null,
      notes: null, last_status_change_at: null, posting: { id: 1, title: "Vue Dev", company: "ACME", location: "Berlin" },
    },
  ]);
});

describe("ApplicationsView", () => {
  it("shows active columns and cards; finished columns only after the switch", async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { render: () => null } }] });
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(ApplicationsView)) });
    const w = mount(Host, { global: { plugins: [createPinia(), vuetify, i18n, router] }, attachTo: document.body });
    await flushPromises();
    expect(w.findAll(".column")).toHaveLength(5);
    expect(w.find('[data-status="applied"] [data-id="7"]').text()).toContain("Vue Dev");
    const sw = w.find('input[type="checkbox"]');
    await sw.setValue(true);
    await flushPromises();
    expect(w.findAll(".column")).toHaveLength(8);
    expect((get.mock.calls.at(-1)![1] as { status: string[] }).status).toHaveLength(8);
    w.unmount();
  });
});
