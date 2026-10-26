import { defineStore } from "pinia";
import { ref } from "vue";
import { ApiError, api, BASE, toQuery } from "@/api/client";
import type { CoverLetterIn, CoverLetterOut } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

const POLL_MS = 2000;

/** URL of the compiled PDF; `compiledAt` busts the browser cache after every recompile. */
export function pdfUrl(appId: number, compiledAt: string | null): string {
  return `${BASE}/applications/${appId}/cover-letter/pdf?v=${compiledAt ?? 0}`;
}

/** The cover letter of one application. Polls while it is generating or compiling. */
export const useCoverLetterStore = defineStore("coverLetter", () => {
  const letter = ref<CoverLetterOut | null>(null);
  const loading = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  // Request generation: bumped by stopPolling() and load(); responses from an older generation are dropped.
  let gen = 0;

  function clearTimer() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  function stopPolling() {
    gen++;
    clearTimer();
    loading.value = false;
  }

  function schedule(appId: number) {
    clearTimer();
    if (!letter.value || letter.value.status === "idle") return;
    const g = gen;
    timer = setTimeout(() => {
      timer = undefined;
      if (g === gen) void fetchLetter(appId, g);
    }, POLL_MS);
  }

  async function fetchLetter(appId: number, g: number) {
    let next: CoverLetterOut | null = null;
    try {
      next = await api.get<CoverLetterOut>(`/applications/${appId}/cover-letter`);
    } catch (e) {
      if (g !== gen) return;
      if (e instanceof ApiError && e.status === 404) letter.value = null;
      else useNotifyStore().error(e);
      schedule(appId);
      return;
    }
    if (g !== gen || next.application_id !== appId) return;
    letter.value = next;
    schedule(appId);
  }

  async function load(appId: number) {
    gen++;
    clearTimer();
    const g = gen;
    loading.value = true;
    try {
      await fetchLetter(appId, g);
    } finally {
      if (g === gen) loading.value = false;
    }
  }

  async function mutate(appId: number, call: () => Promise<CoverLetterOut>): Promise<boolean> {
    const g = gen;
    try {
      const next = await call();
      if (g === gen && next.application_id === appId) {
        letter.value = next;
        schedule(appId);
      }
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  const base = (appId: number) => `/applications/${appId}/cover-letter`;

  const create = (appId: number, data: CoverLetterIn) => mutate(appId, () => api.post<CoverLetterOut>(base(appId), data));
  const saveContent = (appId: number, content: string) => mutate(appId, () => api.put<CoverLetterOut>(`${base(appId)}/content`, { content }));
  const send = (appId: number, text: string) => mutate(appId, () => api.post<CoverLetterOut>(`${base(appId)}/messages`, { text }));
  const repair = (appId: number) => mutate(appId, () => api.post<CoverLetterOut>(`${base(appId)}/repair`));

  async function attach(appId: number, lang: "de" | "en"): Promise<boolean> {
    try {
      await api.post(`${base(appId)}/attach?${toQuery({ lang })}`);
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  async function remove(appId: number): Promise<boolean> {
    try {
      await api.del(base(appId));
      stopPolling(); // also drops responses of requests still in flight
      letter.value = null;
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  return { letter, loading, load, create, saveContent, send, repair, attach, remove, stopPolling };
});
