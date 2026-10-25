import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout, VSelect } from "vuetify/components";
import { ApiError, api, toQuery } from "@/api/client";
import type { FitOut, PostingOut } from "@/api/types";
import FeedFilters from "@/components/FeedFilters.vue";
import FitDot from "@/components/FitDot.vue";
import NotifySnackbar from "@/components/NotifySnackbar.vue";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useFeedStore } from "@/stores/feed";
import { useFitStore } from "@/stores/fit";
import { useNotifyStore } from "@/stores/notify";
import FeedView from "@/views/FeedView.vue";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

function fitOut(over: Partial<FitOut> = {}): FitOut {
  return { rating: "good", status: "done", error: null, explanation: "Matches well.", evaluated_at: "2026-10-24T10:00:00Z", outdated: false, ...over };
}

function posting(id: number, fit: FitOut | null = null): PostingOut {
  const now = new Date().toISOString();
  return {
    id, source: "x", external_id: String(id), url: null, title: `Job ${id}`, company: "ACME", location: "Berlin",
    lat: null, lon: null, description: null, published_at: null, first_seen_at: now, last_seen_at: now,
    employment_type: null, remote: null, contract_type: null, triage_status: "new", triaged_at: null,
    profile_ids: [], application_id: null, fit,
  };
}

let status = { profile: true, configured: true, active: 0 };
let items: PostingOut[] = [];

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  localStorage.clear();
  status = { profile: true, configured: true, active: 0 };
  items = [posting(1), posting(2)];
  get.mockReset();
  post.mockReset();
  get.mockImplementation((async (path: string) => {
    if (path === "/feed") return { items, total: items.length };
    if (path === "/fit/status") return status;
    if (path === "/fit/bulk/count") return { count: 7 };
    if (path === "/plugins" || path === "/profiles") return [];
    return [];
  }) as never);
  post.mockResolvedValue({ queued: 1, limit_exceeded: false });
});
afterEach(() => vi.useRealTimers());

function mountDot(fit: FitOut | null) {
  return mount(FitDot, { props: { fit }, global: { plugins: [vuetify, i18n] } });
}

describe("FitDot", () => {
  it.each([
    ["good", "fit-dot--good", "Good fit"],
    ["moderate", "fit-dot--moderate", "Partial fit"],
    ["poor", "fit-dot--poor", "Poor fit"],
  ] as const)("%s is a coloured dot with a text label", (rating, cls, label) => {
    const w = mountDot(fitOut({ rating }));
    const dot = w.find('[data-test="fit-dot"]');
    expect(dot.classes()).toContain(cls);
    expect(dot.attributes("aria-label")).toContain(label);
    expect(dot.attributes("role")).toBe("img");
  });

  it("each rating has its own glyph so colour is not the only signal", () => {
    const glyphs = (["good", "moderate", "poor"] as const).map((rating) => {
      const w = mountDot(fitOut({ rating }));
      const icon = w.find('[data-test="fit-dot-glyph"]');
      expect(icon.exists()).toBe(true);
      expect(icon.attributes("aria-hidden")).toBe("true");
      return icon.classes().find((c) => c.startsWith("mdi-") && c !== "mdi");
    });
    expect(glyphs).toEqual(["mdi-check", "mdi-minus", "mdi-close"]);
    expect(mountDot(null).find('[data-test="fit-dot-glyph"]').exists()).toBe(false);
  });

  it("stored row errors are reason-free and fit-specific (en + de)", () => {
    const label = (error: string) =>
      mountDot(fitOut({ status: "error", rating: null, error })).find('[data-test="fit-dot"]').attributes("aria-label")!;
    for (const loc of ["en", "de"] as const) {
      setLocale(loc);
      const noReason = i18n.global.t("common.noReason");
      for (const code of ["llm_unavailable", "llm_timeout", "llm_invalid_output", "llm_auth_failed", "llm_rate_limited", "llm_bad_request", "profile_missing", "llm_not_configured"]) {
        expect(label(code)).not.toContain(noReason);
        expect(label(code)).not.toContain("{reason}");
      }
    }
    setLocale("en");
    expect(label("llm_timeout")).toBe("Evaluation failed: The LLM provider did not answer in time.");
    expect(label("profile_missing")).toBe("Evaluation failed: Create your profile on the My profile page first.");
    expect(label("llm_not_configured")).toBe("Evaluation failed: Set up an LLM configuration in the settings first.");
  });

  it("no fit is a grey dot labelled as not evaluated", () => {
    const dot = mountDot(null).find('[data-test="fit-dot"]');
    expect(dot.classes()).toContain("fit-dot--none");
    expect(dot.attributes("aria-label")).toBe("Not evaluated");
  });

  it.each([["queued"], ["running"]] as const)("%s shows a spinner instead of the dot", (st) => {
    const w = mountDot(fitOut({ status: st, rating: "good" }));
    expect(w.find(".v-progress-circular").exists()).toBe(true);
    expect(w.find(".fit-dot--good").exists()).toBe(false);
    expect(w.find('[data-test="fit-dot"]').attributes("aria-label")).toBeTruthy();
  });

  it("an error shows a warning icon with the localised error text, falling back to errors.<code>", () => {
    let w = mountDot(fitOut({ status: "error", rating: null, error: "daily_limit" }));
    expect(w.find(".mdi-alert").exists()).toBe(true);
    expect(w.find('[data-test="fit-dot"]').attributes("aria-label")).toContain("Daily limit reached – not evaluated.");
    w = mountDot(fitOut({ status: "error", rating: null, error: "llm_timeout" }));
    expect(w.find('[data-test="fit-dot"]').attributes("aria-label")).toContain("The LLM provider did not answer in time");
    w = mountDot(fitOut({ status: "error", rating: null, error: "something_unknown" }));
    expect(w.find('[data-test="fit-dot"]').attributes("aria-label")).toContain("something_unknown");
  });

  it("an outdated result gets the ring style and says so", () => {
    const dot = mountDot(fitOut({ outdated: true })).find('[data-test="fit-dot"]');
    expect(dot.classes()).toContain("fit-dot--outdated");
    expect(dot.attributes("aria-label")).toContain("older version of your profile");
    expect(mountDot(fitOut()).find(".fit-dot--outdated").exists()).toBe(false);
  });
});

