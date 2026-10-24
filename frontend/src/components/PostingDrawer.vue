<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "@/api/client";
import FitSection from "@/components/FitSection.vue";
import type { PostingDetail } from "@/api/types";
import { formatDate } from "@/domain/time";
import { useFeedStore } from "@/stores/feed";
import { useNotifyStore } from "@/stores/notify";

const props = defineProps<{ postingId: number | null }>();
const emit = defineEmits<{ close: [] }>();

const { t, locale } = useI18n();
const feed = useFeedStore();
const detail = ref<PostingDetail | null>(null);
const loading = ref(false);
let token = 0;

const open = computed(() => props.postingId !== null);
// Only http(s) links are rendered; the URL comes from third-party sites.
const safeUrl = computed(() => (detail.value?.url && /^https?:\/\//i.test(detail.value.url) ? detail.value.url : null));

watch(
  () => props.postingId,
  async (id) => {
    const mine = ++token;
    detail.value = null;
    if (id === null) return;
    loading.value = true;
    try {
      const d = await api.get<PostingDetail>(`/postings/${id}`);
      if (mine === token) detail.value = d;
    } catch (e) {
      if (mine === token) {
        useNotifyStore().error(e);
        emit("close");
      }
    } finally {
      if (mine === token) loading.value = false;
    }
  },
  { immediate: true },
);

async function run(action: (id: number) => Promise<unknown>, to: "saved" | "dismissed" | "new") {
  if (!detail.value) return;
  const status = await action(detail.value.id);
  if (status && detail.value) detail.value.triage_status = to;
}
</script>

<template>
  <v-navigation-drawer
    :model-value="open"
    location="right"
    temporary
    width="520"
    data-test="posting-drawer"
    @update:model-value="(v: boolean) => !v && emit('close')"
  >
    <v-progress-linear v-if="loading" indeterminate />
    <div v-if="detail" class="pa-4">
      <div class="d-flex align-start">
        <h2 class="text-h6 flex-grow-1">{{ detail.title }}</h2>
        <v-btn icon="mdi-close" variant="text" size="small" :aria-label="t('common.close')" @click="emit('close')" />
      </div>
      <div class="text-subtitle-1">{{ detail.company }}</div>
      <div class="text-body-2 text-medium-emphasis">{{ detail.location }}</div>
      <div class="my-2 d-flex ga-2 flex-wrap">
        <v-chip size="small" label>{{ detail.source }}</v-chip>
        <v-chip size="small" label>{{ t(`triage.${detail.triage_status}`) }}</v-chip>
      </div>
      <div class="text-caption text-medium-emphasis">
        {{ t("feed.drawer.found", { date: formatDate(detail.first_seen_at, locale) }) }}
        <template v-if="detail.published_at">
          · {{ t("feed.drawer.published", { date: formatDate(detail.published_at, locale) }) }}
        </template>
      </div>
      <div class="my-3 d-flex ga-2 flex-wrap">
        <v-btn
          size="small"
          variant="tonal"
          :prepend-icon="detail.triage_status === 'saved' ? 'mdi-bookmark-off' : 'mdi-bookmark'"
          data-test="drawer-save"
          @click="detail.triage_status === 'saved' ? run(feed.unsave, 'new') : run(feed.save, 'saved')"
        >
          {{ detail.triage_status === "saved" ? t("feed.actions.unsave") : t("feed.actions.save") }}
        </v-btn>
        <v-btn
          size="small"
          variant="tonal"
          :prepend-icon="detail.triage_status === 'dismissed' ? 'mdi-restore' : 'mdi-close-circle'"
          data-test="drawer-dismiss"
          v-if="detail.triage_status === 'dismissed' || feed.canDismiss(detail)"
          @click="detail.triage_status === 'dismissed' ? run(feed.undismiss, 'new') : run(feed.dismiss, 'dismissed')"
        >
          {{ detail.triage_status === "dismissed" ? t("feed.actions.undismiss") : t("feed.actions.dismiss") }}
        </v-btn>
        <v-btn
          v-if="safeUrl"
          size="small"
          variant="text"
          prepend-icon="mdi-open-in-new"
          :href="safeUrl"
          target="_blank"
          rel="noopener noreferrer"
        >
          {{ t("feed.drawer.openSource") }}
        </v-btn>
      </div>
      <v-divider class="mb-3" />
      <FitSection :key="detail.id" :posting-id="detail.id" :fit="detail.fit" class="mb-3" />
      <div v-if="detail.description" class="description" data-test="drawer-description">{{ detail.description }}</div>
      <div v-else class="text-medium-emphasis">{{ t("feed.drawer.noDescription") }}</div>
    </div>
  </v-navigation-drawer>
</template>

<style scoped>
.description {
  white-space: pre-line;
  overflow-wrap: anywhere;
}
</style>
