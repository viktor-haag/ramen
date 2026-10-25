import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { api } from "@/api/client";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import DashboardView from "@/views/DashboardView.vue";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

const get = vi.mocked(api.get);

function run(id: number, minutesAgo: number, status: "ok" | "error" | "timeout", error: string | null = null) {
  return {
    id, profile_id: 1, profile_name: "ML", plugin: "arbeitsagentur", trigger: "schedule", status,
    started_at: new Date(Date.now() - minutesAgo * 60_000).toISOString(), finished_at: null,
    new_count: 3, total_count: 3, invalid_count: 0, error,
  };
}

async function mountWith(recent: ReturnType<typeof run>[], olderFailed: number) {
  get.mockResolvedValue({ new_count: 0, upcoming: [], stale: [], recent_runs: recent, older_failed_count: olderFailed } as never);
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, { default: () => h(DashboardView) }) });
  const w = mount(Host, { global: { plugins: [pinia, i18n, vuetify], stubs: { RouterLink: true } } });
  await flushPromises();
  return w;
}

beforeEach(() => {
  get.mockReset();
  i18n.global.locale.value = "en";
});

describe("DashboardView runs", () => {
  it("shows one list in the server's order, failures marked inline", async () => {
    const w = await mountWith([run(3, 1, "ok"), run(2, 5, "error", '"nlp": HTTP 429 Too Many Requests (x)'), run(1, 9, "ok")], 0);
    const items = w.findAll('[data-test="dash-runs"] .v-list-item');
    expect(items).toHaveLength(3);
    expect(items.map((i) => i.attributes("data-failed"))).toEqual(["false", "true", "false"]);
    expect(items[1].text()).toContain("HTTP 429");
    expect(w.find('[data-test="dash-older-failed"]').exists()).toBe(false);
  });

  it("summarizes older failures in one line instead of listing them", async () => {
    const w = await mountWith([run(3, 1, "ok")], 4);
    const line = w.get('[data-test="dash-older-failed"]');
    expect(line.text()).toContain("4");
    expect(w.findAll('[data-test="dash-runs"] .v-list-item').filter((i) => i.attributes("data-failed") === "true")).toHaveLength(0);
  });
});
