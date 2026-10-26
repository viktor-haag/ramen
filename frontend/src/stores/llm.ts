import { defineStore } from "pinia";
import { ref } from "vue";
import { ApiError, api, validationFieldErrors } from "@/api/client";
import type { AppSettings, LlmConfigIn, LlmConfigOut, LlmModelsIn, LlmPurposes, LlmTestOut, LlmUsageOut } from "@/api/types";
import { errorMessage } from "@/i18n";
import { useNotifyStore } from "@/stores/notify";
import type { SaveResult } from "@/stores/plugins";

export type TestResult = { ok: true; model: string; latencyMs: number } | { ok: false; message: string };

export const useLlmStore = defineStore("llm", () => {
  const configs = ref<LlmConfigOut[]>([]);
  const purposes = ref<LlmPurposes>({ profile: null, fit: null, extraction: null, cover_letter: null });
  const settings = ref<AppSettings | null>(null);
  const usage = ref<LlmUsageOut | null>(null);
  const loaded = ref(false);

  const notify = () => useNotifyStore();

  /**
   * Run a save call. 422 field errors are returned; when none of them belongs to a field the caller shows
   * (`visible`), the error also goes to the snackbar so it is never lost. Other errors go to the snackbar.
   */
  async function guarded(fn: () => Promise<void>, visible?: string[]): Promise<SaveResult> {
    try {
      await fn();
      return { ok: true };
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.code === "validation_error") {
        const errors = validationFieldErrors(e, ["body"]);
        const keys = Object.keys(errors);
        if (keys.length > 0) {
          if (visible && !keys.some((k) => visible.includes(k))) notify().error(e);
          return { ok: false, errors };
        }
      }
      notify().error(e);
      return { ok: false, errors: {} };
    }
  }

  async function loadConfigs() {
    configs.value = await api.get<LlmConfigOut[]>("/llm/configs");
  }
  async function loadUsage() {
    usage.value = await api.get<LlmUsageOut>("/llm/usage");
  }

  async function load() {
    const [c, p, s, u] = await Promise.allSettled([
      api.get<LlmConfigOut[]>("/llm/configs"),
      api.get<LlmPurposes>("/llm/purposes"),
      api.get<AppSettings>("/settings"),
      api.get<LlmUsageOut>("/llm/usage"),
    ]);
    if (c.status === "fulfilled") configs.value = c.value;
    if (p.status === "fulfilled") purposes.value = p.value;
    if (s.status === "fulfilled") settings.value = s.value;
    if (u.status === "fulfilled") usage.value = u.value;
    loaded.value = [c, p, s, u].every((r) => r.status === "fulfilled");
    const failed = [c, p, s, u].find((r): r is PromiseRejectedResult => r.status === "rejected");
    if (failed) notify().error(failed.reason); // one message even when several parts failed
  }

  /** Create (no `id`) or update a configuration. */
  async function save(cfg: LlmConfigIn, id?: number, visible?: string[]): Promise<SaveResult> {
    return guarded(async () => {
      if (id === undefined) await api.post<LlmConfigOut>("/llm/configs", cfg);
      else await api.put<LlmConfigOut>(`/llm/configs/${id}`, cfg);
      await loadConfigs(); // the default flag may have moved
    }, visible);
  }

  async function remove(id: number): Promise<boolean> {
    try {
      await api.del(`/llm/configs/${id}`);
      await loadConfigs();
      return true;
    } catch (e) {
      notify().error(e);
      return false;
    }
  }

  async function setDefault(id: number): Promise<boolean> {
    try {
      await api.post<LlmConfigOut>(`/llm/configs/${id}/default`);
      await loadConfigs();
      return true;
    } catch (e) {
      notify().error(e);
      return false;
    }
  }

  /** Connection test; the outcome (including the error text) is returned for inline display. */
  async function test(id: number): Promise<TestResult> {
    let result: TestResult;
    try {
      const res = await api.post<LlmTestOut>(`/llm/configs/${id}/test`);
      result = { ok: true, model: res.model, latencyMs: res.latency_ms };
    } catch (e) {
      result = { ok: false, message: e instanceof ApiError ? errorMessage(e) : e instanceof Error ? e.message : String(e) };
    }
    await loadUsage().catch(() => {}); // the test call is recorded as usage
    return result;
  }

  /** Model ids offered by the provider, or null when the call failed (already reported). */
  async function loadModels(input: LlmModelsIn): Promise<string[] | null> {
    try {
      return await api.post<string[]>("/llm/models", input);
    } catch (e) {
      notify().error(e);
      return null;
    }
  }

  async function savePurposes(body: LlmPurposes = purposes.value): Promise<SaveResult> {
    return guarded(async () => {
      purposes.value = await api.put<LlmPurposes>("/llm/purposes", body);
    }, []);
  }

  async function saveSettings(body: AppSettings, visible?: string[]): Promise<SaveResult> {
    const res = await guarded(async () => {
      settings.value = await api.put<AppSettings>("/settings", body);
    }, visible);
    if (res.ok) await loadUsage().catch(() => {}); // limit_exceeded depends on the saved limit; a stale value is harmless
    return res;
  }

  /** Forget everything (after "Reset everything" the server state is gone). */
  function clear() {
    configs.value = [];
    purposes.value = { profile: null, fit: null, extraction: null, cover_letter: null };
    settings.value = null;
    usage.value = null;
    loaded.value = false;
  }

  return { configs, purposes, settings, usage, loaded, load, save, remove, setDefault, test, loadModels, savePurposes, saveSettings, clear };
});