describe("fit filter and sort", () => {
  it("fit values and sort=fit reach the feed query and are persisted", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const feed = useFeedStore();
    const w = mount(FeedFilters, { global: { plugins: [pinia, i18n, vuetify] } });
    await flushPromises();
    w.findComponent<typeof VSelect>('[data-test="filter-fit"]').vm.$emit("update:modelValue", ["good", "none"]);
    await flushPromises();
    expect(feed.filter.fit).toEqual(["good", "none"]);
    w.findComponent<typeof VSelect>('[data-test="filter-sort"]').vm.$emit("update:modelValue", "fit");
    await flushPromises();
    expect(feed.filter.sort).toBe("fit");
    const params = get.mock.calls.filter((c) => c[0] === "/feed").at(-1)![1] as Record<string, unknown>;
    expect(params.fit).toEqual(["good", "none"]);
    expect(params.sort).toBe("fit");
    expect(toQuery(params)).toContain("fit=good&fit=none");
    expect(toQuery(params)).toContain("sort=fit");
    expect(JSON.parse(localStorage.getItem("jobtracker.feedFilter")!).filter).toMatchObject({ fit: ["good", "none"], sort: "fit" });
    w.unmount();
  });
});

function mountFeed() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const Host = defineComponent({ render: () => h(VLayout, null, { default: () => h(FeedView) }) });
  const w = mount(Host, { global: { plugins: [pinia, i18n, vuetify], stubs: { RouterLink: { props: ["to"], template: '<a :href="to"><slot /></a>' } } }, attachTo: document.body });
  return { w, pinia };
}

