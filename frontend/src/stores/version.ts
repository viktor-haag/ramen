import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "@/api/client";
import type { VersionInfo } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

export const DISMISSED_KEY = "jobtracker.dismissedUpdate";
export const REFRESH_MS = 3_600_000;

function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISSED_KEY);
  } catch {
    return null; /* storage unavailable */
  }
}

export const useVersionStore = defineStore("version", () => {
  const info = ref<VersionInfo | null>(null);
  /** The release the user hid; a newer one shows the chip again. Kept in memory even when storage fails. */
  const dismissed = ref<string | null>(readDismissed());
  let lastLoad = 0;
  let watching = false;

  const showChip = computed(() => {
    const i = info.value;
    return !!i && i.update_available && !!i.latest && !!i.release_url && dismissed.value !== i.latest;
  });

  /** Background read: a failure keeps the last known result and shows nothing. */
  async function load(): Promise<void> {
    lastLoad = Date.now();
    try {
      info.value = await api.get<VersionInfo>("/version");
    } catch {
      /* keep the last result */
    }
  }

  /** Manual check (the About card); failures are reported. */
  async function checkNow(): Promise<void> {
    try {
      info.value = await api.post<VersionInfo>("/version/check");
      lastLoad = Date.now();
    } catch (e) {
      useNotifyStore().error(e);
    }
  }

  function dismiss(version: string): void {
    dismissed.value = version;
    try {
      localStorage.setItem(DISMISSED_KEY, version);
    } catch {
      /* storage unavailable */
    }
  }

  /** Reload when the tab becomes visible again and the last load is at least REFRESH_MS ago. */
  function startAutoRefresh(): void {
    if (watching) return;
    watching = true;
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && Date.now() - lastLoad >= REFRESH_MS) void load();
    });
  }

  return { info, showChip, load, checkNow, dismiss, startAutoRefresh };
});
