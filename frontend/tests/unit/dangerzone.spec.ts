import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick } from "vue";
import { VLayout } from "vuetify/components";
import { ApiError, api } from "@/api/client";
import DangerZone from "@/components/DangerZone.vue";
import TypeToConfirmDialog from "@/components/TypeToConfirmDialog.vue";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { router } from "@/router";
import { useApplicationDetailStore } from "@/stores/applicationDetail";
import { useApplicationsStore } from "@/stores/applications";
import { useDashboardStore } from "@/stores/dashboard";
import { useFeedStore } from "@/stores/feed";
import { useFitStore } from "@/stores/fit";
import { useLlmStore } from "@/stores/llm";
import { useMeStore } from "@/stores/me";
import { useNotifyStore } from "@/stores/notify";
import { useSettingsPluginsStore } from "@/stores/plugins";
import { useProfilesStore } from "@/stores/profiles";
import { useRunsStore } from "@/stores/runs";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

beforeAll(() => {
  // jsdom has no visualViewport (used by Vuetify's overlay positioning)
  vi.stubGlobal("visualViewport", { width: 1024, height: 768, offsetLeft: 0, offsetTop: 0, addEventListener() {}, removeEventListener() {} });
});

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  get.mockReset();
  post.mockReset();
  get.mockResolvedValue([] as never);
  document.body.innerHTML = "";
});

const q = (sel: string) => document.body.querySelector(sel) as HTMLElement | null;
async function typeInto(text: string) {
  const input = q("[data-test=ttc-input] input") as HTMLInputElement;
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await nextTick();
}
const okDisabled = () => (q("[data-test=ttc-ok]") as HTMLButtonElement).disabled;

describe("TypeToConfirmDialog", () => {
  function mountDialog() {
    const Host = defineComponent({
      render: () => h(VLayout, null, () => h(TypeToConfirmDialog, { modelValue: true, title: "T", text: "X", busy: false })),
    });
    return mount(Host, { global: { plugins: [vuetify, i18n] }, attachTo: document.body });
  }

  it("enables confirm only for the exact English word", async () => {
    const w = mountDialog();
    expect(okDisabled()).toBe(true);
    for (const wrong of ["delete", "LÖSCHEN", "DELET", ""]) {
      await typeInto(wrong);
      expect(okDisabled()).toBe(true);
    }
    await typeInto("DELETE");
    expect(okDisabled()).toBe(false);
    await typeInto("  DELETE ");
    expect(okDisabled()).toBe(false);
    w.unmount();
  });

  it("uses the German word in the German locale", async () => {
    setLocale("de");
    const w = mountDialog();
    await typeInto("LÖSCHE");
    expect(okDisabled()).toBe(true);
    await typeInto("DELETE");
    expect(okDisabled()).toBe(true);
    await typeInto("LÖSCHEN");
    expect(okDisabled()).toBe(false);
    w.unmount();
  });
});

