import { defineStore } from "pinia";
import { ref } from "vue";
import { ApiError, api, BASE, toQuery } from "@/api/client";
import type { CoverLetterIn, CoverLetterLanguage, CoverLetterOut } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

const POLL_MS = 2000;

/** URL of the compiled PDF; `compiledAt` busts the browser cache after every recompile. */
export function pdfUrl(appId: number, compiledAt: string | null): string {
  return `${BASE}/applications/${appId}/cover-letter/pdf?v=${compiledAt ?? ""}`;
}

/** The cover letter of one application. Polls while it is generating or compiling. */
export const useCoverLetterStore = defineStore("coverLetter", () => {
  const letter = ref<CoverLetterOut | null>(null);
  const loading = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pollApp: number | null = null;
  let ticking = false;

  function stopPolling() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    pollApp = null;
  }

  function schedule(appId: number) {
    stopPolling();
    if (!letter.value || letter.value.status === "idle") return;
    pollApp = appId;
    timer = setTimeout(() => void tick(appId), POLL_MS);
  }

  async function tick(appId: number) {
    timer = undefined;
    if (ticking || pollApp !== appId) return;
    ticking = true;
    try {
      await fetchLetter(appId);
    } finally {
      ticking = false;
    }
    // fetchLetter reschedules on success; keep polling after a transient error too.
    if (timer === undefined && pollApp === appId && letter.value && letter.value.status !== "idle") schedule(appId);
  }

  async function fetchLetter(appId: number) {
    try {
      letter.value = await api.get<CoverLetterOut>(`/applications/${appId}/cover-letter`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) letter.value = null;
      else useNotifyStore().error(e);
    }
    schedule(appId);
  }

  async function load(appId: number) {
    loading.value = true;
    try {
      await fetchLetter(appId);
    } finally {
      loading.value = false;
    }
  }

  async function mutate(appId: number, call: () => Promise<CoverLetterOut>): Promise<boolean> {
    try {
      letter.value = await call();
      schedule(appId);
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

  async function attach(appId: number, lang: CoverLetterLanguage | "de" | "en"): Promise<boolean> {
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
      stopPolling();
      letter.value = null;
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  return { letter, loading, load, create, saveContent, send, repair, attach, remove, stopPolling };
});
