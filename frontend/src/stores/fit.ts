import { defineStore } from "pinia";
import { computed, reactive, ref, watch } from "vue";
import { ApiError, api, toQuery } from "@/api/client";
import type { CancelOut, CountOut, EnqueueOut, FitItemOut, FitOut, FitStatusOut } from "@/api/types";
import { i18n } from "@/i18n";
import { useFeedStore } from "@/stores/feed";
import { useNotifyStore } from "@/stores/notify";

export const FIT_POLL_MS = 2000;
export const MAX_POLL_FAILURES = 5;
const COUNT_DEBOUNCE_MS = 300;
const MAX_IDS = 200; // GET /fit accepts at most 200 ids

export const useFitStore = defineStore("fit", () => {
  const feed = useFeedStore();
  const notify = useNotifyStore();
  const status = ref<FitStatusOut>({ profile: false, configured: false, active: 0 });
  /** True once /fit/status has been read successfully (no hint before that). */
  const statusLoaded = ref(false);
  /** A profile exists and an LLM is configured for the fit purpose. */
  const ready = computed(() => !!status.value.profile && !!status.value.configured);
  /** Postings a bulk run over the current filter would evaluate; null while unknown. */
  const bulkTotal = ref<number | null>(null);

  const lang = () => i18n.global.locale.value;
  const t = (key: string, ...args: unknown[]) => (i18n.global.t as (k: string, ...a: unknown[]) => string)(key, ...args);

  /** `quiet` (background refresh): a failure keeps the last known status and shows nothing. */
  async function loadStatus(opts: { quiet?: boolean } = {}) {
    try {
      status.value = await api.get<FitStatusOut>("/fit/status");
      statusLoaded.value = true;
    } catch (e) {
      if (opts.quiet) return;
      statusLoaded.value = false;
      notify.error(e);
    }
  }

  /** Fit-specific wording (with a link to the place that fixes it) for the 409s whose generic texts talk about other features. */
  function showError(e: unknown) {
    if (e instanceof ApiError && e.code === "profile_missing") {
      notify.show(t("fit.needsProfile"), "error", { label: t("fit.openProfile"), to: "/me" });
    } else if (e instanceof ApiError && e.code === "llm_not_configured") {
      notify.show(t("fit.needsLlm"), "error", { label: t("fit.openSettings"), to: "/settings" });
    } else {
      notify.error(e);
    }
  }

  // --- applying results ---

  let requestSeq = 0;
  /** Per posting: sequence number of the newest request whose result was applied. */
  const applied = new Map<number, number>();
  /** Latest applied fit per posting, also for postings that are not in the feed list (drawer, application detail). */
  const known = reactive(new Map<number, FitOut | null>());
  /** undefined = never fetched in this session. */
  const fitOf = (id: number): FitOut | null | undefined => known.get(id);

  const isActive = (f: FitOut | null | undefined) => f?.status === "queued" || f?.status === "running";
  /** Is `candidate` (e.g. a freshly loaded detail) at least as new as what the store knows? */
  function isNewer(candidate: FitOut | null, current: FitOut | null | undefined): boolean {
    if (current === undefined) return true;
    if (candidate === null) return false;
    if (current === null) return true;
    if (candidate.evaluated_at && current.evaluated_at && candidate.evaluated_at !== current.evaluated_at) {
      return candidate.evaluated_at > current.evaluated_at;
    }
    return isActive(candidate) && !isActive(current);
  }
  /** Offer a fit from another source (props); it only replaces a known fit when it is newer. */
  function offer(id: number, fit: FitOut | null) {
    if (isNewer(fit, known.get(id))) known.set(id, fit);
  }

  /** Postings shown in a detail view (reference counted); the poll covers them even without a feed. */
  const tracked = reactive(new Map<number, number>());
  function track(id: number, fit: FitOut | null) {
    offer(id, fit);
    tracked.set(id, (tracked.get(id) ?? 0) + 1);
  }
  function untrack(id: number) {
    const n = (tracked.get(id) ?? 0) - 1;
    if (n > 0) tracked.set(id, n);
    else tracked.delete(id);
  }

  /** Fetch the current fit of the given postings and patch the loaded feed items in place. */
  async function refresh(ids: number[]) {
    const seq = ++requestSeq;
    let failed = false;
    for (let i = 0; i < ids.length; i += MAX_IDS) {
      const rows = await api.get<FitItemOut[]>("/fit", { ids: ids.slice(i, i + MAX_IDS).join(",") });
      for (const row of rows) {
        // A result of an older request must not overwrite a newer one.
        if ((applied.get(row.posting_id) ?? 0) > seq) continue;
        applied.set(row.posting_id, seq);
        const was = known.get(row.posting_id) ?? feed.items.find((p) => p.id === row.posting_id)?.fit;
        if (isActive(was) && row.fit?.status === "error") failed = true;
        known.set(row.posting_id, row.fit);
        const item = feed.items.find((p) => p.id === row.posting_id);
        if (item) item.fit = row.fit;
      }
    }
    // A failed evaluation makes the posting a bulk candidate again (a successful one does not change the count).
    if (failed) refreshCount();
  }

  // --- bulk count ---

  let countSeq = 0;
  let countTimer: ReturnType<typeof setTimeout> | undefined;

  /** Count what a bulk run would evaluate; null (with the error shown unless quiet) when it fails. */
  async function bulkCount(opts: { quiet?: boolean } = {}): Promise<number | null> {
    const mine = ++countSeq;
    try {
      const res = await api.get<CountOut>("/fit/bulk/count", feed.filterQuery());
      if (typeof res?.count !== "number") throw new Error("Invalid response");
      if (mine === countSeq) bulkTotal.value = res.count;
      return res.count;
    } catch (e) {
      if (mine === countSeq) bulkTotal.value = null;
      if (!opts.quiet) showError(e);
      return null;
    }
  }

  function scheduleCount() {
    clearTimeout(countTimer);
    countSeq++; // an answer for the old filter is obsolete
    bulkTotal.value = null;
    countTimer = setTimeout(() => void bulkCount({ quiet: true }), COUNT_DEBOUNCE_MS);
  }

  /** Debounced quiet recount that keeps the shown number until the answer arrives (no flicker). */
  function refreshCount() {
    if (!attached.value) return;
    clearTimeout(countTimer);
    countTimer = setTimeout(() => void bulkCount({ quiet: true }), COUNT_DEBOUNCE_MS);
  }

  // --- actions ---

  async function evaluate(postingId: number): Promise<boolean> {
    resumePolling();
    try {
      const res = await api.post<EnqueueOut>(`/fit/${postingId}?${toQuery({ lang: lang() })}`);
      if (res?.limit_exceeded) notify.show(t("fit.limitWarning"), "warning");
      await refresh([postingId]);
      refreshCount();
      void loadStatus({ quiet: true });
      return true;
    } catch (e) {
      showError(e);
      return false;
    }
  }

  async function bulkEvaluate(): Promise<boolean> {
    resumePolling();
    try {
      const res = await api.post<EnqueueOut>(`/fit/bulk?${toQuery({ ...feed.filterQuery(), lang: lang() })}`);
      notify.show(t("fit.bulk.queued", { n: res.queued }, res.queued), "success");
      await refresh(feed.items.map((p) => p.id));
      void bulkCount({ quiet: true });
      void loadStatus({ quiet: true });
      return true;
    } catch (e) {
      showError(e);
      return false;
    }
  }

  /** Cancel every queued/running evaluation; affected postings return to their previous state. */
  async function cancel(): Promise<boolean> {
    resumePolling();
    const ids = activeIds.value; // what the user sees as active, read before the request
    try {
      await api.post<CancelOut>("/fit/cancel");
      if (ids.length) await refresh(ids);
      void loadStatus({ quiet: true });
      refreshCount();
      notify.show(t("fit.cancel.done"), "success");
      return true;
    } catch (e) {
      showError(e);
      return false;
    }
  }

  // --- polling ---

  /** Ids the poll asks for, each once: active feed items (while the feed is attached) and active tracked postings. */
  const activeIds = computed(() => {
    const ids = new Set<number>();
    if (attached.value) for (const p of feed.items) if (isActive(p.fit)) ids.add(p.id);
    for (const id of tracked.keys()) if (isActive(known.get(id))) ids.add(id);
    return [...ids];
  });
  const attached = ref(false);
  /** True after too many failed polls; a manual action resumes. */
  const suspended = ref(false);
  let failures = 0;
  let timer: ReturnType<typeof setInterval> | undefined;
  let inFlight = false;

  async function tick() {
    const ids = activeIds.value;
    if (!ids.length) {
      // Nothing visible is active, but the server still reports jobs (other pages, cancelled jobs finishing).
      await loadStatus({ quiet: true });
      return sync();
    }
    if (inFlight) return;
    inFlight = true;
    try {
      await refresh(ids);
      failures = 0;
      void loadStatus({ quiet: true }); // keeps `status.active` (cancel button) fresh
    } catch (e) {
      failures++;
      if (failures === 1) notify.error(e); // one report per failure streak
      if (failures >= MAX_POLL_FAILURES) {
        suspended.value = true;
        sync();
      }
    } finally {
      inFlight = false;
    }
  }

  /** Exactly one interval runs while not suspended and a visible item is queued/running or (feed attached) the server reports active jobs. */
  function sync() {
    const want = !suspended.value && (activeIds.value.length > 0 || (attached.value && status.value.active > 0));
    if (want && timer === undefined) timer = setInterval(() => void tick(), FIT_POLL_MS);
    else if (!want && timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
  }

  /** After a user action or a feed load, polling may run again. */
  function resumePolling() {
    failures = 0;
    suspended.value = false;
    sync();
  }

  watch(() => activeIds.value.length > 0, sync);
  watch(() => status.value.active > 0, sync);
  watch(() => feed.pageCount, resumePolling);
  watch(
    () => feed.resetCount,
    () => {
      resumePolling();
      if (attached.value) scheduleCount();
    },
  );

  /** Start watching the feed (call on mount of the view). */
  function startPolling() {
    attached.value = true;
    resumePolling();
  }
  /** Stop and clear all timers (call on unmount). */
  function stopPolling() {
    attached.value = false;
    clearTimeout(countTimer);
    sync();
  }

  /** Forget cached results after data was deleted (danger zone). */
  function clear() {
    known.clear();
    applied.clear();
    for (const p of feed.items) p.fit = null;
    statusLoaded.value = false; // profile/config state may have changed
    clearTimeout(countTimer);
    countSeq++; // a count in flight is obsolete
    bulkTotal.value = null;
  }

  return { suspended, resume: resumePolling, track, untrack, offer, clear, status, statusLoaded, ready, bulkTotal, fitOf, loadStatus, evaluate, bulkCount, bulkEvaluate, cancel, refresh, startPolling, stopPolling };
});