describe("bulk evaluation in FeedView", () => {
  it("confirm shows the count and posts with the UI language and the feed filter", async () => {
    setLocale("de");
    const { w } = mountFeed();
    await flushPromises();
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    expect(get.mock.calls.some((c) => c[0] === "/fit/bulk/count")).toBe(true);
    const dialog = document.querySelector('[data-test="confirm-ok"]')!;
    expect(document.querySelector(".v-card-title")!.textContent!.trim()).toBe("7 Stellen bewerten?");
    const counts = () => get.mock.calls.filter((c) => c[0] === "/fit/bulk/count").length;
    const countsBefore = counts();
    (dialog as HTMLElement).click();
    await flushPromises();
    expect(counts()).toBeGreaterThan(countsBefore); // the count is refreshed after the enqueue
    const call = post.mock.calls.find((c) => String(c[0]).startsWith("/fit/bulk"))!;
    expect(call[0]).toContain("lang=de");
    expect(call[0]).toContain("triage=new&triage=saved");
    expect(call[0]).not.toContain("offset=");
    expect(call[0]).not.toContain("limit=");
    w.unmount();
  });

  it("cancel posts nothing", async () => {
    const { w } = mountFeed();
    await flushPromises();
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    (document.querySelector('[data-test="confirm-cancel"]') as HTMLElement).click();
    await flushPromises();
    expect(post).not.toHaveBeenCalled();
    w.unmount();
  });

  it("is disabled with a link to My profile when there is no profile", async () => {
    status = { profile: false, configured: true, active: 0 };
    const { w } = mountFeed();
    await flushPromises();
    expect(w.find('[data-test="fit-bulk"]').attributes("disabled")).toBeDefined();
    const hint = w.find('[data-test="fit-hint"]');
    expect(hint.text()).toContain("Create your profile on the My profile page first.");
    expect(hint.find("a").attributes("href")).toBe("/me");
    w.unmount();
  });

  it("is disabled with a link to the settings when no LLM is configured", async () => {
    status = { profile: true, configured: false, active: 0 };
    const { w } = mountFeed();
    await flushPromises();
    expect(w.find('[data-test="fit-bulk"]').attributes("disabled")).toBeDefined();
    expect(w.find('[data-test="fit-hint"] a').attributes("href")).toBe("/settings");
    w.unmount();
  });

  it("409 daily_limit_reached shows the error text", async () => {
    post.mockRejectedValue(new ApiError(409, "daily_limit_reached", {}, "limit"));
    const { w, pinia } = mountFeed();
    await flushPromises();
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    (document.querySelector('[data-test="confirm-ok"]') as HTMLElement).click();
    await flushPromises();
    const notify = useNotifyStore(pinia);
    expect(notify.message).toBe("Global daily limit reached.");
    expect(notify.color).toBe("error");
    w.unmount();
  });

  it("409 daily_limit_reached with scope config names the configuration", async () => {
    post.mockRejectedValue(new ApiError(409, "daily_limit_reached", { scope: "config", config_name: "Main" }, "limit"));
    const { w, pinia } = mountFeed();
    await flushPromises();
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    (document.querySelector('[data-test="confirm-ok"]') as HTMLElement).click();
    await flushPromises();
    expect(useNotifyStore(pinia).message).toBe("Daily limit of \u201cMain\u201d reached.");
    w.unmount();
  });

  it("409 profile_missing shows the fit-specific text", async () => {
    post.mockRejectedValue(new ApiError(409, "profile_missing", {}, "no profile"));
    const { w, pinia } = mountFeed();
    await flushPromises();
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    (document.querySelector('[data-test="confirm-ok"]') as HTMLElement).click();
    await flushPromises();
    expect(useNotifyStore(pinia).message).toBe("Create your profile on the My profile page first.");
    w.unmount();
  });
});

