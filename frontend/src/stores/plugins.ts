import { defineStore } from "pinia";
import { ref } from "vue";
import { ApiError, api, validationFieldErrors } from "@/api/client";
import type { PluginOut, PluginUpdate } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

export type SaveResult = { ok: true } | { ok: false; errors: Record<string, string> };

export const useSettingsPluginsStore = defineStore("plugins", () => {
  const items = ref<PluginOut[]>([]);
  const loaded = ref(false);

  async function load() {
    try {
      items.value = await api.get<PluginOut[]>("/plugins");
      loaded.value = true;
    } catch (e) {
      useNotifyStore().error(e);
    }
  }

  /** Save one plugin. Field errors are returned, everything else is reported via notify. */
  async function save(name: string, body: PluginUpdate): Promise<SaveResult> {
    try {
      const updated = await api.put<PluginOut>(`/plugins/${encodeURIComponent(name)}`, body);
      items.value = items.value.map((p) => (p.name === name ? updated : p));
      return { ok: true };
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.code === "validation_error") {
        const errors = validationFieldErrors(e, ["body", "settings"]);
        if (Object.keys(errors).length > 0) return { ok: false, errors };
      }
      useNotifyStore().error(e);
      return { ok: false, errors: {} };
    }
  }

  return { items, loaded, load, save };
});
