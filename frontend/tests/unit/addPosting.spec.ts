import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { createMemoryHistory, createRouter } from "vue-router";
import { ApiError, api } from "@/api/client";
import type { PostingOut } from "@/api/types";
import AddPostingDialog from "@/components/AddPostingDialog.vue";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const post = vi.mocked(api.post);
const get = vi.mocked(api.get);

const posting = (over: Partial<PostingOut> = {}): PostingOut => ({
  id: 5, source: "web", external_id: "x", url: "https://example.com/j/1", title: "Vue Dev", company: "ACME", location: "Berlin",
  lat: null, lon: null, description: "<b>Great</b> job", published_at: null, first_seen_at: "2026-10-01T10:00:00Z",
  last_seen_at: "2026-10-01T10:00:00Z", employment_type: null, remote: null, contract_type: null, triage_status: "new", triaged_at: null,
  profile_ids: [], application_id: null, fit: null, ...over,
});

const q = (sel: string) => document.body.querySelector(sel) as HTMLElement | null;
async function type(sel: string, value: string) {
  const el = q(sel) as HTMLInputElement;
  el.value = value;
  el.dispatchEvent(new Event("input"));
  await flushPromises();
}

let router: ReturnType<typeof createRouter>;
function setup() {
  const Host = defineComponent({
    render: () => h(VLayout, null, () => h(AddPostingDialog, { modelValue: true })),
  });
  return mount(Host, { global: { plugins: [createPinia(), vuetify, i18n, router] }, attachTo: document.body });
}

beforeAll(() => {
  vi.stubGlobal("visualViewport", { width: 1024, height: 768, offsetLeft: 0, offsetTop: 0, addEventListener() {}, removeEventListener() {} });
});

beforeEach(() => {
  setActivePinia(createPinia());
  post.mockReset();
  get.mockReset();
  document.body.innerHTML = "";
  router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { render: () => null } }] });
  i18n.global.locale.value = "en";
});

describe("AddPostingDialog", () => {
  it("success shows a preview (description as text) and saving navigates to the detail page", async () => {
    post.mockResolvedValueOnce(posting()).mockResolvedValueOnce({ application_id: 11 });
    const w = setup();
    await type("[data-test=ap-url] input", "https://example.com/j/1");
    q("[data-test=ap-fetch]")!.click();
    await flushPromises();
    expect(post.mock.calls[0]).toEqual(["/postings/from-url", { url: "https://example.com/j/1" }]);
    expect(q("[data-test=ap-preview]")!.textContent).toContain("Vue Dev");
    expect(q("[data-test=ap-preview-description]")!.textContent).toBe("<b>Great</b> job");
    expect(q("[data-test=ap-preview-description] b")).toBeNull();
    q("[data-test=ap-save]")!.click();
    await flushPromises();
    expect(post.mock.calls[1]![0]).toBe("/postings/5/save");
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe("/applications/11"));
    w.unmount();
  });

  it("existing application: open instead of save", async () => {
    post.mockResolvedValueOnce(posting({ application_id: 9 }));
    const w = setup();
    await type("[data-test=ap-url] input", "https://example.com/j/1");
    q("[data-test=ap-fetch]")!.click();
    await flushPromises();
    expect(q("[data-test=ap-save]")).toBeNull();
    q("[data-test=ap-open]")!.click();
    await flushPromises();
    expect(post).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe("/applications/9"));
    w.unmount();
  });

  it("409 already_saved on save leads to the existing application", async () => {
    post.mockResolvedValueOnce(posting()).mockRejectedValueOnce(new ApiError(409, "already_saved", {}, "x"));
    const w = setup();
    await type("[data-test=ap-url] input", "https://example.com/j/1");
    q("[data-test=ap-fetch]")!.click();
    await flushPromises();
    get.mockResolvedValueOnce(posting({ application_id: 3 }));
    q("[data-test=ap-save]")!.click();
    await flushPromises();
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe("/applications/3"));
    w.unmount();
  });

  it("404 switches to the form with the URL", async () => {
    post.mockRejectedValueOnce(new ApiError(404, "no_plugin_for_url", {}, "No plugin"));
    const w = setup();
    await type("[data-test=ap-url] input", "https://nowhere.example/j");
    q("[data-test=ap-fetch]")!.click();
    await flushPromises();
    expect(q("[data-test=ap-manual]")).not.toBeNull();
    expect((q("[data-test=ap-m-url] input") as HTMLInputElement).value).toBe("https://nowhere.example/j");
    expect(q("[data-test=ap-hint]")!.textContent).toContain("No plugin can handle this URL.");
    w.unmount();
  });

  it("502 stays in the URL step and shows the error", async () => {
    post.mockRejectedValueOnce(new ApiError(502, "fetch_failed", { reason: "timeout" }, "x"));
    const w = setup();
    await type("[data-test=ap-url] input", "https://example.com/j/1");
    q("[data-test=ap-fetch]")!.click();
    await flushPromises();
    expect(q("[data-test=ap-manual]")).toBeNull();
    expect(q("[data-test=ap-error]")!.textContent).toContain("timeout");
    w.unmount();
  });

  it("manual save navigates to the detail page; title is required", async () => {
    post.mockResolvedValueOnce({ application_id: 21 });
    const w = setup();
    q("[data-test=ap-skip]")!.click();
    await flushPromises();
    expect((q("[data-test=ap-m-save]") as HTMLButtonElement).disabled).toBe(true);
    await type("[data-test=ap-m-title] input", "Plumber");
    await type("[data-test=ap-m-company] input", "Pipes AG");
    await type("[data-test=ap-m-description] textarea", "Fix pipes");
    q("[data-test=ap-m-save]")!.click();
    await flushPromises();
    expect(post.mock.calls[0]![0]).toBe("/postings");
    expect(post.mock.calls[0]![1]).toMatchObject({ title: "Plumber", company: "Pipes AG", description: "Fix pipes" });
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe("/applications/21"));
    w.unmount();
  });
});
