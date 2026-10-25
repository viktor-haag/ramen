import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "@/api/client";
import type { PromptOut, PromptPurpose } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

/** The three editable prompts. Mutations report errors via notify and return success. */
export const usePromptsStore = defineStore("prompts", () => {
  const items = ref<PromptOut[]>([]);
  const loaded = ref(false);

  function replace(p: PromptOut) {
    const i = items.value.findIndex((x) => x.purpose === p.purpose);
    if (i >= 0) items.value[i] = p;
    else items.value.push(p);
  }

  async function load() {
    try {
      items.value = await api.get<PromptOut[]>("/prompts");
      loaded.value = true;
    } catch (e) {
      useNotifyStore().error(e);
    }
  }

  async function save(purpose: PromptPurpose, text: string): Promise<boolean> {
    try {
      replace(await api.put<PromptOut>(`/prompts/${purpose}`, { text }));
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  async function reset(purpose: PromptPurpose): Promise<boolean> {
    try {
      replace(await api.del<PromptOut>(`/prompts/${purpose}`));
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  return { items, loaded, load, save, reset };
});
