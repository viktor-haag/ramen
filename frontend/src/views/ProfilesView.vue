<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { PluginOut, ProfileIn, ProfileOut, RunStatus } from "@/api/types";
import { api } from "@/api/client";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import ProfileDialog from "@/components/ProfileDialog.vue";
import { formatDateTime, relativeTime } from "@/domain/time";
import { useNotifyStore } from "@/stores/notify";
import { useProfilesStore } from "@/stores/profiles";

const { t, locale } = useI18n();
const store = useProfilesStore();
const plugins = ref<PluginOut[]>([]);
const pluginsLoaded = ref(false);
const dialog = ref(false);
const editing = ref<ProfileOut | null>(null);
const saving = ref(false);
const toDelete = ref<ProfileOut | null>(null);
const expanded = ref<number[]>([]);

const STATUS_COLOR: Record<RunStatus, string> = { running: "info", ok: "success", error: "error", timeout: "warning" };

onMounted(async () => {
  await Promise.all([
    store.load(),
    api.get<PluginOut[]>("/plugins").then((p) => { plugins.value = p; pluginsLoaded.value = true; }, (e) => useNotifyStore().error(e)),
  ]);
});
onUnmounted(() => store.stop());

function openNew() {
  editing.value = null;
  dialog.value = true;
}
function openEdit(p: ProfileOut) {
  editing.value = p;
  dialog.value = true;
}
async function save(payload: ProfileIn) {
  saving.value = true;
  const ok = await store.save(editing.value?.id ?? null, payload);
  saving.value = false;
  if (ok) dialog.value = false;
}
async function confirmDelete() {
  if (toDelete.value && (await store.remove(toDelete.value.id))) toDelete.value = null;
}
async function toggleHistory(id: number) {
  if (expanded.value.includes(id)) expanded.value = expanded.value.filter((x) => x !== id);
  else {
    expanded.value = [...expanded.value, id];
    await store.loadHistory(id);
  }
}
const lastRun = (id: number) => store.history[id]?.[0];
const scheduleText = (p: ProfileOut) => (p.schedule_hours ? t("profiles.schedule.every", { n: p.schedule_hours }) : t("profiles.schedule.off"));
</script>

<template>
  <div class="d-flex align-center mb-4">
    <h1 class="text-h5">{{ t("profiles.title") }}</h1>
    <v-spacer />
    <v-btn color="primary" prepend-icon="mdi-plus" data-test="profile-add" @click="openNew">{{ t("profiles.add") }}</v-btn>
  </div>

  <div v-if="store.items.length === 0" class="text-medium-emphasis" data-test="profiles-empty">{{ t("profiles.empty") }}</div>

  <v-card v-for="p in store.items" :key="p.id" class="mb-3" :data-test="`profile-${p.id}`">
    <v-card-title class="d-flex align-center">
      <span>{{ p.name }}</span>
      <v-spacer />
      <v-switch
        :model-value="p.enabled"
        :label="t('profiles.fields.enabled')"
        color="primary"
        density="compact"
        hide-details
        data-test="profile-enabled"
        @update:model-value="(v) => store.setEnabled(p, Boolean(v))"
      />
    </v-card-title>
    <v-card-text>
      <div class="d-flex flex-wrap ga-4">
        <span class="d-flex align-center flex-wrap ga-1" data-test="profile-keywords">
          <strong>{{ t("profiles.fields.keywords") }}:</strong>
          <v-chip v-for="k in p.keywords" :key="k" size="small">{{ k }}</v-chip>
          <template v-if="p.keywords.length === 0">–</template>
        </span>
        <span><strong>{{ t("profiles.fields.location") }}:</strong> {{ p.location || "–" }}<template v-if="p.location && p.radius_km"> (+{{ p.radius_km }} km)</template></span>
        <span><strong>{{ t("profiles.fields.schedule") }}:</strong> {{ scheduleText(p) }}</span>
        <span class="d-flex align-center ga-2">
          <strong>{{ t("profiles.lastRun") }}:</strong>
          <template v-if="p.last_run_at">{{ relativeTime(p.last_run_at, locale) }}</template>
          <template v-else>{{ t("profiles.never") }}</template>
          <v-chip v-if="lastRun(p.id)" size="small" :color="STATUS_COLOR[lastRun(p.id)!.status]" data-test="last-run-chip">
            {{ t(`profiles.runStatus.${lastRun(p.id)!.status}`) }}
          </v-chip>
        </span>
      </div>
      <v-alert v-if="store.results[p.id]" class="mt-3" density="compact" :type="store.results[p.id].failed > 0 ? 'warning' : 'success'" data-test="run-result">
        <template v-if="store.results[p.id].alreadyRunning">{{ t("profiles.alreadyRunning") }}</template>
        <template v-else>
          {{ t("feed.refresh.newHits", { n: store.results[p.id].newCount }, store.results[p.id].newCount) }}
          <template v-if="store.results[p.id].failed > 0"> – {{ t("feed.refresh.failed", { n: store.results[p.id].failed }, store.results[p.id].failed) }}</template>
        </template>
      </v-alert>
    </v-card-text>
    <v-card-actions class="flex-wrap ga-1">
      <v-btn
        prepend-icon="mdi-play"
        :loading="store.running[p.id]"
        :disabled="store.running[p.id]"
        data-test="profile-run"
        @click="store.runNow(p.id)"
      >{{ store.running[p.id] ? t("profiles.running") : t("profiles.runNow") }}</v-btn>
      <v-btn prepend-icon="mdi-pencil" data-test="profile-edit" @click="openEdit(p)">{{ t("common.edit") }}</v-btn>
      <v-btn prepend-icon="mdi-delete" color="error" data-test="profile-delete" @click="toDelete = p">{{ t("common.delete") }}</v-btn>
      <v-spacer />
      <v-btn :append-icon="expanded.includes(p.id) ? 'mdi-chevron-up' : 'mdi-chevron-down'" data-test="profile-history" @click="toggleHistory(p.id)">
        {{ t("profiles.history") }}
      </v-btn>
    </v-card-actions>
    <v-card-text v-if="expanded.includes(p.id)" data-test="history">
      <div v-if="!store.history[p.id]?.length" class="text-medium-emphasis">{{ t("profiles.noHistory") }}</div>
      <div v-for="r in store.history[p.id]" :key="r.id" class="mb-2">
        <div class="d-flex align-center ga-2">
          <v-chip size="small" :color="STATUS_COLOR[r.status]">{{ t(`profiles.runStatus.${r.status}`) }}</v-chip>
          <strong>{{ r.plugin }}</strong>
          <span>{{ formatDateTime(r.started_at, locale) }}</span>
          <span class="text-medium-emphasis">{{ t("profiles.runCounts", { new: r.new_count, total: r.total_count, invalid: r.invalid_count }) }}</span>
        </div>
        <div v-if="r.error" class="text-error text-caption" data-test="run-error">{{ r.error }}</div>
      </div>
    </v-card-text>
  </v-card>

  <ProfileDialog v-model="dialog" :profile="editing" :plugins="plugins" :busy="saving" :plugins-loaded="pluginsLoaded" @save="save" />
  <ConfirmDialog
    :model-value="toDelete !== null"
    :title="t('profiles.deleteTitle')"
    :text="t('profiles.deleteText', { name: toDelete?.name ?? '' })"
    @update:model-value="(v: boolean) => !v && (toDelete = null)"
    @confirm="confirmDelete"
  />
</template>
