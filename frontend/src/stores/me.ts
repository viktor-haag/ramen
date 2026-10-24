import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ApiError, api, validationFieldErrors } from "@/api/client";
import type { DocumentPatch, LlmConfigOut, ProfileDocumentOut, UserProfileOut } from "@/api/types";
import { i18n } from "@/i18n";
import { useLlmStore } from "@/stores/llm";
import { useNotifyStore } from "@/stores/notify";
import type { SaveResult } from "@/stores/plugins";

const norm = (v: string | null | undefined) => v || null; // "" and null are the same "empty"

export const useMeStore = defineStore("me", () => {
  const profile = ref<UserProfileOut | null>(null);
  const documents = ref<ProfileDocumentOut[]>([]);
  const loaded = ref(false);
  /** True after a single action ran over the daily limit; cleared by the next successful action. */
  const limitExceeded = ref(false);
  const generating = ref(false);
  /** Ids of documents whose extraction is running. */
  const extracting = ref<Set<number>>(new Set());
  /** Saves (free text / markdown) that are still in flight; generate waits for them. */
  const inflight = new Set<Promise<unknown>>();

  const notify = () => useNotifyStore();

  // --- resolved LLM configurations (purpose -> config, else the default configuration) ---
  function resolve(purpose: "profile" | "extraction"): LlmConfigOut | null {
    const llm = useLlmStore();
    const id = llm.purposes[purpose];
    return (id !== null ? llm.configs.find((c) => c.id === id) : undefined) ?? llm.configs.find((c) => c.is_default) ?? null;
  }
  const profileConfig = computed(() => resolve("profile"));
  const extractionConfig = computed(() => resolve("extraction"));
  /** Display name of the provider that receives the data for profile generation. */
  const label = (c: LlmConfigOut | null) => (c ? `${i18n.global.t(`ai.providers.${c.provider}`)} (${c.model})` : "");
  const providerName = computed(() => label(profileConfig.value));
  /** Provider that receives images/scans, or "" when it is the same as for the profile or cannot read images. */
  const extractionProviderName = computed(() => {
    const c = extractionConfig.value;
    return c && c.supports_images && c.id !== profileConfig.value?.id ? label(c) : "";
  });
  const canExtract = computed(() => extractionConfig.value?.supports_images === true);

  async function guarded<T>(fn: () => Promise<T>): Promise<T | undefined> {
    try {
      return await fn();
    } catch (e) {
      notify().error(e);
      return undefined;
    }
  }

  async function load() {
    const llm = useLlmStore();
    const [d, p, l] = await Promise.allSettled([
      api.get<ProfileDocumentOut[]>("/me/documents"),
      api.get<UserProfileOut>("/me/profile"),
      llm.load(), // always: configurations may have been reset or changed elsewhere
    ]);
    if (d.status === "fulfilled") documents.value = d.value;
    if (p.status === "fulfilled") profile.value = p.value;
    loaded.value = d.status === "fulfilled" && p.status === "fulfilled";
    const failed = [d, p, l].find((r): r is PromiseRejectedResult => r.status === "rejected");
    if (failed) notify().error(failed.reason);
  }

  /** Document changes flip the "inputs changed" flag and the used/unused counts server-side. */
  async function refreshProfile() {
    try {
      profile.value = await api.get<UserProfileOut>("/me/profile");
    } catch {
      /* the flags are only informative; the next load() corrects them */
    }
  }

  function replaceDocument(d: ProfileDocumentOut) {
    const i = documents.value.findIndex((x) => x.id === d.id);
    if (i >= 0) documents.value.splice(i, 1, d);
    else documents.value.push(d);
  }

  async function upload(file: File, description: string): Promise<boolean> {
    const form = new FormData();
    form.append("file", file);
    if (description.trim()) form.append("description", description.trim());
    const d = await guarded(() => api.upload<ProfileDocumentOut>("/me/documents", form));
    if (!d) return false;
    replaceDocument(d);
    await refreshProfile();
    return true;
  }

  async function updateDocument(id: number, patch: DocumentPatch): Promise<boolean> {
    const d = await guarded(() => api.patch<ProfileDocumentOut>(`/me/documents/${id}`, patch));
    if (!d) return false;
    replaceDocument(d);
    await refreshProfile();
    return true;
  }

  async function extract(id: number): Promise<boolean> {
    extracting.value = new Set(extracting.value).add(id);
    try {
      const res = await guarded(() => api.post<{ document: ProfileDocumentOut; limit_exceeded: boolean }>(`/me/documents/${id}/extract`));
      if (!res) return false;
      replaceDocument(res.document);
      limitExceeded.value = res.limit_exceeded;
      await refreshProfile();
      return true;
    } finally {
      const next = new Set(extracting.value);
      next.delete(id);
      extracting.value = next;
    }
  }

  async function removeDocument(id: number): Promise<boolean> {
    if ((await guarded(async () => (await api.del(`/me/documents/${id}`), true))) !== true) return false;
    documents.value = documents.value.filter((d) => d.id !== id);
    await refreshProfile();
    return true;
  }

  /** Remember a save in flight so generate can wait for it. */
  function track<T>(p: Promise<T>): Promise<T> {
    inflight.add(p);
    void p.finally(() => inflight.delete(p));
    return p;
  }
  /** Resolves when all saves started so far have finished. */
  async function settled() {
    while (inflight.size > 0) await Promise.allSettled([...inflight]);
  }

  /** Save a profile edit; 422 field errors are returned for inline display, anything else goes to the snackbar. */
  async function savePut(path: string, body: unknown): Promise<SaveResult> {
    try {
      profile.value = await api.put<UserProfileOut>(path, body);
      return { ok: true };
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.code === "validation_error") {
        const errors = validationFieldErrors(e, ["body"]);
        if (Object.keys(errors).length > 0) return { ok: false, errors };
      }
      notify().error(e);
      return { ok: false, errors: {} };
    }
  }

  /** Autosave: does nothing when the text equals the saved one. */
  async function saveFreeText(text: string): Promise<SaveResult> {
    if (norm(text) === norm(profile.value?.free_text)) return { ok: true };
    return track(savePut("/me/profile/free-text", { free_text: norm(text) }));
  }

  async function saveMarkdown(markdown: string): Promise<SaveResult> {
    if (markdown === (profile.value?.profile_markdown ?? "")) return { ok: true };
    return track(savePut("/me/profile/markdown", { profile_markdown: markdown }));
  }

  /** Create or recreate the profile. `overwrite` is required once the profile was edited manually. */
  async function generate(overwrite: boolean): Promise<boolean> {
    generating.value = true;
    try {
      const path = overwrite ? "/me/profile/generate?overwrite=true" : "/me/profile/generate";
      const res = await api.post<{ profile: UserProfileOut; limit_exceeded: boolean }>(path);
      profile.value = res.profile;
      limitExceeded.value = res.limit_exceeded;
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.code === "profile_edited") {
        // edited between our check and the request: show the current state, never overwrite silently
        await refreshProfile();
        notify().show(i18n.global.t("me.profile.changedWhileGenerating"));
      } else {
        notify().error(e);
      }
      return false;
    } finally {
      generating.value = false;
    }
  }

  function clear() {
    profile.value = null;
    documents.value = [];
    loaded.value = false;
    limitExceeded.value = false;
  }

  return {
    profile, documents, loaded, limitExceeded, generating, extracting,
    profileConfig, extractionConfig, providerName, extractionProviderName, canExtract,
    load, settled, upload, updateDocument, extract, removeDocument, saveFreeText, saveMarkdown, generate, clear,
  };
});
