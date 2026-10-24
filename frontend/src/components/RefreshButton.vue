<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRunsStore } from "@/stores/runs";

const { t } = useI18n();
const runs = useRunsStore();
const visible = ref(false);

const result = computed(() => runs.lastResult);
const text = computed(() => {
  const r = result.value;
  if (!r) return "";
  if (r.alreadyRunning) return t("feed.refresh.alreadyRunning");
  return t("feed.refresh.newHits", { n: r.newCount }, r.newCount);
});

async function refresh() {
  runs.lastResult = null;
  await runs.refreshAll();
  visible.value = runs.lastResult !== null;
}

onUnmounted(() => runs.stop());
</script>

<template>
  <v-btn
    variant="tonal"
    prepend-icon="mdi-refresh"
    :loading="runs.isRunning"
    :disabled="runs.isRunning"
    data-test="refresh"
    @click="refresh"
  >
    {{ runs.isRunning ? t("feed.refresh.running") : t("feed.refresh.button") }}
  </v-btn>
  <v-snackbar v-model="visible" :timeout="8000" multi-line>
    <div data-test="refresh-result">{{ text }}</div>
    <div v-if="result && result.failed > 0">
      {{ t("feed.refresh.failed", { n: result.failed }, result.failed) }}
      <router-link to="/profiles" class="refresh-link">{{ t("feed.refresh.toProfiles") }}</router-link>
    </div>
    <template #actions>
      <v-btn variant="text" @click="visible = false">{{ t("common.close") }}</v-btn>
    </template>
  </v-snackbar>
</template>

<style scoped>
.refresh-link {
  color: inherit;
  text-decoration: underline;
}
</style>
