import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouterLinkStub } from "@vue/test-utils";
import { ApiError, api } from "@/api/client";
import type { FitOut } from "@/api/types";
import FitSection from "@/components/FitSection.vue";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { FIT_POLL_MS, MAX_POLL_FAILURES, useFitStore } from "@/stores/fit";
import { useFeedStore } from "@/stores/feed";
import { useNotifyStore } from "@/stores/notify";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

const fitOut = (over: Partial<FitOut> = {}): FitOut => ({
  rating: "good", status: "done", error: null, explanation: "Matches well.", evaluated_at: "2026-10-24T10:00:00Z", outdated: false, ...over,
});

let status = { profile: true, configured: true, active: 0 };
let fitRow: FitOut | null;

beforeEach(() => {
  setLocale("en");
  setActivePinia(createPinia());
  status = { profile: true, configured: true, active: 0 };
  fitRow = null;
  get.mockReset();
  post.mockReset();
  get.mockImplementation((async (path: string) => {
    if (path === "/fit/status") return status;
    if (path === "/fit") return [{ posting_id: 5, fit: fitRow }];
    return [];
  }) as never);
  post.mockResolvedValue({ queued: 1, limit_exceeded: false });
});
afterEach(() => vi.useRealTimers());

async function mountSection(fit: FitOut | null) {
  const w = mount(FitSection, {
    props: { postingId: 5, fit },
    global: { plugins: [vuetify, i18n], stubs: { RouterLink: RouterLinkStub } },
  });
  await flushPromises();
  return w;
}

