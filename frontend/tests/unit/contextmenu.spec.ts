import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import { createMemoryHistory, createRouter } from "vue-router";
import { VueDraggable } from "vue-draggable-plus";
import { ApiError, api } from "@/api/client";
import type { AppStatus, ApplicationOut } from "@/api/types";
import ApplicationBoard from "@/components/ApplicationBoard.vue";
import ApplicationContextMenu from "@/components/ApplicationContextMenu.vue";
import ApplicationTable from "@/components/ApplicationTable.vue";
import { useLongPress } from "@/composables/useLongPress";
import { allowedTargets, ACTIVE_STATUSES } from "@/domain/status";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";
import { useApplicationsStore } from "@/stores/applications";
import { useNotifyStore } from "@/stores/notify";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

function app(id: number, status: AppStatus): ApplicationOut {
  return {
    id, status, created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z", salary_expectation: null,
    channel: null, notes: null, last_status_change_at: null,
    posting: { id, title: `T${id}`, company: "ACME", location: "Berlin" } as ApplicationOut["posting"],
  };
}

beforeEach(() => {
  localStorage.clear();
  get.mockReset();
  get.mockResolvedValue([]);
  post.mockReset();
  document.body.innerHTML = "";
});
afterEach(() => vi.useRealTimers());

function menuItems(): string[] {
  return [...document.querySelectorAll("[data-test^='cm-']")].map((el) => el.getAttribute("data-test")!);
}

async function mountMenu(status: AppStatus) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { render: () => null } }] });
  const push = vi.spyOn(router, "push");
  const store = useApplicationsStore();
  const move = vi.spyOn(store, "move").mockResolvedValue();
  const reopen = vi.spyOn(store, "reopen").mockResolvedValue();
  const Host = defineComponent({
    render: () => h(VLayout, null, () => h(ApplicationContextMenu, { application: app(5, status), x: 10, y: 20, modelValue: true })),
  });
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n, router] }, attachTo: document.body });
  await flushPromises();
  return { w, push, move, reopen };
}

describe("hide saved (store)", () => {
  it("hides the saved column and rows and persists the flag", async () => {
    setActivePinia(createPinia());
    const s = useApplicationsStore();
    s.items = [app(1, "saved"), app(2, "applied")];
    expect(s.visibleStatuses).toContain("saved");
    expect(s.visibleItems).toHaveLength(2);
    s.hideSaved = true;
    await flushPromises();
    expect(s.visibleStatuses).not.toContain("saved");
    expect(s.visibleStatuses).toEqual(["preparing", "applied", "interviewing", "offer"]);
    expect(s.visibleItems.map((a) => a.id)).toEqual([2]);
    expect(localStorage.getItem("jobtracker.hideSaved")).toBe("true");
    s.showTerminal = true;
    expect(s.visibleStatuses).toEqual(["preparing", "applied", "interviewing", "offer", "rejected", "withdrawn", "accepted"]);
  });

  it("restores the flag from localStorage", () => {
    localStorage.setItem("jobtracker.hideSaved", "true");
    setActivePinia(createPinia());
    expect(useApplicationsStore().hideSaved).toBe(true);
  });
});

describe("reopen (store)", () => {
  it("moves optimistically, posts to /reopen and applies the response", async () => {
    setActivePinia(createPinia());
    const s = useApplicationsStore();
    s.items = [app(1, "rejected")];
    post.mockResolvedValue({ status: "applied", updated_at: "U", last_status_change_at: "L" } as never);
    const p = s.reopen(1, "applied");
    expect(s.byStatus.applied.map((a) => a.id)).toEqual([1]);
    await p;
    expect(post).toHaveBeenCalledWith("/applications/1/reopen", { to: "applied" });
    expect(s.items[0]!.last_status_change_at).toBe("L");
  });

  it("rolls back status and position on 409 and notifies", async () => {
    setActivePinia(createPinia());
    const s = useApplicationsStore();
    s.items = [app(1, "rejected"), app(2, "saved"), app(3, "withdrawn")];
    post.mockRejectedValue(new ApiError(409, "not_terminal", {}, "x"));
    const err = vi.spyOn(useNotifyStore(), "error");
    await s.reopen(1, "applied");
    expect(s.items.map((a) => [a.id, a.status])).toEqual([[1, "rejected"], [2, "saved"], [3, "withdrawn"]]);
    expect(err).toHaveBeenCalled();
  });
});

