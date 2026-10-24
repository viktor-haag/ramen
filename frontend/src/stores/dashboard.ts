import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "@/api/client";
import type { DashboardOut } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

export const useDashboardStore = defineStore("dashboard", () => {
  const data = ref<DashboardOut | null>(null);
  const loading = ref(false);
  const failed = ref(false);

  async function load() {
    loading.value = true;
    failed.value = false;
    try {
      data.value = await api.get<DashboardOut>("/dashboard");
    } catch (e) {
      failed.value = true;
      useNotifyStore().error(e);
    } finally {
      loading.value = false;
    }
  }

  function clear() {
    data.value = null;
    failed.value = false;
  }

  return { data, loading, failed, load, clear };
});
