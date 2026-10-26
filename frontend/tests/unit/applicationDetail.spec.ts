import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { api } from "@/api/client";
import type { ApplicationDetailOut } from "@/api/types";
import { allowedTargets } from "@/domain/status";
import { fromLocalInput, toLocalInput } from "@/domain/time";
import { i18n, setLocale } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useApplicationDetailStore } from "@/stores/applicationDetail";
import ApplicationDetailView from "@/views/ApplicationDetailView.vue";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
// The cover letter section reads the router; the editor route belongs to a later task.
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const patch = vi.mocked(api.patch);

function detail(over: Partial<ApplicationDetailOut> = {}): ApplicationDetailOut {
  return {
    id: 7, status: "applied", created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z",
    salary_expectation: null, channel: null, notes: null, last_status_change_at: null,
    posting: { id: 1, title: "Vue Dev", company: "ACME", location: "Berlin", url: "https://x.test/j", description: "Line1\nLine2" },
    status_changes: [], appointments: [], contacts: [], attachments: [], ...over,
  } as ApplicationDetailOut;
}

beforeEach(() => {
  setLocale("en");
  localStorage.clear();
  for (const m of [get, post, patch]) m.mockReset();
});

describe("allowedTargets", () => {
  it("applied: all except accepted and itself", () => {
    const t = allowedTargets("applied");
    expect(t).toEqual(expect.arrayContaining(["saved", "preparing", "interviewing", "offer", "rejected", "withdrawn"]));
    expect(t).not.toContain("accepted");
    expect(t).not.toContain("applied");
  });
  it("offer may go to accepted", () => expect(allowedTargets("offer")).toContain("accepted"));
  it("finished statuses have no targets", () => {
    for (const s of ["rejected", "withdrawn", "accepted"] as const) expect(allowedTargets(s)).toEqual([]);
  });
});

describe("time helpers", () => {
  it("local datetime input round trip", () => {
    const iso = fromLocalInput("2026-10-30T14:30");
    expect(iso).toMatch(/Z$|[+-]\d\d:\d\d$/);
    expect(toLocalInput(iso)).toBe("2026-10-30T14:30");
  });
});

describe("applicationDetail store", () => {
  it("patch sends the body and adopts the response", async () => {
    setActivePinia(createPinia());
    const s = useApplicationDetailStore();
    get.mockResolvedValue(detail());
    await s.load(7);
    patch.mockResolvedValue(detail({ notes: "hi" }));
    await s.patch({ notes: "hi" });
    expect(patch).toHaveBeenCalledWith("/applications/7", { notes: "hi" });
    expect(s.app?.notes).toBe("hi");
  });

  it("changeStatus replaces state with the response", async () => {
    setActivePinia(createPinia());
    const s = useApplicationDetailStore();
    get.mockResolvedValue(detail());
    await s.load(7);
    post.mockResolvedValue(detail({ status: "offer" }));
    await s.changeStatus("offer", "yay");
    expect(post).toHaveBeenCalledWith("/applications/7/status", { to: "offer", comment: "yay" });
    expect(s.app?.status).toBe("offer");
  });
});

describe("applicationDetail store: stale object", () => {
  it("upload stays visible after an intermediate adopt", async () => {
    setActivePinia(createPinia());
    const s = useApplicationDetailStore();
    get.mockResolvedValue(detail());
    await s.load(7);
    let finish!: (v: unknown) => void;
    vi.mocked(api.upload).mockReturnValue(new Promise((r) => (finish = r)));
    const up = s.uploadAttachment(new File(["x"], "cv.pdf"), "cv");
    patch.mockResolvedValue(detail({ notes: "n" }));
    await s.patch({ notes: "n" }); // replaces s.app with a new object
    finish({ id: 5, application_id: 7, filename: "cv.pdf", display_name: "cv.pdf", stored_path: "", kind: "cv", created_at: "" });
    await up;
    expect(s.app?.notes).toBe("n");
    expect(s.app?.attachments.map((a) => a.id)).toEqual([5]);
  });

  it("oversized file is rejected before the upload", async () => {
    setActivePinia(createPinia());
    const s = useApplicationDetailStore();
    get.mockResolvedValue(detail());
    await s.load(7);
    vi.mocked(api.upload).mockReset();
    const big = new File(["x"], "big.bin");
    Object.defineProperty(big, "size", { value: 26 * 1024 * 1024 });
    expect(await s.uploadAttachment(big, "other")).toBe(false);
    expect(api.upload).not.toHaveBeenCalled();
  });
});

describe("ApplicationDetailView", () => {
  it("finished status shows Reopen instead of the status picker", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    get.mockResolvedValue(detail({ status: "rejected" }));
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(ApplicationDetailView, { id: "7" })) });
    const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
    await flushPromises();
    expect(w.find("[data-test=reopen]").text()).toContain("Reopen");
    expect(w.find("[data-test=status-select]").exists()).toBe(false);
    w.unmount();
  });

  it("autosave: blur without a change sends nothing, with a change exactly one patch", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    get.mockResolvedValue(detail({ channel: "mail" }));
    patch.mockResolvedValue(detail({ channel: "phone" }));
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(ApplicationDetailView, { id: "7" })) });
    const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
    await flushPromises();
    const input = w.find("[data-test=field-channel] input");
    await input.trigger("blur");
    expect(patch).not.toHaveBeenCalled();
    await input.setValue("phone");
    await input.trigger("blur");
    await flushPromises();
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch).toHaveBeenCalledWith("/applications/7", { channel: "phone" });
    w.unmount();
  });

  async function mountDetail() {
    const pinia = createPinia();
    setActivePinia(pinia);
    get.mockResolvedValue(detail({ channel: "mail" }));
    const Host = defineComponent({ render: () => h(VLayout, null, () => h(ApplicationDetailView, { id: "7" })) });
    const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n] }, attachTo: document.body });
    await flushPromises();
    return w;
  }

  it("failed autosave keeps the text and shows a hint", async () => {
    const w = await mountDetail();
    patch.mockRejectedValue(new Error("boom"));
    const input = w.find("[data-test=field-channel] input");
    await input.setValue("phone");
    await input.trigger("blur");
    await flushPromises();
    expect((input.element as HTMLInputElement).value).toBe("phone");
    expect(w.find("[data-test=field-channel]").text()).toContain("Not saved");
    w.unmount();
  });

  it("late response does not overwrite newer text", async () => {
    const w = await mountDetail();
    let finish!: (v: unknown) => void;
    patch.mockReturnValue(new Promise((r) => (finish = r)));
    const input = w.find("[data-test=field-channel] input");
    await input.setValue("p");
    await input.trigger("blur");
    await input.setValue("pq"); // typed while the save is in flight
    finish(detail({ channel: "p" }));
    await flushPromises();
    expect((input.element as HTMLInputElement).value).toBe("pq");
    w.unmount();
  });
});