describe("fit store", () => {
  it("single evaluate posts with lang and warns when the daily limit is exceeded", async () => {
    setActivePinia(createPinia());
    const fit = useFitStore();
    post.mockResolvedValue({ queued: 1, limit_exceeded: true });
    await fit.evaluate(5);
    expect(post).toHaveBeenCalledWith("/fit/5?lang=en");
    const notify = useNotifyStore();
    expect(notify.visible).toBe(true);
    expect(notify.color).toBe("warning");
    expect(notify.message).toContain("daily limit");
  });

  it("single evaluate without limit warning stays quiet", async () => {
    setActivePinia(createPinia());
    await useFitStore().evaluate(5);
    expect(useNotifyStore().visible).toBe(false);
  });

  it("polls active items every 2 s, patches them in place and stops when none is active", async () => {
    vi.useFakeTimers();
    items = [posting(1, fitOut({ status: "queued", rating: null })), posting(2, fitOut()), posting(3, fitOut({ status: "running", rating: null }))];
    const { w, pinia } = mountFeed();
    await flushPromises();
    const feed = useFeedStore(pinia);
    expect(feed.items).toHaveLength(3);
    const fitCalls = () => get.mock.calls.filter((c) => c[0] === "/fit");
    expect(fitCalls()).toHaveLength(0);

    get.mockImplementation((async (path: string) => {
      if (path === "/fit") return [
        { posting_id: 1, fit: fitOut({ rating: "poor", explanation: "No." }) },
        { posting_id: 3, fit: fitOut({ status: "running", rating: null }) },
      ];
      if (path === "/fit/status") return status;
      if (path === "/fit/bulk/count") return { count: 0 };
      return [];
    }) as never);
    await vi.advanceTimersByTimeAsync(1999);
    expect(fitCalls()).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(fitCalls()).toHaveLength(1);
    expect(fitCalls()[0]![1]).toEqual({ ids: "1,3" });
    expect(feed.items[0]!.fit).toMatchObject({ status: "done", rating: "poor" });
    expect(feed.items[2]!.fit!.status).toBe("running");

    get.mockImplementation((async (path: string) => {
      if (path === "/fit") return [{ posting_id: 3, fit: fitOut({ rating: "moderate" }) }];
      if (path === "/fit/bulk/count") return { count: 0 };
      return [];
    }) as never);
    await vi.advanceTimersByTimeAsync(2000);
    expect(fitCalls()).toHaveLength(2);
    expect(fitCalls()[1]![1]).toEqual({ ids: "3" });
    expect(feed.items[2]!.fit!.status).toBe("done");

    await vi.advanceTimersByTimeAsync(10000);
    expect(fitCalls()).toHaveLength(2);
    w.unmount();
  });

  it("never runs more than one timer and stops on unmount", async () => {
    vi.useFakeTimers();
    items = [posting(1, fitOut({ status: "queued", rating: null }))];
    get.mockImplementation((async (path: string) => {
      if (path === "/feed") return { items, total: 1 };
      if (path === "/fit") return [{ posting_id: 1, fit: fitOut({ status: "queued", rating: null }) }];
      if (path === "/fit/status") return status;
      if (path === "/fit/bulk/count") return { count: 0 };
      return [];
    }) as never);
    const set = vi.spyOn(globalThis, "setInterval");
    const clear = vi.spyOn(globalThis, "clearInterval");
    const { w, pinia } = mountFeed();
    await flushPromises();
    const feed = useFeedStore(pinia);
    feed.items[0]!.fit = fitOut({ status: "running", rating: null });
    feed.items.push(posting(9, fitOut({ status: "queued", rating: null })));
    await flushPromises();
    const pollers = () => set.mock.calls.filter((c) => c[1] === 2000);
    expect(pollers()).toHaveLength(1);
    w.unmount();
    await flushPromises();
    const handle = set.mock.results[set.mock.calls.findIndex((c) => c[1] === 2000)]!.value;
    expect(clear.mock.calls.filter((c) => c[0] === handle)).toHaveLength(1);
    const fitCalls = get.mock.calls.filter((c) => c[0] === "/fit").length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(get.mock.calls.filter((c) => c[0] === "/fit")).toHaveLength(fitCalls);
    set.mockRestore();
    clear.mockRestore();
  });
});