describe("ApplicationContextMenu", () => {
  it("offers exactly allowedTargets plus open for an active application", async () => {
    const { w } = await mountMenu("applied");
    expect(menuItems()).toEqual([...allowedTargets("applied").map((s) => "cm-status-" + s), "cm-open"]);
    w.unmount();
  });

  it("offers reopen into all active statuses (no status changes) for a finished application", async () => {
    const { w } = await mountMenu("rejected");
    expect(menuItems()).toEqual([...ACTIVE_STATUSES.map((s) => "cm-reopen-" + s), "cm-open"]);
    w.unmount();
  });

  it("calls move, reopen and router.push from the entries", async () => {
    let ctx = await mountMenu("applied");
    (document.querySelector("[data-test=cm-status-interviewing]") as HTMLElement).click();
    expect(ctx.move).toHaveBeenCalledWith(5, "interviewing");
    ctx.w.unmount();
    document.body.innerHTML = "";

    ctx = await mountMenu("rejected");
    (document.querySelector("[data-test=cm-reopen-applied]") as HTMLElement).click();
    expect(ctx.reopen).toHaveBeenCalledWith(5, "applied");
    ctx.w.unmount();
    document.body.innerHTML = "";

    ctx = await mountMenu("applied");
    (document.querySelector("[data-test=cm-open]") as HTMLElement).click();
    expect(ctx.push).toHaveBeenCalledWith("/applications/5");
    ctx.w.unmount();
  });
});

describe("useLongPress", () => {
  const down = { pointerType: "touch" } as PointerEvent;

  it("does not trigger before 500 ms and lets the click through", () => {
    vi.useFakeTimers();
    const cb = vi.fn();
    const lp = useLongPress(cb);
    lp.onPointerdown(down);
    vi.advanceTimersByTime(499);
    lp.onPointerup();
    vi.advanceTimersByTime(10);
    expect(cb).not.toHaveBeenCalled();
    const click = { stopPropagation: vi.fn(), stopImmediatePropagation: vi.fn(), preventDefault: vi.fn() };
    lp.onClickCapture(click as never);
    expect(click.stopPropagation).not.toHaveBeenCalled();
  });

  it("recognises at 500 ms, runs the callback after the swallowed click and swallows only that click", () => {
    vi.useFakeTimers();
    const cb = vi.fn();
    const lp = useLongPress(cb);
    lp.onPointerdown(down);
    vi.advanceTimersByTime(500);
    expect(cb).not.toHaveBeenCalled(); // finger still down
    lp.onPointerup();
    const mk = () => ({ stopPropagation: vi.fn(), stopImmediatePropagation: vi.fn(), preventDefault: vi.fn() });
    const first = mk();
    lp.onClickCapture(first as never);
    expect(first.stopPropagation).toHaveBeenCalled();
    expect(first.preventDefault).toHaveBeenCalled();
    expect(cb).not.toHaveBeenCalled(); // still inside the click dispatch
    vi.advanceTimersByTime(0);
    expect(cb).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1000);
    expect(cb).toHaveBeenCalledTimes(1); // the fallback does not fire a second time
    const second = mk();
    lp.onClickCapture(second as never);
    expect(second.stopPropagation).not.toHaveBeenCalled();
  });

  it("runs the callback 300 ms after pointerup when no click follows", () => {
    vi.useFakeTimers();
    const cb = vi.fn();
    const lp = useLongPress(cb);
    lp.onPointerdown(down);
    vi.advanceTimersByTime(500);
    lp.onPointerup();
    lp.onPointerleave(); // fired right after pointerup on touch; must not abort
    vi.advanceTimersByTime(299);
    expect(cb).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("cancel() (drag started) aborts a recognised long press: no callback, click not swallowed", () => {
    vi.useFakeTimers();
    const cb = vi.fn();
    const lp = useLongPress(cb);
    lp.onPointerdown(down);
    vi.advanceTimersByTime(500);
    lp.cancel();
    lp.onPointerup();
    vi.advanceTimersByTime(1000);
    expect(cb).not.toHaveBeenCalled();
    const click = { stopPropagation: vi.fn(), stopImmediatePropagation: vi.fn(), preventDefault: vi.fn() };
    lp.onClickCapture(click as never);
    expect(click.stopPropagation).not.toHaveBeenCalled();
  });

  it("cancels on drift beyond 10 px but tolerates small movement", () => {
    vi.useFakeTimers();
    const cb = vi.fn();
    const lp = useLongPress(cb);
    const at = (x: number, y: number) => ({ pointerType: "touch", clientX: x, clientY: y }) as PointerEvent;
    lp.onPointerdown(at(100, 100));
    vi.advanceTimersByTime(200);
    lp.onPointermove(at(115, 100));
    vi.advanceTimersByTime(400);
    expect(cb).not.toHaveBeenCalled();
    const click = { stopPropagation: vi.fn(), stopImmediatePropagation: vi.fn(), preventDefault: vi.fn() };
    lp.onClickCapture(click as never);
    expect(click.stopPropagation).not.toHaveBeenCalled();

    lp.onPointerdown(at(100, 100));
    vi.advanceTimersByTime(200);
    lp.onPointermove(at(105, 100));
    vi.advanceTimersByTime(300);
    lp.onPointerup();
    vi.advanceTimersByTime(300);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("is cancelled by pointercancel and ignores mouse pointers", () => {
    vi.useFakeTimers();
    const cb = vi.fn();
    const lp = useLongPress(cb);
    lp.onPointerdown(down);
    lp.onPointercancel();
    vi.advanceTimersByTime(600);
    lp.onPointerdown({ pointerType: "mouse" } as PointerEvent);
    vi.advanceTimersByTime(600);
    expect(cb).not.toHaveBeenCalled();
  });
});

async function mountView(comp: typeof ApplicationBoard | typeof ApplicationTable, status: AppStatus) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useApplicationsStore();
  store.items = [app(7, status)];
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: { render: () => null } }] });
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(comp)) });
  const push = vi.spyOn(router, "push");
  const w = mount(Host, { global: { plugins: [pinia, vuetify, i18n, router] }, attachTo: document.body });
  await flushPromises();
  return { w, store, push };
}