describe("FitSection", () => {
  it("shows rating label, explanation, date and the outdated hint", async () => {
    const w = await mountSection(fitOut({ outdated: true }));
    expect(w.find("[data-test=fit-rating]").text()).toBe("Good fit");
    expect(w.find("[data-test=fit-explanation]").text()).toBe("Matches well.");
    expect(w.find("[data-test=fit-evaluated-at]").text()).toContain("2026");
    expect(w.find("[data-test=fit-outdated]").text()).toContain("older version of your profile");
    expect(w.find("[data-test=fit-dot]").exists()).toBe(true);
  });

  it("button says Evaluate without a fit and Re-evaluate with one", async () => {
    expect((await mountSection(null)).find("[data-test=fit-evaluate]").text()).toBe("Evaluate");
    expect((await mountSection(fitOut())).find("[data-test=fit-evaluate]").text()).toBe("Re-evaluate");
  });

  it("shows the localised error text", async () => {
    const w = await mountSection(fitOut({ status: "error", rating: null, error: "daily_limit", explanation: null }));
    expect(w.find("[data-test=fit-error]").text()).toContain("Daily limit reached");
  });

  it("click posts with lang, shows the spinner, then the done result after the poll; emits updated", async () => {
    vi.useFakeTimers();
    setLocale("de");
    const w = await mountSection(null);
    post.mockImplementation((async () => {
      fitRow = fitOut({ status: "queued", rating: null, explanation: null, evaluated_at: null });
      return { queued: 1, limit_exceeded: false };
    }) as never);
    await w.find("[data-test=fit-evaluate]").trigger("click");
    await flushPromises();
    expect(post).toHaveBeenCalledWith("/fit/5?lang=de");
    expect(w.find("[data-test=fit-pending]").exists()).toBe(true);
    expect(w.find("[data-test=fit-evaluate]").attributes("disabled")).toBeDefined();
    const getsBefore = get.mock.calls.filter((c) => c[0] === "/fit").length;

    fitRow = fitOut({ explanation: "Passt gut." });
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS);
    await flushPromises();
    expect(get.mock.calls.filter((c) => c[0] === "/fit").length).toBe(getsBefore + 1);
    expect(get).toHaveBeenCalledWith("/fit", { ids: "5" });
    expect(w.find("[data-test=fit-explanation]").text()).toBe("Passt gut.");
    expect(w.find("[data-test=fit-pending]").exists()).toBe(false);

    // polling stopped after done
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS * 3);
    expect(get.mock.calls.filter((c) => c[0] === "/fit").length).toBe(getsBefore + 1);
    w.unmount();
  });

  it("stops polling on an error result and on unmount", async () => {
    vi.useFakeTimers();
    const w = await mountSection(fitOut({ status: "running", rating: null, explanation: null }));
    fitRow = fitOut({ status: "error", rating: null, error: "llm_invalid_output", explanation: null });
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS);
    await flushPromises();
    expect(w.find("[data-test=fit-error]").exists()).toBe(true);
    const n = get.mock.calls.filter((c) => c[0] === "/fit").length;
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS * 3);
    expect(get.mock.calls.filter((c) => c[0] === "/fit").length).toBe(n);

    w.unmount();
    const w2 = await mountSection(fitOut({ status: "queued", rating: null }));
    w2.unmount();
    const m = get.mock.calls.filter((c) => c[0] === "/fit").length;
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS * 3);
    expect(get.mock.calls.filter((c) => c[0] === "/fit").length).toBe(m);
  });

  it("gives up after a failure streak and reports it once", async () => {
    vi.useFakeTimers();
    const w = await mountSection(fitOut({ status: "running", rating: null }));
    get.mockImplementation((async (path: string) => {
      if (path === "/fit") throw new ApiError(500, null, {}, "boom");
      return status;
    }) as never);
    const errors = vi.spyOn(useNotifyStore(), "error");
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS * (MAX_POLL_FAILURES + 3));
    await flushPromises();
    expect(errors).toHaveBeenCalledTimes(1);
    expect(get.mock.calls.filter((c) => c[0] === "/fit").length).toBe(MAX_POLL_FAILURES);

    // Recovery: polling is suspended, the section offers a refresh and Re-evaluate is not stuck disabled.
    expect(useFitStore().suspended).toBe(true);
    expect(w.find("[data-test=fit-refresh]").exists()).toBe(true);
    expect(w.find("[data-test=fit-evaluate]").attributes("disabled")).toBeUndefined();
    get.mockImplementation((async (path: string) => {
      if (path === "/fit") return [{ posting_id: 5, fit: fitOut({ explanation: "Back again." }) }];
      return status;
    }) as never);
    await w.find("[data-test=fit-refresh]").trigger("click");
    await flushPromises();
    expect(useFitStore().suspended).toBe(false);
    expect(w.find("[data-test=fit-explanation]").text()).toBe("Back again.");
    expect(w.find("[data-test=fit-refresh]").exists()).toBe(false);
    w.unmount();
  });

  it("re-evaluating clears a suspended poll too (the button works while stalled)", async () => {
    vi.useFakeTimers();
    const w = await mountSection(fitOut({ status: "running" }));
    get.mockImplementation((async (path: string) => {
      if (path === "/fit") throw new ApiError(500, null, {}, "boom");
      return status;
    }) as never);
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS * (MAX_POLL_FAILURES + 1));
    expect(useFitStore().suspended).toBe(true);
    get.mockImplementation((async (path: string) => (path === "/fit" ? [{ posting_id: 5, fit: fitOut({ status: "queued" }) }] : status)) as never);
    await w.find("[data-test=fit-evaluate]").trigger("click");
    await flushPromises();
    expect(post).toHaveBeenCalled();
    expect(useFitStore().suspended).toBe(false);
    w.unmount();
  });

  it("keeps the old rating and explanation visible while a re-evaluation is pending", async () => {
    const w = await mountSection(fitOut({ status: "queued" }));
    expect(w.find("[data-test=fit-pending]").exists()).toBe(true);
    expect(w.find("[data-test=fit-rating]").text()).toBe("Good fit");
    expect(w.find("[data-test=fit-explanation]").text()).toBe("Matches well.");
    w.unmount();
  });

  it("keeps the old rating and explanation visible next to the error after a failed re-evaluation", async () => {
    const w = await mountSection(fitOut({ status: "error", error: "llm_invalid_output" }));
    expect(w.find("[data-test=fit-rating]").text()).toBe("Good fit");
    expect(w.find("[data-test=fit-explanation]").text()).toBe("Matches well.");
    expect(w.find("[data-test=fit-error]").exists()).toBe(true);
    w.unmount();
  });

  it("with the posting in the attached feed, one request per tick contains the id once", async () => {
    vi.useFakeTimers();
    const feed = useFeedStore();
    const store = useFitStore();
    const running = fitOut({ status: "running" });
    feed.items = [{ id: 5, fit: running } as never];
    fitRow = running;
    store.startPolling();
    const w = await mountSection(running);
    get.mockClear();
    await vi.advanceTimersByTimeAsync(FIT_POLL_MS);
    const calls = get.mock.calls.filter((c) => c[0] === "/fit");
    expect(calls).toHaveLength(1);
    expect(calls[0]![1]).toEqual({ ids: "5" });
    store.stopPolling();
    w.unmount();
  });

  it("a newer store result is not overwritten by an older prop", async () => {
    const w = await mountSection(fitOut({ evaluated_at: "2026-10-24T10:00:00Z", explanation: "Old." }));
    useFitStore().offer(5, fitOut({ evaluated_at: "2026-10-24T11:00:00Z", explanation: "New." }));
    await w.setProps({ fit: fitOut({ evaluated_at: "2026-10-24T10:00:00Z", explanation: "Old." }) });
    expect(w.find("[data-test=fit-explanation]").text()).toBe("New.");
    w.unmount();
  });

  it("seeds from a newer store result instead of the prop", async () => {
    useFitStore().offer(5, fitOut({ evaluated_at: "2026-10-24T12:00:00Z", explanation: "Store." }));
    const w = await mountSection(fitOut({ explanation: "Prop." }));
    expect(w.find("[data-test=fit-explanation]").text()).toBe("Store.");
    w.unmount();
  });

  it("is disabled with a link to /me without a profile, and to /settings without configuration", async () => {
    status = { profile: false, configured: true, active: 0 };
    let w = await mountSection(null);
    expect(w.find("[data-test=fit-evaluate]").attributes("disabled")).toBeDefined();
    expect(w.find("[data-test=fit-section-hint]").text()).toContain("Create your profile");
    expect(w.findComponent(RouterLinkStub).props("to")).toBe("/me");
    w.unmount();

    status = { profile: true, configured: false, active: 0 };
    setActivePinia(createPinia());
    w = await mountSection(null);
    expect(w.find("[data-test=fit-evaluate]").attributes("disabled")).toBeDefined();
    expect(w.findComponent(RouterLinkStub).props("to")).toBe("/settings");
    w.unmount();
  });
});