describe("cancel evaluation", () => {
  it("store: posts /fit/cancel, refreshes status and the fits of active items, notifies", async () => {
    items = [posting(1, fitOut({ status: "queued", rating: null })), posting(2, fitOut()), posting(3, fitOut({ status: "running" }))];
    status = { profile: true, configured: true, active: 2 };
    const { w, pinia } = mountFeed();
    await flushPromises();
    const fit = useFitStore(pinia);
    const feed = useFeedStore(pinia);
    expect(fit.status.active).toBe(2);
    post.mockImplementation((async (path: string) => (path === "/fit/cancel" ? { cancelled: 2 } : { queued: 1, limit_exceeded: false })) as never);
    get.mockImplementation((async (path: string, params?: { ids?: string }) => {
      if (path === "/fit/status") return { profile: true, configured: true, active: 0 };
      if (path === "/fit") return String(params?.ids).split(",").map((id) => ({ posting_id: Number(id), fit: id === "1" ? null : fitOut({ rating: "poor" }) }));
      if (path === "/fit/bulk/count") return { count: 0 };
      return [];
    }) as never);
    expect(await fit.cancel()).toBe(true);
    expect(post).toHaveBeenCalledWith("/fit/cancel");
    expect(fit.status.active).toBe(0);
    const fitCall = get.mock.calls.filter((c) => c[0] === "/fit").at(-1)!;
    expect(fitCall[1]).toEqual({ ids: "1,3" });
    expect(feed.items[0]!.fit).toBeNull();
    expect(feed.items[2]!.fit).toMatchObject({ status: "done", rating: "poor" });
    const notify = useNotifyStore(pinia);
    expect(notify.color).toBe("success");
    expect(notify.message).toBe("Evaluation cancelled");
    w.unmount();
  });

  it("store: a failing cancel shows the error and returns false", async () => {
    setActivePinia(createPinia());
    post.mockRejectedValue(new ApiError(500, null, {}, "boom"));
    expect(await useFitStore().cancel()).toBe(false);
    expect(useNotifyStore().color).toBe("error");
  });

  it("the poll reloads /fit/status on every tick, quietly", async () => {
    vi.useFakeTimers();
    items = [posting(1, fitOut({ status: "queued", rating: null }))];
    status = { profile: true, configured: true, active: 1 };
    const { w, pinia } = mountFeed();
    await flushPromises();
    const statusCalls = () => get.mock.calls.filter((c) => c[0] === "/fit/status").length;
    const before = statusCalls();
    get.mockImplementation((async (path: string) => {
      if (path === "/fit") return [{ posting_id: 1, fit: fitOut({ status: "running", rating: null }) }];
      if (path === "/fit/status") return { profile: true, configured: true, active: 5 };
      if (path === "/fit/bulk/count") return { count: 0 };
      return [];
    }) as never);
    await vi.advanceTimersByTimeAsync(2000);
    expect(statusCalls()).toBe(before + 1);
    expect(useFitStore(pinia).status.active).toBe(5);
    get.mockImplementation((async (path: string) => {
      if (path === "/fit") return [{ posting_id: 1, fit: fitOut({ status: "running", rating: null }) }];
      if (path === "/fit/status") throw new ApiError(500, null, {}, "status broke");
      return [];
    }) as never);
    const err = vi.spyOn(useNotifyStore(pinia), "error");
    await vi.advanceTimersByTimeAsync(2000);
    expect(err).not.toHaveBeenCalled(); // a failing status reload does not disturb the poll
    expect(useFitStore(pinia).status.active).toBe(5);
    w.unmount();
  });

  it("keeps reloading /fit/status while active > 0 even without active items, and stops at 0", async () => {
    vi.useFakeTimers();
    status = { profile: true, configured: true, active: 4 }; // e.g. a bulk run over items that are not loaded
    const { w, pinia } = mountFeed();
    await flushPromises();
    const statusCalls = () => get.mock.calls.filter((c) => c[0] === "/fit/status").length;
    const fitCalls = () => get.mock.calls.filter((c) => c[0] === "/fit").length;
    const before = statusCalls();
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(2000);
    expect(statusCalls()).toBe(before + 2);
    expect(fitCalls()).toBe(0);
    status = { profile: true, configured: true, active: 0 };
    await vi.advanceTimersByTimeAsync(2000);
    expect(useFitStore(pinia).status.active).toBe(0);
    const after = statusCalls();
    await vi.advanceTimersByTimeAsync(10000);
    expect(statusCalls()).toBe(after);
    w.unmount();
  });

  it("after a cancel the button disappears once the server stops reporting old jobs as active", async () => {
    vi.useFakeTimers();
    items = [posting(1, fitOut({ status: "running", rating: null }))];
    status = { profile: true, configured: true, active: 1 };
    const { w } = mountFeed();
    await flushPromises();
    expect(w.find('[data-test="fit-cancel"]').exists()).toBe(true);
    get.mockImplementation((async (path: string, params?: { ids?: string }) => {
      if (path === "/fit/status") return status; // still 1: the old job has not returned from the LLM yet
      if (path === "/fit") return String(params?.ids).split(",").map((id) => ({ posting_id: Number(id), fit: null }));
      if (path === "/fit/bulk/count") return { count: 1 };
      return [];
    }) as never);
    post.mockResolvedValue({ cancelled: 1 });
    await w.find('[data-test="fit-cancel"]').trigger("click");
    await vi.advanceTimersByTimeAsync(0);
    expect(w.find('[data-test="fit-cancel"]').exists()).toBe(true);
    status = { profile: true, configured: true, active: 0 };
    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();
    expect(w.find('[data-test="fit-cancel"]').exists()).toBe(false);
    w.unmount();
  });

  it("status is reloaded after single and bulk evaluate", async () => {
    setActivePinia(createPinia());
    const fit = useFitStore();
    const statusCalls = () => get.mock.calls.filter((c) => c[0] === "/fit/status").length;
    await fit.evaluate(5);
    expect(statusCalls()).toBe(1);
    await fit.bulkEvaluate();
    expect(statusCalls()).toBe(2);
  });

  it("FeedView: the button is hidden without active evaluations and shows N otherwise", async () => {
    const { w } = mountFeed();
    await flushPromises();
    expect(w.find('[data-test="fit-cancel"]').exists()).toBe(false);
    status = { ...status, active: 3 };
    await useFitStore().loadStatus();
    await flushPromises();
    const btn = w.find('[data-test="fit-cancel"]');
    expect(btn.exists()).toBe(true);
    expect(btn.text()).toContain("Cancel evaluation (3)");
    w.unmount();
  });

  it("FeedView: German label and click calls cancel without a dialog", async () => {
    setLocale("de");
    status.active = 2;
    const { w, pinia } = mountFeed();
    await flushPromises();
    const btn = w.find('[data-test="fit-cancel"]');
    expect(btn.text()).toContain("Bewertung abbrechen (2)");
    const spy = vi.spyOn(useFitStore(pinia), "cancel");
    post.mockResolvedValue({ cancelled: 2 });
    await btn.trigger("click");
    await flushPromises();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/fit/cancel");
    expect(document.querySelector('[data-test="confirm-ok"]')).toBeNull();
    w.unmount();
  });
});

