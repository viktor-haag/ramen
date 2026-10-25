import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { BASE, api, toQuery } from "@/api/client";
import type { AppStatus, ApplicationDetailOut, ApplicationOut } from "@/api/types";
import { ACTIVE_STATUSES, TERMINAL_STATUSES } from "@/domain/status";
import { i18n } from "@/i18n";
import { useNotifyStore } from "@/stores/notify";

export type ApplicationsViewMode = "board" | "table";

export const APPLICATIONS_VIEW_KEY = "jobtracker.applicationsView";
export const HIDE_SAVED_KEY = "jobtracker.hideSaved";
const ALL_STATUSES: AppStatus[] = [...ACTIVE_STATUSES, ...TERMINAL_STATUSES];

function loadView(): ApplicationsViewMode {
  try {
    const v = localStorage.getItem(APPLICATIONS_VIEW_KEY);
    if (v === "board" || v === "table") return v;
  } catch {
    /* storage unavailable */
  }
  return "board";
}

function loadHideSaved(): boolean {
  try {
    return localStorage.getItem(HIDE_SAVED_KEY) === "true";
  } catch {
    return false;
  }
}

export const useApplicationsStore = defineStore("applications", () => {
  const items = ref<ApplicationOut[]>([]);
  const showTerminal = ref(false);
  const view = ref<ApplicationsViewMode>(loadView());
  const hideSaved = ref(loadHideSaved());
  const q = ref<string | null>("");
  const loading = ref(false);
  let generation = 0;

  watch(view, (v) => {
    // The search field only exists in the table; don't leave a hidden filter active on the board.
    if (v === "board" && (q.value ?? "").trim() !== "") {
      q.value = "";
      void load();
    }
    try {
      localStorage.setItem(APPLICATIONS_VIEW_KEY, v);
    } catch {
      /* storage unavailable */
    }
  });

  watch(hideSaved, (v) => {
    try {
      localStorage.setItem(HIDE_SAVED_KEY, String(v));
    } catch {
      /* storage unavailable */
    }
  });

  /** Board columns: active statuses, plus finished ones on request, without "saved" when hidden. */
  const visibleStatuses = computed<AppStatus[]>(() =>
    (showTerminal.value ? ALL_STATUSES : ACTIVE_STATUSES).filter((s) => !(hideSaved.value && s === "saved")),
  );

  /** Table rows: all loaded items, without "saved" ones when hidden. */
  const visibleItems = computed(() => (hideSaved.value ? items.value.filter((a) => a.status !== "saved") : items.value));

  const byStatus = computed(() => {
    const groups = Object.fromEntries(ALL_STATUSES.map((s) => [s, [] as ApplicationOut[]])) as Record<AppStatus, ApplicationOut[]>;
    for (const a of items.value) groups[a.status]?.push(a);
    return groups;
  });

  /** Download URL for the current view's applications (same filters as the board/table, "saved" dropped when hidden). */
  function exportUrl(format: "csv" | "xlsx"): string {
    const status = visibleStatuses.value;
    const query = toQuery({ format, status, q: (q.value ?? "").trim(), lang: i18n.global.locale.value });
    return `${BASE}/applications/export?${query}`;
  }

  async function load() {
    const mine = ++generation;
    loading.value = true;
    try {
      const status = showTerminal.value ? ALL_STATUSES : ACTIVE_STATUSES;
      const list = await api.get<ApplicationOut[]>("/applications", { status, q: (q.value ?? "").trim() });
      if (mine === generation) items.value = list;
    } catch (e) {
      if (mine === generation) useNotifyStore().error(e);
    } finally {
      if (mine === generation) loading.value = false;
    }
  }

  /**
   * Shared core of move() and reopen(): optimistically set the new status, POST it,
   * apply the response fields, and roll back status and position on any API error.
   */
  async function changeStatus(id: number, to: AppStatus, path: "status" | "reopen") {
    const idx = items.value.findIndex((a) => a.id === id);
    if (idx < 0) return;
    const app = items.value[idx]!;
    const from = app.status;
    if (from === to) return;
    app.status = to;
    // Append to the end of the target column (column order follows list order).
    items.value.splice(idx, 1);
    items.value.push(app);
    try {
      const res = await api.post<ApplicationDetailOut | undefined>(`/applications/${id}/${path}`, { to });
      const cur = items.value.find((a) => a.id === id);
      if (cur && res) {
        cur.status = res.status;
        cur.updated_at = res.updated_at;
        cur.last_status_change_at = res.last_status_change_at;
      }
    } catch (e) {
      const cur = items.value.findIndex((a) => a.id === id);
      if (cur >= 0) {
        const [back] = items.value.splice(cur, 1);
        back!.status = from;
        items.value.splice(Math.min(idx, items.value.length), 0, back!);
      }
      useNotifyStore().error(e);
    }
  }

  /** Optimistically move an application to another status; roll back on any API error. */
  const move = (id: number, to: AppStatus) => changeStatus(id, to, "status");

  /** Optimistically reopen a finished application into an active status; roll back on any API error. */
  const reopen = (id: number, to: AppStatus) => changeStatus(id, to, "reopen");

  /** Drop all loaded applications (data was wiped on the server). */
  function clear() {
    generation++;
    items.value = [];
    loading.value = false;
  }

  return { items, showTerminal, hideSaved, view, q, loading, byStatus, visibleStatuses, visibleItems, exportUrl, load, move, reopen, clear };
});
