import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/api/client";
import type { CoverLetterIn, CoverLetterOut, CoverLetterTemplate } from "@/api/types";
import { pdfUrl, useCoverLetterStore } from "@/stores/coverLetter";
import { useCoverLetterTemplatesStore } from "@/stores/coverLetterTemplates";
import { useNotifyStore } from "@/stores/notify";

vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } };
});
const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const put = vi.mocked(api.put);
const patch = vi.mocked(api.patch);
const del = vi.mocked(api.del);
const upload = vi.mocked(api.upload);

const letter = (over: Partial<CoverLetterOut> = {}): CoverLetterOut => ({
  id: 1, application_id: 7, format: "text", template_id: null, template_name: null, language: "en", context: {},
  content: "Dear", status: "idle", error: null, compile_log: null, pdf_available: false, compiler_available: true,
  compiled_at: null, updated_at: "2026-01-01T00:00:00Z", messages: [], ...over,
});
const input: CoverLetterIn = { format: "text", template_id: null, language: "en", context: { profile: true, document_ids: [], notes: "" } };

beforeEach(() => {
  setActivePinia(createPinia());
  for (const m of [get, post, put, patch, del, upload]) m.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("cover letter store", () => {
  it("treats 404 as no letter without notifying", async () => {
    get.mockRejectedValue(new ApiError(404, "cover_letter_not_found", {}, "x"));
    const store = useCoverLetterStore();
    const notify = useNotifyStore();
    const spy = vi.spyOn(notify, "error");
    await store.load(7);
    expect(store.letter).toBeNull();
    expect(spy).not.toHaveBeenCalled();
    expect(store.loading).toBe(false);
  });

  it("notifies other load errors", async () => {
    get.mockRejectedValue(new ApiError(500, "internal_error", {}, "x"));
    const spy = vi.spyOn(useNotifyStore(), "error");
    await useCoverLetterStore().load(7);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("create posts the body and stores the result", async () => {
    post.mockResolvedValue(letter({ status: "generating" }));
    const store = useCoverLetterStore();
    expect(await store.create(7, input)).toBe(true);
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter", input);
    expect(store.letter?.status).toBe("generating");
    store.stopPolling();
  });

  it("mutations return false and notify on error", async () => {
    post.mockRejectedValue(new ApiError(409, "cover_letter_busy", {}, "x"));
    const spy = vi.spyOn(useNotifyStore(), "error");
    expect(await useCoverLetterStore().send(7, "hi")).toBe(false);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("saveContent, send, repair, attach and remove hit the right routes", async () => {
    const store = useCoverLetterStore();
    put.mockResolvedValue(letter());
    expect(await store.saveContent(7, "new")).toBe(true);
    expect(put).toHaveBeenCalledWith("/applications/7/cover-letter/content", { content: "new" });
    post.mockResolvedValue(letter());
    expect(await store.send(7, "shorter")).toBe(true);
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter/messages", { text: "shorter" });
    expect(await store.repair(7)).toBe(true);
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter/repair");
    expect(await store.attach(7, "de")).toBe(true);
    expect(post).toHaveBeenCalledWith("/applications/7/cover-letter/attach?lang=de");
    del.mockResolvedValue(undefined as never);
    store.letter = letter();
    expect(await store.remove(7)).toBe(true);
    expect(del).toHaveBeenCalledWith("/applications/7/cover-letter");
    expect(store.letter).toBeNull();
  });

  it("polls every 2 s while not idle and stops at idle", async () => {
    vi.useFakeTimers();
    post.mockResolvedValue(letter({ status: "generating" }));
    get.mockResolvedValueOnce(letter({ status: "generating" })).mockResolvedValue(letter({ status: "idle" }));
    const store = useCoverLetterStore();
    await store.create(7, input);
    expect(get).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2000);
    expect(get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(get).toHaveBeenCalledTimes(2);
    expect(store.letter?.status).toBe("idle");
    await vi.advanceTimersByTimeAsync(10000);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("stopPolling cancels the timer", async () => {
    vi.useFakeTimers();
    get.mockResolvedValue(letter({ status: "compiling" }));
    const store = useCoverLetterStore();
    await store.load(7);
    store.stopPolling();
    await vi.advanceTimersByTimeAsync(10000);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("ignores a late response for another application", async () => {
    let resolveA!: (l: CoverLetterOut) => void;
    get.mockImplementationOnce(() => new Promise((r) => (resolveA = r as never)));
    get.mockResolvedValueOnce(letter({ application_id: 8, content: "B" }));
    const store = useCoverLetterStore();
    const a = store.load(7);
    await store.load(8);
    resolveA(letter({ application_id: 7, content: "A" }));
    await a;
    expect(store.letter?.content).toBe("B");
    expect(store.loading).toBe(false);
  });

  it("does not restart polling when stopPolling ran during an in-flight fetch", async () => {
    vi.useFakeTimers();
    let resolve!: (l: CoverLetterOut) => void;
    get.mockImplementationOnce(() => new Promise((r) => (resolve = r as never)));
    const store = useCoverLetterStore();
    const p = store.load(7);
    store.stopPolling();
    resolve(letter({ status: "generating" }));
    await p;
    await vi.advanceTimersByTimeAsync(10000);
    expect(get).toHaveBeenCalledTimes(1);
    expect(store.letter).toBeNull();
  });

  it("keeps letter null when remove runs during an in-flight fetch", async () => {
    let resolve!: (l: CoverLetterOut) => void;
    get.mockImplementationOnce(() => new Promise((r) => (resolve = r as never)));
    del.mockResolvedValue(undefined as never);
    const store = useCoverLetterStore();
    const p = store.load(7);
    expect(await store.remove(7)).toBe(true);
    resolve(letter());
    await p;
    expect(store.letter).toBeNull();
  });

  it("pdfUrl carries a cache-busting version", () => {
    expect(pdfUrl(7, "2026-01-01T00:00:00Z")).toBe("/api/applications/7/cover-letter/pdf?v=2026-01-01T00:00:00Z");
    expect(pdfUrl(7, null)).toBe("/api/applications/7/cover-letter/pdf?v=0");
  });
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onerror: (() => void) | null = null;
  closed = false;
  private handlers: Record<string, ((e: MessageEvent) => void)[]> = {};
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    (this.handlers[type] ??= []).push(cb);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    for (const cb of this.handlers[type] ?? []) cb({ data: JSON.stringify(data) } as MessageEvent);
  }
  fail() {
    this.onerror?.();
  }
}

describe("cover letter streaming", () => {
  const original = (globalThis as { EventSource?: unknown }).EventSource;
  beforeEach(() => {
    FakeEventSource.instances = [];
    (globalThis as { EventSource?: unknown }).EventSource = FakeEventSource;
  });
  afterEach(() => {
    (globalThis as { EventSource?: unknown }).EventSource = original;
  });

  it("opens exactly one EventSource while generating", async () => {
    vi.useFakeTimers();
    get.mockResolvedValue(letter({ status: "generating" }));
    const store = useCoverLetterStore();
    await store.load(7);
    await store.load(7);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/applications/7/cover-letter/stream");
    store.stopPolling();
  });

  it("does not open a stream for an idle letter", async () => {
    get.mockResolvedValue(letter());
    await useCoverLetterStore().load(7);
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("sets text and phase; end closes, clears and reloads", async () => {
    vi.useFakeTimers();
    get.mockResolvedValueOnce(letter({ status: "generating" })).mockResolvedValue(letter({ content: "Done" }));
    const store = useCoverLetterStore();
    await store.load(7);
    const es = FakeEventSource.instances[0];
    es.emit("text", { phase: "generate", text: "Dear Sir", seq: 1 });
    expect(store.streamText).toBe("Dear Sir");
    expect(store.streamPhase).toBe("generate");
    es.emit("end", {});
    expect(es.closed).toBe(true);
    expect(store.streamText).toBeNull();
    expect(store.streamPhase).toBeNull();
    await vi.advanceTimersByTimeAsync(0);
    expect(get).toHaveBeenCalledTimes(2);
    expect(store.letter?.content).toBe("Done");
    store.stopPolling();
  });

  it("falls back to polling when the stream errors before any text", async () => {
    vi.useFakeTimers();
    get.mockResolvedValue(letter({ status: "generating" }));
    const store = useCoverLetterStore();
    await store.load(7);
    const es = FakeEventSource.instances[0];
    es.fail();
    expect(es.closed).toBe(true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(get).toHaveBeenCalledTimes(2);
    expect(FakeEventSource.instances).toHaveLength(1);
    store.stopPolling();
  });

  it("tolerates one error after text, closes on the second", async () => {
    vi.useFakeTimers();
    get.mockResolvedValue(letter({ status: "generating" }));
    const store = useCoverLetterStore();
    await store.load(7);
    const es = FakeEventSource.instances[0];
    es.emit("text", { phase: "generate", text: "a", seq: 1 });
    es.fail();
    expect(es.closed).toBe(false);
    es.fail();
    expect(es.closed).toBe(true);
    store.stopPolling();
  });

  it("stopPolling closes the stream and clears the text", async () => {
    vi.useFakeTimers();
    get.mockResolvedValue(letter({ status: "generating" }));
    const store = useCoverLetterStore();
    await store.load(7);
    const es = FakeEventSource.instances[0];
    es.emit("text", { phase: "revise", text: "a", seq: 1 });
    store.stopPolling();
    expect(es.closed).toBe(true);
    expect(store.streamText).toBeNull();
  });

  it("ignores late events of application A after load(B)", async () => {
    vi.useFakeTimers();
    get.mockResolvedValueOnce(letter({ status: "generating" })).mockResolvedValue(letter({ application_id: 8 }));
    const store = useCoverLetterStore();
    await store.load(7);
    const es = FakeEventSource.instances[0];
    await store.load(8);
    es.emit("text", { phase: "generate", text: "late", seq: 2 });
    expect(es.closed).toBe(true);
    expect(store.streamText).toBeNull();
  });
});

describe("cover letter templates store", () => {
  const tpl = (id: number, name = `T${id}`): CoverLetterTemplate => ({ id, name, builtin: false, created_at: "2026-01-01T00:00:00Z" });

  it("loads, uploads, renames and removes", async () => {
    const store = useCoverLetterTemplatesStore();
    get.mockResolvedValue([tpl(1)]);
    await store.load();
    expect(get).toHaveBeenCalledWith("/cover-letter-templates");
    expect(store.items).toHaveLength(1);

    upload.mockResolvedValue(tpl(2));
    const file = new File(["x"], "a.tex");
    expect(await store.upload(file)).toBe(true);
    const form = upload.mock.calls[0][1] as FormData;
    expect(upload.mock.calls[0][0]).toBe("/cover-letter-templates");
    expect(form.get("file")).toBeInstanceOf(File);
    expect(store.items.map((t) => t.id)).toEqual([1, 2]);

    patch.mockResolvedValue(tpl(2, "New"));
    expect(await store.rename(2, "New")).toBe(true);
    expect(patch).toHaveBeenCalledWith("/cover-letter-templates/2", { name: "New" });
    expect(store.items[1].name).toBe("New");

    del.mockResolvedValue(undefined as never);
    expect(await store.remove(2)).toBe(true);
    expect(store.items.map((t) => t.id)).toEqual([1]);
  });

  it("returns false and notifies on upload error", async () => {
    upload.mockRejectedValue(new ApiError(422, "template_invalid", {}, "x"));
    const spy = vi.spyOn(useNotifyStore(), "error");
    expect(await useCoverLetterTemplatesStore().upload(new File(["x"], "a.tex"))).toBe(false);
    expect(spy).toHaveBeenCalledOnce();
  });
});
