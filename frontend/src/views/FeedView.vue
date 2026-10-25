<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import FeedFilters from "@/components/FeedFilters.vue";
import FitDot from "@/components/FitDot.vue";
import FitHint from "@/components/FitHint.vue";
import PostingDrawer from "@/components/PostingDrawer.vue";
import RefreshButton from "@/components/RefreshButton.vue";
import { relativeTime } from "@/domain/time";
import { useFeedStore } from "@/stores/feed";
import { useFitStore } from "@/stores/fit";
import { useNotifyStore } from "@/stores/notify";

const { t, locale } = useI18n();
const feed = useFeedStore();
const fit = useFitStore();
const notify = useNotifyStore();
const drawerId = ref<number | null>(null);
const list = ref<HTMLElement | null>(null);

const TRIAGE_COLOR = { new: "primary", saved: "success", dismissed: "grey" } as const;

async function onLoad({ done }: { done: (status: "ok" | "empty" | "error") => void }) {
  await feed.loadMore();
  done(feed.loadError ? "error" : feed.hasMore ? "ok" : "empty");
}

const bulkOpen = ref(false);
const bulkN = ref(0);
const bulkBusy = ref(false);
const cancelBusy = ref(false);

async function cancelFit() {
  cancelBusy.value = true;
  await fit.cancel();
  cancelBusy.value = false;
}

async function askBulk() {
  bulkBusy.value = true;
  const n = await fit.bulkCount();
  bulkBusy.value = false;
  if (n === null) return; // the error is already shown
  if (n === 0) {
    notify.show(t("fit.bulk.none"), "success");
    return;
  }
  bulkN.value = n;
  bulkOpen.value = true;
}

async function confirmBulk() {
  bulkBusy.value = true;
  await fit.bulkEvaluate();
  bulkBusy.value = false;
  bulkOpen.value = false;
}

/** True when the key press belongs to a form control or an editable element. */
function isEditable(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && !!target.closest("input, textarea, select, [contenteditable]:not([contenteditable='false'])");
}

function onKey(e: KeyboardEvent) {
  if (e.ctrlKey || e.metaKey || e.altKey || isEditable(e.target)) return;
  const current = feed.items[feed.selectedIndex];
  switch (e.key) {
    case "j":
      feed.selectNext();
      break;
    case "k":
      feed.selectPrev();
      break;
    case "m":
      if (current) void feed.toggleSave(current);
      break;
    case "v":
      if (current) void feed.toggleDismiss(current);
      break;
    case "Enter":
      // Enter on a focused button/link activates it natively.
      if (current && !(e.target instanceof HTMLElement && e.target.closest("button, a"))) drawerId.value = current.id;
      break;
    default:
      return;
  }
}

watch(
  () => feed.selectedIndex,
  async (i) => {
    await nextTick();
    list.value?.querySelector<HTMLElement>(`[data-index="${i}"]`)?.scrollIntoView?.({ block: "nearest" });
  },
);

onMounted(() => {
  window.addEventListener("keydown", onKey);
  void feed.reset();
  void fit.loadStatus();
  fit.startPolling();
});
onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
  fit.stopPolling();
});
</script>

<template>
  <div>
    <div class="d-flex align-center flex-wrap ga-2 mb-2">
      <h1 class="text-h5 flex-grow-1">{{ t("feed.title") }}</h1>
      <span class="text-body-2 text-medium-emphasis mr-2" data-test="feed-total">{{ t("feed.total", { n: feed.total }, feed.total) }}</span>
      <v-btn
        variant="tonal"
        prepend-icon="mdi-star-circle-outline"
        :disabled="!fit.ready"
        :loading="bulkBusy"
        data-test="fit-bulk"
        @click="askBulk"
      >
        {{ fit.bulkTotal === null ? t("fit.bulk.buttonUnknown") : t("fit.bulk.button", { n: fit.bulkTotal }) }}
      </v-btn>
      <v-btn
        v-if="fit.status.active > 0"
        variant="tonal"
        color="warning"
        prepend-icon="mdi-stop-circle-outline"
        :loading="cancelBusy"
        data-test="fit-cancel"
        @click="cancelFit"
      >
        {{ t("fit.cancel.button", { n: fit.status.active }) }}
      </v-btn>
      <RefreshButton />
    </div>
    <FitHint class="text-body-2 text-medium-emphasis mb-2" data-test="fit-hint" />
    <FeedFilters class="mb-2" />
    <div ref="list">
      <v-infinite-scroll :key="feed.resetCount" :items="feed.items" height="calc(100vh - 280px)" @load="onLoad">
        <template v-if="!feed.items.length && !feed.loading" #empty>
          <div class="pa-6 text-medium-emphasis" data-test="feed-empty">{{ t("feed.empty") }}</div>
        </template>
        <v-list lines="two" class="pa-0 bg-transparent">
          <v-list-item
            v-for="(item, i) in feed.items"
            :key="item.id"
            :data-index="i"
            :class="['feed-item', `feed-item--${item.triage_status}`]"
            :active="i === feed.selectedIndex"
            data-test="feed-row"
            @click="feed.selectedIndex = i; drawerId = item.id"
          >
            <template #prepend>
              <FitDot :fit="item.fit" class="mr-3" />
            </template>
            <v-list-item-title>{{ item.title }}</v-list-item-title>
            <v-list-item-subtitle>
              {{ [item.company, item.location].filter(Boolean).join(" · ") }}
              · {{ t("feed.foundAgo", { when: relativeTime(item.first_seen_at, locale) }) }}
            </v-list-item-subtitle>
            <template #append>
              <!-- phones: no room for the chips; status shows as the row's accent edge -->
              <v-chip size="x-small" label class="mr-2 d-none d-sm-inline-flex">{{ item.source }}</v-chip>
              <v-chip size="x-small" label class="mr-2 d-none d-sm-inline-flex" :color="TRIAGE_COLOR[item.triage_status]">
                {{ t(`triage.${item.triage_status}`) }}
              </v-chip>
              <v-btn
                icon
                size="small"
                variant="text"
                :title="item.triage_status === 'saved' ? t('feed.actions.unsave') : t('feed.actions.save')"
                :aria-label="item.triage_status === 'saved' ? t('feed.actions.unsave') : t('feed.actions.save')"
                data-test="row-save"
                @click.stop="feed.toggleSave(item)"
              >
                <v-icon>{{ item.triage_status === "saved" ? "mdi-bookmark-off" : "mdi-bookmark-outline" }}</v-icon>
              </v-btn>
              <v-btn
                icon
                size="small"
                variant="text"
                :title="item.triage_status === 'dismissed' ? t('feed.actions.undismiss') : t('feed.actions.dismiss')"
                :aria-label="item.triage_status === 'dismissed' ? t('feed.actions.undismiss') : t('feed.actions.dismiss')"
                data-test="row-dismiss"
                v-if="item.triage_status === 'dismissed' || feed.canDismiss(item)"
                @click.stop="feed.toggleDismiss(item)"
              >
                <v-icon>{{ item.triage_status === "dismissed" ? "mdi-restore" : "mdi-close-circle-outline" }}</v-icon>
              </v-btn>
            </template>
          </v-list-item>
        </v-list>
      </v-infinite-scroll>
    </div>
    <ConfirmDialog
      v-model="bulkOpen"
      :title="t('fit.bulk.title', { n: bulkN })"
      :text="t('fit.bulk.text')"
      :ok-label="t('fit.bulk.confirm')"
      :busy="bulkBusy"
      @confirm="confirmBulk"
    />
    <PostingDrawer :posting-id="drawerId" @close="drawerId = null" />
  </div>
</template>
