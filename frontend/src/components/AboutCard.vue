<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { relativeTime } from "@/domain/time";
import { useLlmStore } from "@/stores/llm";
import { useNotifyStore } from "@/stores/notify";
import { useVersionStore } from "@/stores/version";

const { t, te, locale } = useI18n();
const store = useVersionStore();
const llm = useLlmStore();
const notify = useNotifyStore();

onMounted(() => store.load());

const info = computed(() => store.info);
const disabledByEnv = computed(() => info.value?.disabled_by_env === true);

/** The app settings arrive with the AI settings card on the same page; the switch waits for them. */
const autoOn = computed(() => llm.settings?.update_check ?? true);
const autoDisabled = computed(() => disabledByEnv.value || !llm.settings);

const errorText = computed(() => {
  const code = info.value?.error;
  if (!code) return null;
  const http = /^http_(\d+)$/.exec(code);
  if (http) return t("about.error.http", { code: http[1] });
  return te(`about.error.${code}`) ? t(`about.error.${code}`) : code;
});
const lastChecked = computed(() =>
  info.value?.checked_at ? t("about.lastChecked", { when: relativeTime(info.value.checked_at, locale.value) }) : t("about.never"),
);

const checking = ref(false);
async function checkNow() {
  checking.value = true;
  await store.checkNow();
  checking.value = false;
}

const saving = ref(false);
async function setAuto(value: boolean | null) {
  if (!llm.settings) return;
  saving.value = true;
  const res = await llm.saveSettings({ ...llm.settings, update_check: value === true }, ["update_check"]);
  saving.value = false;
  if (res.ok) {
    notify.show(t("settings.saved"), "success");
    await store.load(); // `enabled` follows the setting
  }
}
</script>

<template>
  <v-card class="mb-6" :title="t('about.title')" data-test="about-card">
    <v-card-text>
      <v-table density="compact" class="mb-2">
        <tbody>
          <tr data-test="about-installed">
            <th class="text-left">{{ t("about.installed") }}</th>
            <td>{{ info?.current ?? "" }}</td>
          </tr>
          <tr data-test="about-latest">
            <th class="text-left">{{ t("about.latest") }}</th>
            <td>
              <template v-if="info?.latest">
                <a v-if="info.release_url" :href="info.release_url" target="_blank" rel="noopener noreferrer">{{ info.latest }}</a>
                <span v-else>{{ info.latest }}</span>
                <v-chip v-if="!info.update_available" class="ml-2" size="small" label color="success" data-test="about-up-to-date">{{ t("about.upToDate") }}</v-chip>
              </template>
            </td>
          </tr>
        </tbody>
      </v-table>
      <div v-if="info?.pdf_available !== undefined" class="text-body-2 mb-2" data-test="about-pdf">
        {{ info.pdf_available ? t("about.pdf.available") : t("about.pdf.unavailable") }}
      </div>
      <div class="text-body-2 text-medium-emphasis" data-test="about-last-checked">{{ lastChecked }}</div>
      <v-alert v-if="errorText" type="warning" density="compact" class="mt-3" data-test="about-error">{{ errorText }}</v-alert>
      <v-alert v-if="disabledByEnv" type="info" density="compact" class="mt-3" data-test="about-disabled">{{ t("about.disabledByEnv") }}</v-alert>
      <v-switch
        :model-value="autoOn"
        :label="t('about.auto')"
        :disabled="autoDisabled"
        :loading="saving"
        color="primary"
        density="comfortable"
        hide-details
        class="mt-2"
        data-test="about-auto"
        @update:model-value="setAuto"
      />
    </v-card-text>
    <v-card-actions>
      <v-spacer />
      <v-btn variant="tonal" prepend-icon="mdi-refresh" :loading="checking" :disabled="disabledByEnv" data-test="about-check" @click="checkNow">{{ t("about.checkNow") }}</v-btn>
    </v-card-actions>
  </v-card>
</template>