describe("bulk button count", () => {
  it("shows (N) once the count is loaded, without N while unknown, and refreshes after a bulk enqueue", async () => {
    let resolveCount: (v: { count: number }) => void = () => {};
    const baseline = get.getMockImplementation()!;
    get.mockImplementation((async (path: string, params?: Record<string, unknown>) => {
      if (path === "/fit/bulk/count") return new Promise((r) => (resolveCount = r));
      return baseline(path, params);
    }) as never);
    const { w } = mountFeed();
    await flushPromises();
    const btn = () => w.find('[data-test="fit-bulk"]').text();
    expect(btn()).toBe("Evaluate all visible");
    await vi.waitFor(() => expect(get.mock.calls.some((c) => c[0] === "/fit/bulk/count")).toBe(true));
    resolveCount({ count: 4 });
    await vi.waitFor(() => expect(btn()).toBe("Evaluate all visible (4)"));

    const before = get.mock.calls.filter((c) => c[0] === "/fit/bulk/count").length;
    get.mockImplementation((async (path: string, params?: Record<string, unknown>) => {
      if (path === "/fit/bulk/count") return { count: 0 };
      return baseline(path, params);
    }) as never);
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    // the count is 0 now: no dialog, and the label has been refreshed
    expect(get.mock.calls.filter((c) => c[0] === "/fit/bulk/count").length).toBeGreaterThan(before);
    await vi.waitFor(() => expect(btn()).toBe("Evaluate all visible (0)"));
    w.unmount();
  });

  it("refreshes the count quietly after a single evaluate and when a polled posting fails, not when it is done", async () => {
    vi.useFakeTimers();
    let count = 5;
    items = [posting(1), posting(2, fitOut({ status: "queued", rating: null }))];
    let polled: FitOut = fitOut({ status: "queued", rating: null });
    get.mockImplementation((async (path: string, params?: Record<string, unknown>) => {
      if (path === "/feed") return { items, total: items.length };
      if (path === "/fit/status") return status;
      if (path === "/fit/bulk/count") return { count };
      if (path === "/fit") return String(params?.ids).split(",").map((id) => ({ posting_id: Number(id), fit: id === "1" ? fitOut({ status: "queued", rating: null }) : polled }));
      return [];
    }) as never);
    const { w, pinia } = mountFeed();
    await flushPromises();
    await vi.advanceTimersByTimeAsync(400);
    const btn = () => w.find('[data-test="fit-bulk"]').text();
    expect(btn()).toBe("Evaluate all visible (5)");

    // single evaluate: the posting is no longer counted
    count = 4;
    await useFitStore(pinia).evaluate(1);
    await vi.advanceTimersByTimeAsync(400);
    expect(btn()).toBe("Evaluate all visible (4)");

    // the poll sees posting 2 finish with a result: the count cannot change, no recount
    const counts = () => get.mock.calls.filter((c) => c[0] === "/fit/bulk/count").length;
    const before = counts();
    polled = fitOut();
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(400);
    expect(counts()).toBe(before);

    // posting 2 is re-evaluated and fails: it is a bulk candidate again, the count is refreshed
    count = 3;
    polled = fitOut({ status: "queued", rating: null });
    await useFitStore(pinia).evaluate(2);
    await vi.advanceTimersByTimeAsync(400);
    count = 4;
    polled = fitOut({ status: "error", rating: null, error: "llm_timeout" });
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(400);
    expect(btn()).toBe("Evaluate all visible (4)");
    w.unmount();
  });

  it("count 0 shows the 'nothing to evaluate' message instead of the dialog", async () => {
    get.mockImplementation((async (path: string) => {
      if (path === "/feed") return { items, total: items.length };
      if (path === "/fit/status") return status;
      if (path === "/fit/bulk/count") return { count: 0 };
      return [];
    }) as never);
    const { w, pinia } = mountFeed();
    await flushPromises();
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    expect(useNotifyStore(pinia).message).toBe("Nothing to evaluate: all matching postings already have a result, or are being evaluated right now.");
    expect(document.querySelector('[data-test="confirm-ok"]')).toBeNull();
    w.unmount();
  });

  it("a failing count keeps the error visible and shows neither dialog nor 'none'", async () => {
    get.mockImplementation((async (path: string) => {
      if (path === "/feed") return { items, total: items.length };
      if (path === "/fit/status") return status;
      if (path === "/fit/bulk/count") throw new ApiError(500, null, {}, "count broke");
      return [];
    }) as never);
    const { w, pinia } = mountFeed();
    await flushPromises();
    const notify = useNotifyStore(pinia);
    notify.visible = false;
    await w.find('[data-test="fit-bulk"]').trigger("click");
    await flushPromises();
    expect(notify.visible).toBe(true);
    expect(notify.message).toBe("count broke");
    expect(notify.color).toBe("error");
    expect(document.querySelector('[data-test="confirm-ok"]')).toBeNull();
    w.unmount();
  });
});

