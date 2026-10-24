<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "@/api/client";
import { router } from "@/router";
import { useApplicationDetailStore } from "@/stores/applicationDetail";
import { useApplicationsStore } from "@/stores/applications";
import { useDashboardStore } from "@/stores/dashboard";
import { useFeedStore } from "@/stores/feed";
import { useFitStore } from "@/stores/fit";
import { useLlmStore } from "@/stores/llm";
import { useMeStore } from "@/stores/me";
import { useNotifyStore } from "@/stores/notify";
import { useSettingsPluginsStore } from "@/stores/plugins";
import { useProfilesStore } from "@/stores/profiles";
import { useRunsStore } from "@/stores/runs";
import TypeToConfirmDialog from "./TypeToConfirmDialog.vue";

type Action = "clearFeed" | "deleteProfile" | "reset";

const { t } = useI18n();
const notify = useNotifyStore();
const pending = ref<Action | null>(null);
const open = ref(false);
const busy = ref(false);

function ask(action: Action) {
  pending.value = action;
  open.value = true;
}

async function clearFeed() {
  const res = await api.post<{ deleted_postings: number; deleted_runs: number }>("/admin/clear-feed");
  // The server action succeeded: report that, whatever the follow-up reload does.
  useProfilesStore().clearRunData();
  useRunsStore().clear();
  notify.show(t("settings.danger.clearFeedDone", { postings: res.deleted_postings, runs: res.deleted_runs }), "success");
  // The stores report their own load errors through the notify store.
  await Promise.allSettled([useFeedStore().reset(), useDashboardStore().load()]);
}

async function deleteProfile() {
  const res = await api.post<{ deleted_documents: number; deleted_fits?: number }>("/admin/delete-profile");
  useMeStore().clear();
  useApplicationDetailStore().clear(); // a cached application would re-seed its old fit
  useFitStore().clear(); // the fit evaluations are gone as well
  notify.show(t("settings.danger.deleteProfileDone", { documents: res.deleted_documents, fits: res.deleted_fits ?? 0 }), "success");
}

async function resetAll() {
  const res = await api.post<{ deleted: Record<string, number> }>("/admin/reset");
  const total = Object.values(res.deleted).reduce((a, b) => a + b, 0);
  const feed = useFeedStore();
  feed.resetFilter();
  feed.clear();
  useApplicationsStore().clear();
  useApplicationDetailStore().clear();
  useProfilesStore().clear();
  useRunsStore().clear();
  useDashboardStore().clear();
  useMeStore().clear();
  useFitStore().clear();
  useLlmStore().clear();
  await useSettingsPluginsStore().load();
  notify.show(t("settings.danger.resetDone", { total }), "success");
  await router.push("/");
}

async function confirm() {
  const action = pending.value;
  if (!action || busy.value) return;
  busy.value = true;
  try {
    await (action === "clearFeed" ? clearFeed() : action === "deleteProfile" ? deleteProfile() : resetAll());
  } catch (e) {
    notify.error(e);
  } finally {
    busy.value = false;
    open.value = false;
  }
}
</script>

<template>
  <h2 class="text-h6 mb-2 text-error">{{ t("settings.danger.title") }}</h2>
  <v-card class="mb-6 border-error" variant="outlined" data-test="danger-zone">
    <v-list lines="two">
      <v-list-item :title="t('settings.danger.clearFeed')" :subtitle="t('settings.danger.clearFeedHint')">
        <template #append>
          <v-btn color="error" variant="outlined" data-test="danger-clear-feed" @click="ask('clearFeed')">{{ t("settings.danger.clearFeed") }}</v-btn>
        </template>
      </v-list-item>
      <v-list-item :title="t('settings.danger.deleteProfile')" :subtitle="t('settings.danger.deleteProfileHint')">
        <template #append>
          <v-btn color="error" variant="outlined" data-test="danger-delete-profile" @click="ask('deleteProfile')">{{ t("settings.danger.deleteProfile") }}</v-btn>
        </template>
      </v-list-item>
      <v-list-item :title="t('settings.danger.reset')" :subtitle="t('settings.danger.resetHint')">
        <template #append>
          <v-btn color="error" variant="flat" data-test="danger-reset" @click="ask('reset')">{{ t("settings.danger.reset") }}</v-btn>
        </template>
      </v-list-item>
    </v-list>
  </v-card>

  <TypeToConfirmDialog
    v-model="open"
    :title="pending ? t(`settings.danger.${pending}`) : ''"
    :text="pending ? t(`settings.danger.${pending}Confirm`) : ''"
    :busy="busy"
    @confirm="confirm"
  />
</template>
