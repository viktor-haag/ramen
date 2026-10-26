import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "@/api/client";
import type { CoverLetterTemplate } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

/** LaTeX cover letter templates. Mutations report errors via notify and return success. */
export const useCoverLetterTemplatesStore = defineStore("coverLetterTemplates", () => {
  const items = ref<CoverLetterTemplate[]>([]);
  const loaded = ref(false);

  async function load() {
    try {
      items.value = await api.get<CoverLetterTemplate[]>("/cover-letter-templates");
      loaded.value = true;
    } catch (e) {
      useNotifyStore().error(e);
    }
  }

  async function upload(file: File): Promise<boolean> {
    try {
      const form = new FormData();
      form.append("file", file);
      items.value.push(await api.upload<CoverLetterTemplate>("/cover-letter-templates", form));
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  async function rename(id: number, name: string): Promise<boolean> {
    try {
      const t = await api.patch<CoverLetterTemplate>(`/cover-letter-templates/${id}`, { name });
      const i = items.value.findIndex((x) => x.id === id);
      if (i >= 0) items.value[i] = t;
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  async function remove(id: number): Promise<boolean> {
    try {
      await api.del(`/cover-letter-templates/${id}`);
      items.value = items.value.filter((x) => x.id !== id);
      return true;
    } catch (e) {
      useNotifyStore().error(e);
      return false;
    }
  }

  return { items, loaded, load, upload, rename, remove };
});