describe("status hint", () => {
  it("shows no hint while the status is unknown or when loading it failed", async () => {
    get.mockImplementation((async (path: string) => {
      if (path === "/feed") return { items, total: items.length };
      if (path === "/fit/status") throw new ApiError(500, null, {}, "status broke");
      return [];
    }) as never);
    const { w, pinia } = mountFeed();
    await flushPromises();
    expect(useFitStore(pinia).statusLoaded).toBe(false);
    expect(w.find('[data-test="fit-hint"]').exists()).toBe(false);
    expect(useNotifyStore(pinia).message).toBe("status broke");
    w.unmount();
  });
});

describe("snackbar action", () => {
  it("profile_missing and llm_not_configured carry a link action; the snackbar renders it and routes", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const notify = useNotifyStore();
    const fit = useFitStore();
    post.mockRejectedValue(new ApiError(409, "profile_missing", {}, "x"));
    await fit.evaluate(1);
    expect(notify.action).toEqual({ label: "Open My profile", to: "/me" });
    post.mockRejectedValue(new ApiError(409, "llm_not_configured", {}, "x"));
    await fit.evaluate(1);
    expect(notify.action).toEqual({ label: "Open settings", to: "/settings" });

    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { render: () => null } }] });
    const Host = defineComponent({ render: () => h(VLayout, null, { default: () => h(NotifySnackbar) }) });
    const w = mount(Host, { global: { plugins: [pinia, i18n, vuetify, router] }, attachTo: document.body });
    await flushPromises();
    const link = document.querySelector('[data-test="notify-action"]') as HTMLElement;
    expect(link).not.toBeNull();
    expect(link.textContent).toContain("Open settings");
    link.click();
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe("/settings"));
    w.unmount();
  });

  it("a plain message clears a previous action", () => {
    setActivePinia(createPinia());
    const notify = useNotifyStore();
    notify.show("a", "error", { label: "x", to: "/me" });
    notify.show("b");
    expect(notify.action).toBeNull();
  });
});

