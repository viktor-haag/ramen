import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "@/api/client";
import type { FeedFilter, FeedPage, PostingOut, TriageStatus } from "@/api/types";
import { TRIAGE_STATUSES } from "@/api/types";
import { useNotifyStore } from "@/stores/notify";

export type FoundRange = "today" | "7d" | "30d" | "all";

export const FEED_FILTER_KEY = "jobtracker.feedFilter";
export const PAGE_SIZE = 30;
const RANGE_DAYS: Record<Exclude<FoundRange, "all">, number> = { today: 1, "7d": 7, "30d": 30 };

type StoredFilter = Omit<FeedFilter, "found_after" | "found_before" | "offset" | "limit">;

function defaultFilter(): StoredFilter {
  return { triage: ["new", "saved"], source: [] };
}

function loadStored(): { filter: StoredFilter; foundRange: FoundRange } {
  const fallback = { filter: defaultFilter(), foundRange: "all" as FoundRange };
  try {
    const raw = localStorage.getItem(FEED_FILTER_KEY);
    if (!raw) return fallback;
    const data = JSON.parse(raw) as { filter?: StoredFilter; foundRange?: FoundRange };
    const range = data.foundRange && (data.foundRange === "all" || data.foundRange in RANGE_DAYS) ? data.foundRange : "all";
    const stored = data.filter && typeof data.filter === "object" ? data.filter : {};
    return { filter: { ...defaultFilter(), ...stored }, foundRange: range };
  } catch {
    return fallback;
  }
}

/** Status a posting gets after a triage action. */
const RESULT: Record<"save" | "unsave" | "dismiss" | "undismiss", TriageStatus> = {
  save: "saved",
  unsave: "new",
  dismiss: "dismissed",
  undismiss: "new",
};

export const useFeedStore = defineStore("feed", () => {
  const stored = loadStored();
  const filter = ref<StoredFilter>(stored.filter);
  const foundRange = ref<FoundRange>(stored.foundRange);
  const items = ref<PostingOut[]>([]);
  const total = ref(0);
  const loading = ref(false);
  const selectedIndex = ref(-1);
  /** Bumped whenever a reset has replaced the list; lets the infinite scroller re-arm itself. */
  const resetCount = ref(0);
  /** Bumped after each successfully loaded further page (lets the fit poll resume). */
  const pageCount = ref(0);
  /** True when the last page fetch failed. */
  const loadError = ref(false);
  let generation = 0;

  const hasMore = computed(() => items.value.length < total.value);

  function query(offset: number): Record<string, unknown> {
    // No chip selected means "all statuses" (the backend would otherwise default to new+saved).
    const triage = filter.value.triage?.length ? filter.value.triage : TRIAGE_STATUSES;
    const params: Record<string, unknown> = { ...filter.value, triage, offset, limit: PAGE_SIZE };
    if (foundRange.value !== "all") {
      params.found_after = new Date(Date.now() - RANGE_DAYS[foundRange.value] * 86400_000).toISOString();
    }
    return params;
  }

  /** The current filter as feed query parameters without paging (used by bulk actions on everything the filter matches). */
  function filterQuery(): Record<string, unknown> {
    const { offset: _offset, limit: _limit, ...rest } = query(0);
    return rest;
  }

  function persist() {
    try {
      localStorage.setItem(FEED_FILTER_KEY, JSON.stringify({ filter: filter.value, foundRange: foundRange.value }));
    } catch {
      /* storage unavailable */
    }
  }

  async function fetchPage(offset: number): Promise<FeedPage | null> {
    const mine = ++generation;
    loading.value = true;
    loadError.value = false;
    try {
      const page = await api.get<FeedPage>("/feed", query(offset));
      return mine === generation ? page : null;
    } catch (e) {
      if (mine === generation) {
        loadError.value = true;
        useNotifyStore().error(e);
      }
      return null;
    } finally {
      if (mine === generation) loading.value = false;
    }
  }

  /** Reload from the first page with the current filter. */
  async function reset() {
    persist();
    const page = await fetchPage(0);
    if (!page) return;
    items.value = page.items;
    total.value = page.total;
    selectedIndex.value = -1;
    resetCount.value++;
  }

  /** Back to the default filter and persist it (IDs may be reused after a data wipe, stale profile/source filters would mislead). */
  function resetFilter() {
    filter.value = defaultFilter();
    foundRange.value = "all";
    persist();
  }

  /** Drop all loaded postings (data was wiped on the server). */
  function clear() {
    generation++;
    items.value = [];
    total.value = 0;
    loading.value = false;
    loadError.value = false;
    selectedIndex.value = -1;
    resetCount.value++;
  }

  async function loadMore() {
    if (loading.value || items.value.length >= total.value) return;
    const page = await fetchPage(items.value.length);
    if (!page) return;
    const known = new Set(items.value.map((i) => i.id));
    items.value.push(...page.items.filter((i) => !known.has(i.id)));
    total.value = page.total;
    pageCount.value++;
  }

  function matchesFilter(status: TriageStatus): boolean {
    const wanted = filter.value.triage;
    return !wanted || wanted.length === 0 || wanted.includes(status);
  }

  async function act(id: number, action: keyof typeof RESULT): Promise<TriageStatus | null> {
    try {
      await api.post(`/postings/${id}/${action}`);
    } catch (e) {
      useNotifyStore().error(e);
      return null;
    }
    const status = RESULT[action];
    const idx = items.value.findIndex((i) => i.id === id);
    if (idx >= 0) {
      if (matchesFilter(status)) {
        items.value[idx]!.triage_status = status;
      } else {
        items.value.splice(idx, 1);
        total.value = Math.max(0, total.value - 1);
        selectedIndex.value = Math.min(selectedIndex.value, items.value.length - 1);
      }
    }
    return status;
  }

  const save = (id: number) => act(id, "save");
  const unsave = (id: number) => act(id, "unsave");
  const dismiss = (id: number) => act(id, "dismiss");
  const undismiss = (id: number) => act(id, "undismiss");

  const toggleSave = (p: Pick<PostingOut, "id" | "triage_status">) => (p.triage_status === "saved" ? unsave(p.id) : save(p.id));
  /** A posting with an application (saved) cannot be dismissed; the backend would answer 409. */
  const canDismiss = (p: Pick<PostingOut, "triage_status"> & { application_id?: number | null }) =>
    p.triage_status !== "saved" && p.application_id == null;
  const toggleDismiss = (p: Pick<PostingOut, "id" | "triage_status"> & { application_id?: number | null }) => {
    if (p.triage_status === "dismissed") return undismiss(p.id);
    return canDismiss(p) ? dismiss(p.id) : Promise.resolve(null);
  };

  function selectNext() {
    if (items.value.length) selectedIndex.value = Math.min(selectedIndex.value + 1, items.value.length - 1);
  }
  function selectPrev() {
    if (items.value.length) selectedIndex.value = Math.max(selectedIndex.value - 1, 0);
  }

  return {
    filter, foundRange, items, total, loading, selectedIndex, hasMore, resetCount, pageCount, loadError,
    reset, resetFilter, clear, loadMore, filterQuery, save, unsave, dismiss, undismiss, toggleSave, toggleDismiss, canDismiss, selectNext, selectPrev,
  };
});