describe("context menu in the views", () => {
  it("board card: right click opens the menu", async () => {
    const { w } = await mountView(ApplicationBoard, "applied");
    const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 30, clientY: 40 });
    w.find('[data-id="7"]').element.dispatchEvent(ev);
    await flushPromises();
    expect(ev.defaultPrevented).toBe(true);
    expect(menuItems()).toContain("cm-open");
    w.unmount();
  });

  it("board card: long touch press opens the menu", async () => {
    vi.useFakeTimers();
    const { w } = await mountView(ApplicationBoard, "applied");
    const card = w.find('[data-id="7"]').element;
    const pd = new Event("pointerdown", { bubbles: true });
    Object.assign(pd, { pointerType: "touch", clientX: 12, clientY: 13 });
    card.dispatchEvent(pd);
    vi.advanceTimersByTime(500);
    await flushPromises();
    expect(menuItems()).toEqual([]); // finger still down: not opened yet
    card.dispatchEvent(new Event("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(300);
    await flushPromises();
    expect(menuItems()).toContain("cm-open");
    w.unmount();
  });

  it("board card: starting a drag cancels the pending long press", async () => {
    vi.useFakeTimers();
    const { w, push } = await mountView(ApplicationBoard, "applied");
    const card = w.find('[data-id="7"]').element;
    card.dispatchEvent(Object.assign(new Event("pointerdown", { bubbles: true }), { pointerType: "touch", clientX: 1, clientY: 2 }));
    vi.advanceTimersByTime(500);
    w.findComponent(VueDraggable).vm.$emit("start", {});
    card.dispatchEvent(new Event("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(1000);
    await flushPromises();
    expect(menuItems()).toEqual([]);
    expect(push).not.toHaveBeenCalled();
    w.unmount();
  });

  it("board card: pointerup without a click opens the menu after 300 ms", async () => {
    vi.useFakeTimers();
    const { w } = await mountView(ApplicationBoard, "applied");
    const card = w.find('[data-id="7"]').element;
    card.dispatchEvent(Object.assign(new Event("pointerdown", { bubbles: true }), { pointerType: "touch", clientX: 1, clientY: 2 }));
    vi.advanceTimersByTime(500);
    card.dispatchEvent(new Event("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(299);
    await flushPromises();
    expect(menuItems()).toEqual([]);
    vi.advanceTimersByTime(1);
    await flushPromises();
    expect(menuItems()).toContain("cm-open");
    w.unmount();
  });

  it.each([
    ["board card", ApplicationBoard, '[data-id="7"]'],
    ["table row", ApplicationTable, "tbody tr"],
  ] as const)("%s: after a long press the first click is swallowed, the second navigates", async (_n, comp, sel) => {
    vi.useFakeTimers();
    const { w, push } = await mountView(comp, "applied");
    const el = w.find(sel).element;
    const pd = Object.assign(new Event("pointerdown", { bubbles: true }), { pointerType: "touch", clientX: 1, clientY: 2 });
    el.dispatchEvent(pd);
    vi.advanceTimersByTime(500);
    el.dispatchEvent(new Event("pointerup", { bubbles: true }));
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    expect(push).not.toHaveBeenCalled();
    vi.advanceTimersByTime(0);
    await flushPromises();
    expect(menuItems()).toContain("cm-open"); // opened after the swallowed click ...
    vi.advanceTimersByTime(1000);
    await flushPromises();
    expect(menuItems()).toContain("cm-open"); // ... and stays open
    expect(push).not.toHaveBeenCalled();
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    expect(push).toHaveBeenCalledWith("/applications/7");
    w.unmount();
  });

  it("table row: right click opens the menu for that row", async () => {
    const { w } = await mountView(ApplicationTable, "rejected");
    const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 5, clientY: 6 });
    w.find("tbody tr").element.dispatchEvent(ev);
    await flushPromises();
    expect(ev.defaultPrevented).toBe(true);
    expect(menuItems()).toContain("cm-reopen-applied");
    w.unmount();
  });

  it("table hides saved rows when hideSaved is set", async () => {
    const { w, store } = await mountView(ApplicationTable, "saved");
    expect(w.findAll("tbody tr")).toHaveLength(1);
    store.hideSaved = true;
    await flushPromises();
    expect(w.text()).not.toContain("T7");
    w.unmount();
  });
});