describe("polling robustness", () => {
  function pollSetup() {
    vi.useFakeTimers();
    items = [posting(1, fitOut({ status: "queued", rating: null }))];
    let mode: "fail" | "ok" = "fail";
    get.mockImplementation((async (path: string) => {
      if (path === "/feed") return { items, total: 1 };
      if (path === "/fit/status") return status;
      if (path === "/fit/bulk/count") return { count: 0 };
      if (path === "/fit") {
        if (mode === "fail") throw new ApiError(500, null, {}, "poll broke");
        return [{ posting_id: 1, fit: fitOut() }];
      }
      return [];
    }) as never);
    return { setMode: (m: "fail" | "ok") => (mode = m) };
  }
  const fitCalls = () => get.mock.calls.filter((c) => c[0] === "/fit").length;

  it("reports a failing poll once, recovers on success and resets the failure count", async () => {
    const ctl = pollSetup();
    const { w, pinia } = mountFeed();
    await flushPromises();
    const notify = useNotifyStore(pinia);
    const err = vi.spyOn(notify, "error");
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(2000);
    expect(fitCalls()).toBe(2);
    expect(err).toHaveBeenCalledTimes(1);
    ctl.setMode("ok");
    await vi.advanceTimersByTimeAsync(2000);
    expect(useFeedStore(pinia).items[0]!.fit!.status).toBe("done");
    w.unmount();
  });

  it("after 5 consecutive failures polling stops (one report) and resumes on the next feed load", async () => {
    const ctl = pollSetup();
    const { w, pinia } = mountFeed();
    await flushPromises();
    const notify = useNotifyStore(pinia);
    const err = vi.spyOn(notify, "error");
    await vi.advanceTimersByTimeAsync(2000 * 5);
    expect(fitCalls()).toBe(5);
    await vi.advanceTimersByTimeAsync(2000 * 5);
    expect(fitCalls()).toBe(5);
    expect(err).toHaveBeenCalledTimes(1);

    ctl.setMode("ok");
    await useFeedStore(pinia).reset();
    await vi.advanceTimersByTimeAsync(2000);
    expect(fitCalls()).toBe(6);
    w.unmount();
  });

  it("a successful loadMore resumes suspended polling", async () => {
    vi.useFakeTimers();
    items = [posting(1, fitOut({ status: "queued", rating: null }))];
    const page2 = posting(2);
    get.mockImplementation((async (path: string, params?: Record<string, unknown>) => {
      if (path === "/feed") return params?.offset ? { items: [page2], total: 2 } : { items, total: 2 };
      if (path === "/fit/status") return status;
      if (path === "/fit/bulk/count") return { count: 0 };
      if (path === "/fit") throw new ApiError(500, null, {}, "poll broke");
      return [];
    }) as never);
    const { w, pinia } = mountFeed();
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2000 * 6);
    expect(fitCalls()).toBe(5);
    await useFeedStore(pinia).loadMore();
    await vi.advanceTimersByTimeAsync(2000);
    expect(fitCalls()).toBe(6);
    w.unmount();
  });

  it("ignores a stale poll result that arrives after a newer one", async () => {
    setActivePinia(createPinia());
    const feed = useFeedStore();
    const fit = useFitStore();
    feed.items = [posting(1, fitOut({ status: "queued", rating: null }))];
    const resolvers: ((v: unknown) => void)[] = [];
    get.mockImplementation((() => new Promise((r) => resolvers.push(r))) as never);
    const a = fit.refresh([1]);
    const b = fit.refresh([1]);
    resolvers[1]!([{ posting_id: 1, fit: fitOut({ rating: "good" }) }]);
    await b;
    resolvers[0]!([{ posting_id: 1, fit: fitOut({ status: "running", rating: null }) }]);
    await a;
    expect(feed.items[0]!.fit).toMatchObject({ status: "done", rating: "good" });
  });
});