describe("DangerZone", () => {
  async function mountZone() {
    const pinia = createPinia();
    setActivePinia(pinia);
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(DangerZone)) });
    const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
    await flushPromises();
    return w;
  }
  async function confirm(trigger: string) {
    (q(`[data-test=${trigger}]`) as HTMLElement).click();
    await flushPromises();
    await typeInto("DELETE");
    (q("[data-test=ttc-ok]") as HTMLElement).click();
    await flushPromises();
  }

  it("calls clear-feed only after confirmation and reloads feed and dashboard", async () => {
    post.mockResolvedValue({ deleted_postings: 12, deleted_runs: 3 } as never);
    const w = await mountZone();
    (q("[data-test=danger-clear-feed]") as HTMLElement).click();
    await flushPromises();
    expect(post).not.toHaveBeenCalled();
    await typeInto("DELETE");
    (q("[data-test=ttc-ok]") as HTMLElement).click();
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/admin/clear-feed");
    expect(get).toHaveBeenCalledWith("/feed", expect.anything());
    expect(get).toHaveBeenCalledWith("/dashboard");
    const notify = useNotifyStore();
    expect(notify.message).toContain("12");
    expect(notify.message).toContain("3");
    expect(notify.color).toBe("success");
    w.unmount();
  });

  it("delete-profile texts mention fit evaluations (en + de) and the success message counts them", async () => {
    for (const [loc, word] of [["en", "fit evaluations"], ["de", "Fit-Bewertungen"]] as const) {
      setLocale(loc);
      expect(i18n.global.t("settings.danger.deleteProfileHint")).toContain(word);
      expect(i18n.global.t("settings.danger.deleteProfileConfirm")).toContain(word);
    }
    setLocale("en");
    post.mockResolvedValue({ deleted_documents: 4, deleted_fits: 7 } as never);
    const w = await mountZone();
    await confirm("danger-delete-profile");
    expect(post).toHaveBeenCalledWith("/admin/delete-profile");
    expect(useNotifyStore().message).toContain("4 documents and 7 fit evaluations");
    w.unmount();
  });

  it.each([["danger-delete-profile", { deleted_documents: 1, deleted_fits: 2 }], ["danger-reset", { deleted: {} }]])(
    "%s clears known fits and the fit of loaded feed items",
    async (trigger, res) => {
      post.mockResolvedValue(res as never);
      vi.spyOn(router, "push").mockResolvedValue(undefined);
      const w = await mountZone();
      const feed = useFeedStore();
      const fit = useFitStore();
      const done = { rating: "good", status: "done", error: null, explanation: "x", evaluated_at: null, outdated: false } as never;
      feed.items = [{ id: 3, fit: done } as never];
      fit.offer(3, done);
      expect(fit.fitOf(3)).not.toBeUndefined();
      await confirm(trigger);
      expect(fit.fitOf(3)).toBeUndefined();
      if (trigger === "danger-delete-profile") expect(feed.items[0]!.fit).toBeNull();
      w.unmount();
    },
  );

  it("delete-profile also clears the cached application detail and the bulk count", async () => {
    post.mockResolvedValue({ deleted_documents: 0, deleted_fits: 1 } as never);
    const w = await mountZone();
    const detail = useApplicationDetailStore();
    const fit = useFitStore();
    detail.app = { id: 5, posting: { id: 3, fit: { rating: "good", status: "done" } } } as never;
    fit.bulkTotal = 4;
    await confirm("danger-delete-profile");
    expect(detail.app).toBeNull();
    expect(fit.bulkTotal).toBeNull();
    w.unmount();
  });

  it("reset clears the stores, shows the total and navigates to the dashboard", async () => {
    post.mockResolvedValue({ deleted: { job_posting: 5, application: 2, search_profile: 1 } } as never);
    const push = vi.spyOn(router, "push").mockResolvedValue(undefined);
    const w = await mountZone();
    const feed = useFeedStore();
    const apps = useApplicationsStore();
    const profiles = useProfilesStore();
    const dash = useDashboardStore();
    feed.items = [{ id: 1 }] as never;
    feed.total = 1;
    apps.items = [{ id: 1 }] as never;
    profiles.items = [{ id: 1 }] as never;
    dash.data = {} as never;
    const me = useMeStore();
    me.documents = [{ id: 1 }] as never;
    me.profile = { version: 1 } as never;
    const llm = useLlmStore();
    llm.configs = [{ id: 1 }] as never;
    llm.loaded = true;
    const plugins = useSettingsPluginsStore();
    await confirm("danger-reset");
    expect(post).toHaveBeenCalledWith("/admin/reset");
    expect(feed.items).toEqual([]);
    expect(feed.total).toBe(0);
    expect(apps.items).toEqual([]);
    expect(profiles.items).toEqual([]);
    expect(dash.data).toBeNull();
    expect(me.documents).toEqual([]);
    expect(me.profile).toBeNull();
    expect(llm.configs).toEqual([]);
    expect(llm.loaded).toBe(false);
    expect(get).toHaveBeenCalledWith("/plugins");
    expect(plugins.loaded).toBe(true);
    expect(useNotifyStore().message).toContain("8");
    expect(push).toHaveBeenCalledWith("/");
    push.mockRestore();
    w.unmount();
  });

  it("reset also restores the default feed filter and persists it", async () => {
    post.mockResolvedValue({ deleted: {} } as never);
    const push = vi.spyOn(router, "push").mockResolvedValue(undefined);
    const w = await mountZone();
    const feed = useFeedStore();
    feed.filter = { triage: ["dismissed"], source: ["x"], profile_id: 3 } as never;
    feed.foundRange = "7d";
    await confirm("danger-reset");
    expect(feed.filter).toEqual({ triage: ["new", "saved"], source: [] });
    expect(feed.foundRange).toBe("all");
    expect(JSON.parse(localStorage.getItem("jobtracker.feedFilter")!)).toEqual({ filter: { triage: ["new", "saved"], source: [] }, foundRange: "all" });
    push.mockRestore();
    w.unmount();
  });

  it("clear-feed also drops profile run history/results and the last refresh result", async () => {
    post.mockResolvedValue({ deleted_postings: 1, deleted_runs: 2 } as never);
    const w = await mountZone();
    const profiles = useProfilesStore();
    const runs = useRunsStore();
    profiles.history = { 1: [{ id: 9 }] } as never;
    profiles.results = { 1: { newCount: 2, failed: 0 } } as never;
    runs.lastResult = { newCount: 2, failed: 0, alreadyRunning: false };
    await confirm("danger-clear-feed");
    expect(profiles.history).toEqual({});
    expect(profiles.results).toEqual({});
    expect(runs.lastResult).toBeNull();
    w.unmount();
  });

  it("clear-feed still reports success when the follow-up reload fails", async () => {
    post.mockResolvedValue({ deleted_postings: 1, deleted_runs: 2 } as never);
    const w = await mountZone();
    get.mockRejectedValue(new Error("reload failed"));
    const show = vi.spyOn(useNotifyStore(), "show");
    await confirm("danger-clear-feed");
    // success is announced first; the reload error is reported separately by the stores
    expect(show.mock.calls[0]![1]).toBe("success");
    expect(show.mock.calls[0]![0]).toContain("2");
    expect(post).toHaveBeenCalledWith("/admin/clear-feed");
    w.unmount();
  });

  it("shows the translated runs_active error and keeps the stores on 409", async () => {
    post.mockRejectedValue(new ApiError(409, "runs_active", {}, "Runs are active"));
    const push = vi.spyOn(router, "push").mockResolvedValue(undefined);
    const w = await mountZone();
    const feed = useFeedStore();
    feed.items = [{ id: 1 }] as never;
    await confirm("danger-reset");
    expect(useNotifyStore().message).toBe("Search runs are active. Wait until they have finished.");
    expect(useNotifyStore().color).toBe("error");
    expect(feed.items).toHaveLength(1);
    expect(push).not.toHaveBeenCalled();
    push.mockRestore();
    w.unmount();
  });
});
