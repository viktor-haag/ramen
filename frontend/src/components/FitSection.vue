<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { FitOut } from "@/api/types";
import FitDot from "@/components/FitDot.vue";
import FitHint from "@/components/FitHint.vue";
import { fitErrorText } from "@/domain/fitError";
import { formatDateTime } from "@/domain/time";
import { useFitStore } from "@/stores/fit";
import { useNotifyStore } from "@/stores/notify";

const props = defineProps<{ postingId: number; fit: FitOut | null }>();

const { t, te, locale } = useI18n();
const store = useFitStore();
const notify = useNotifyStore();

// The store owns results and polling; this section shows what it knows (falling back to the loaded detail).
store.track(props.postingId, props.fit);
onBeforeUnmount(() => store.untrack(props.postingId));
// A reloaded detail only replaces the store's result when it is newer.
watch(() => props.fit, (f) => store.offer(props.postingId, f));
if (!store.statusLoaded) void store.loadStatus();

const current = computed<FitOut | null>(() => store.fitOf(props.postingId) ?? props.fit);
const pending = computed(() => current.value?.status === "queued" || current.value?.status === "running");
const hasRating = computed(() => current.value?.rating != null);
const errorText = computed(() => (current.value?.status === "error" ? fitErrorText(t as never, te, current.value.error) : null));
/** Polling gave up while the result is still pending: offer a manual way out. */
const stalled = computed(() => pending.value && store.suspended);

const busy = ref(false);
const notReady = computed(() => store.statusLoaded && !store.ready);
const disabled = computed(() => (pending.value && !stalled.value) || busy.value || notReady.value);

async function evaluate() {
  busy.value = true;
  try {
    await store.evaluate(props.postingId); // also resumes polling
  } finally {
    busy.value = false;
  }
}

async function refreshNow() {
  store.resume();
  try {
    await store.refresh([props.postingId]);
  } catch (e) {
    notify.error(e);
  }
}
</script>

<template>
  <section class="fit-section" data-test="fit-section">
    <div class="d-flex align-center ga-2">
      <h3 class="text-subtitle-1 flex-grow-1">{{ t("fit.section") }}</h3>
      <v-btn v-if="stalled" size="small" variant="text" prepend-icon="mdi-refresh" data-test="fit-refresh" @click="refreshNow">{{ t("fit.refresh") }}</v-btn>
      <v-btn
        size="small"
        variant="tonal"
        :prepend-icon="current ? 'mdi-refresh' : 'mdi-auto-fix'"
        :disabled="disabled"
        :loading="busy"
        data-test="fit-evaluate"
        @click="evaluate"
      >
        {{ current ? t("fit.reevaluate") : t("fit.evaluate") }}
      </v-btn>
    </div>
    <FitHint class="text-body-2 text-medium-emphasis mt-1" data-test="fit-section-hint" />
    <div class="d-flex align-center ga-2 mt-2" data-test="fit-state">
      <FitDot :fit="current" />
      <span v-if="hasRating" class="font-weight-medium" data-test="fit-rating">{{ t(`fit.rating.${current!.rating}`) }}</span>
      <span v-if="pending" class="text-medium-emphasis" data-test="fit-pending">{{ t(`fit.state.${current!.status}`) }}</span>
      <span v-else-if="!hasRating && !errorText" class="text-medium-emphasis" data-test="fit-none">{{ t("fit.state.none") }}</span>
    </div>
    <div v-if="errorText" class="text-error text-body-2 mt-1" data-test="fit-error">{{ t("fit.state.error") }}: {{ errorText }}</div>
    <template v-if="hasRating">
      <p v-if="current!.explanation" class="mt-1 explanation" data-test="fit-explanation">{{ current!.explanation }}</p>
      <div v-if="current!.evaluated_at" class="text-caption text-medium-emphasis" data-test="fit-evaluated-at">
        {{ t("fit.evaluatedAt", { date: formatDateTime(current!.evaluated_at, locale) }) }}
      </div>
      <div v-if="current!.outdated" class="text-caption text-warning" data-test="fit-outdated">{{ t("fit.outdated") }}</div>
    </template>
  </section>
</template>

<style scoped>
.explanation {
  white-space: pre-line;
  overflow-wrap: anywhere;
}
</style>
