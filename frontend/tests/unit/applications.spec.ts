import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/api/client";
import type { AppStatus, ApplicationOut } from "@/api/types";
import { i18n } from "@/i18n";
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
    posting: { id, title: `T${id}`, company: "ACME" } as ApplicationOut["posting"],
  };
}

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  get.mockReset();
  post.mockReset();
});

describe("applications store", () => {
  it("byStatus groups", async () => {
    get.mockResolvedValue([app(1, "saved"), app(2, "applied"), app(3, "saved")]);
    const s = useApplicationsStore();
    await s.load();
    expect(s.byStatus.saved.map((a) => a.id)).toEqual([1, 3]);
    expect(s.byStatus.applied.map((a) => a.id)).toEqual([2]);
    expect(s.byStatus.offer).toEqual([]);
  });

  it("load without terminal requests only active statuses, with terminal all eight", async () => {
    get.mockResolvedValue([]);
    const s = useApplicationsStore();
    await s.load();
    expect(get.mock.calls[0]![0]).toBe("/applications");
    expect((get.mock.calls[0]![1] as { status: string[] }).status).toEqual(["saved", "preparing", "applied", "interviewing", "offer"]);
    s.showTerminal = true;
    s.q = " vue ";
    await s.load();
    const params = get.mock.calls[1]![1] as { status: string[]; q: string };
    expect(params.status).toHaveLength(8);
    expect(params.status).toContain("accepted");
    expect(params.q).toBe("vue");
  });

  it("load tolerates q = null", async () => {
    get.mockResolvedValue([]);
    const s = useApplicationsStore();
    s.q = null;
    await s.load();
    expect((get.mock.calls[0]![1] as { q: string }).q).toBe("");
  });

  it("move updates optimistically and sends the new status", async () => {
    get.mockResolvedValue([app(1, "saved"), app(2, "saved")]);
    let resolve!: () => void;
    post.mockReturnValue(new Promise<void>((r) => (resolve = r)) as never);
    const s = useApplicationsStore();
    await s.load();
    const p = s.move(1, "preparing");
    expect(s.byStatus.preparing.map((a) => a.id)).toEqual([1]);
    expect(s.byStatus.saved.map((a) => a.id)).toEqual([2]);
    resolve();
    await p;
    expect(post).toHaveBeenCalledWith("/applications/1/status", { to: "preparing" });
  });

  it("move resets status and position on 409 and shows the error", async () => {
    get.mockResolvedValue([app(1, "applied"), app(2, "saved"), app(3, "applied")]);
    post.mockRejectedValue(new ApiError(409, "invalid_transition", { from: "applied", to: "accepted" }, "nope"));
    const s = useApplicationsStore();
    await s.load();
    await s.move(1, "accepted");
    expect(s.items.map((a) => [a.id, a.status])).toEqual([[1, "applied"], [2, "saved"], [3, "applied"]]);
    const n = useNotifyStore();
    expect(n.visible).toBe(true);
    expect(n.message).toContain("applied");
  });

  it("move adopts the response (status, updated_at, last_status_change_at)", async () => {
    get.mockResolvedValue([app(1, "saved")]);
    post.mockResolvedValue({ ...app(1, "preparing"), updated_at: "2026-10-23T09:00:00Z", last_status_change_at: "2026-10-23T09:00:00Z" });
    const s = useApplicationsStore();
    await s.load();
    await s.move(1, "preparing");
    expect(s.items[0]!.last_status_change_at).toBe("2026-10-23T09:00:00Z");
    expect(s.items[0]!.updated_at).toBe("2026-10-23T09:00:00Z");
    expect(s.items[0]!.status).toBe("preparing");
  });

  it("switching to the board clears q and reloads", async () => {
    get.mockResolvedValue([]);
    const s = useApplicationsStore();
    s.view = "table";
    s.q = "vue";
    await nextTick();
    expect(get).not.toHaveBeenCalled();
    s.view = "board";
    await nextTick();
    expect(s.q).toBe("");
    expect(get).toHaveBeenCalledTimes(1);
    expect((get.mock.calls[0]![1] as { q: string }).q).toBe("");
  });

  it("move ignores drops into the same column", async () => {
    get.mockResolvedValue([app(1, "saved")]);
    const s = useApplicationsStore();
    await s.load();
    await s.move(1, "saved");
    expect(post).not.toHaveBeenCalled();
  });

  it("view is stored in and read from localStorage", async () => {
    const s = useApplicationsStore();
    expect(s.view).toBe("board");
    s.view = "table";
    await Promise.resolve();
    expect(localStorage.getItem("jobtracker.applicationsView")).toBe("table");
    setActivePinia(createPinia());
    expect(useApplicationsStore().view).toBe("table");
  });
});

describe("applications store exportUrl", () => {
  it("reflects showTerminal, hideSaved, q and locale", () => {
    const s = useApplicationsStore();
    const u = (f: "csv" | "xlsx") => new URL(s.exportUrl(f), "http://x");
    let url = u("csv");
    expect(url.pathname).toBe("/api/applications/export");
    expect(url.searchParams.get("format")).toBe("csv");
    expect(url.searchParams.getAll("status")).toEqual(["saved", "preparing", "applied", "interviewing", "offer"]);
    expect(url.searchParams.has("q")).toBe(false);
    s.showTerminal = true;
    s.hideSaved = true;
    s.q = " vue ";
    i18n.global.locale.value = "de";
    url = u("xlsx");
    expect(url.searchParams.get("format")).toBe("xlsx");
    expect(url.searchParams.getAll("status")).toHaveLength(7);
    expect(url.searchParams.getAll("status")).not.toContain("saved");
    expect(url.searchParams.get("q")).toBe("vue");
    expect(url.searchParams.get("lang")).toBe("de");
    s.q = null;
    expect(u("csv").searchParams.has("q")).toBe(false);
    i18n.global.locale.value = "en";
  });
});
