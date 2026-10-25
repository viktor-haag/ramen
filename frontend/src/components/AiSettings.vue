<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { DailyLimitKind, LlmConfigOut, UsageTotals } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import LlmConfigDialog from "@/components/LlmConfigDialog.vue";
import { useLlmStore, type TestResult } from "@/stores/llm";
import { useNotifyStore } from "@/stores/notify";

const { t, locale } = useI18n();
const store = useLlmStore();
const notify = useNotifyStore();

onMounted(() => store.load());

// --- configurations ---
const dialogOpen = ref(false);
const editing = ref<LlmConfigOut | null>(null);
const toDelete = ref<LlmConfigOut | null>(null);
const confirmOpen = ref(false);
const testing = ref<number | null>(null);
const results = reactive<Record<number, TestResult>>({});

function openDialog(c: LlmConfigOut | null) {
  editing.value = c;
  dialogOpen.value = true;
}
function askDelete(c: LlmConfigOut) {
  toDelete.value = c;
  confirmOpen.value = true;
}
async function confirmDelete() {
  const c = toDelete.value;
  confirmOpen.value = false;
  if (c && (await store.remove(c.id))) delete results[c.id];
}
async function runTest(c: LlmConfigOut) {
  testing.value = c.id;
  results[c.id] = await store.test(c.id);
  testing.value = null;
}
function testText(r: TestResult) {
  return r.ok ? t("ai.testOk", { model: r.model, ms: r.latencyMs }) : r.message;
}

// --- purposes ---
const purposeKeys = ["profile", "fit", "extraction"] as const;
const purposeDraft = reactive<Record<(typeof purposeKeys)[number], number | null>>({ profile: null, fit: null, extraction: null });
const purposeItems = computed(() => [
  { value: null, title: t("ai.purposes.default") },
  ...store.configs.map((c) => ({ value: c.id, title: c.name })),
]);
watch(() => store.purposes, (p) => Object.assign(purposeDraft, p), { immediate: true, deep: true });
const savingPurposes = ref(false);
async function savePurposes() {
  savingPurposes.value = true;
  const res = await store.savePurposes({ ...purposeDraft });
  savingPurposes.value = false;
  if (res.ok) notify.show(t("settings.saved"), "success");
}

// --- fit settings and daily limit ---
const settingsDraft = reactive<{ fit_auto: boolean; fit_concurrency: string; fit_language: "en" | "de"; kind: DailyLimitKind; value: string }>({
  fit_auto: false, fit_concurrency: "2", fit_language: "en", kind: "none", value: "",
});
const settingsErrors = ref<Record<string, string>>({});
watch(
  () => store.settings,
  (s) => {
    if (!s) return;
    settingsDraft.fit_auto = s.fit_auto;
    settingsDraft.fit_concurrency = String(s.fit_concurrency);
    settingsDraft.fit_language = s.fit_language;
    settingsDraft.kind = s.daily_limit_kind;
    settingsDraft.value = s.daily_limit_value === null ? "" : String(s.daily_limit_value);
  },
  { immediate: true, deep: true },
);
const kindItems = computed(() => (["none", "tokens", "eur"] as const).map((k) => ({ value: k, title: t(`ai.limit.${k}`) })));
const languageItems = computed(() => (["en", "de"] as const).map((l) => ({ value: l, title: t(`ai.fit.languages.${l}`) })));
const savingSettings = ref(false);
async function saveSettings() {
  const raw = settingsDraft.value.trim();
  const value = settingsDraft.kind === "none" || raw === "" ? null : Number(raw);
  savingSettings.value = true;
  settingsErrors.value = {};
  const visible = ["fit_concurrency", "fit_language", "daily_limit_kind"];
  if (settingsDraft.kind !== "none") visible.push("daily_limit_value");
  const res = await store.saveSettings(
    {
      fit_auto: settingsDraft.fit_auto,
      fit_concurrency: Number(settingsDraft.fit_concurrency),
      fit_language: settingsDraft.fit_language,
      daily_limit_kind: settingsDraft.kind,
      daily_limit_value: value,
      update_check: store.settings?.update_check ?? true, // owned by the About card; the PUT is a full body
    },
    visible,
  );
  savingSettings.value = false;
  if (res.ok) notify.show(t("settings.saved"), "success");
  else settingsErrors.value = res.errors;
}

// --- usage ---
const num = (n: number) => new Intl.NumberFormat(locale.value).format(n);
const eur = (n: number) => new Intl.NumberFormat(locale.value, { style: "currency", currency: "EUR" }).format(n);
const usageRows = computed(() => {
  const u = store.usage;
  if (!u) return [];
  const row = (key: string, totals: UsageTotals) => ({
    key,
    tokens: t("ai.usage.tokens", { input: num(totals.input_tokens), output: num(totals.output_tokens) }),
    eur: totals.eur === null ? t("ai.usage.noPrices") : eur(totals.eur),
  });
  return [row("today", u.today), row("month", u.month)];
});
</script>

<template>
  <h2 class="text-h6 mb-2">{{ t("ai.title") }}</h2>

  <v-card class="mb-4 ramen-stack-append" :title="t('ai.configs')" data-test="llm-configs">
    <template #append>
      <v-btn color="primary" variant="tonal" prepend-icon="mdi-plus" data-test="llm-add" @click="openDialog(null)">{{ t("ai.add") }}</v-btn>
    </template>
    <v-card-text v-if="store.loaded && store.configs.length === 0" class="text-medium-emphasis" data-test="llm-empty">{{ t("ai.empty") }}</v-card-text>
    <v-list v-else lines="two">
      <v-list-item
        v-for="c in store.configs"
        :key="c.id"
        :title="c.name"
        :subtitle="`${t(`ai.providers.${c.provider}`)} · ${c.model}`"
        :data-test="`llm-config-${c.id}`"
      >
        <template #prepend>
          <v-btn
            variant="text"
            icon
            size="small"
            :title="c.is_default ? t('ai.isDefault') : t('ai.makeDefault')"
            :disabled="c.is_default"
            data-test="llm-default"
            @click="store.setDefault(c.id)"
          >
            <v-icon :icon="c.is_default ? 'mdi-star' : 'mdi-star-outline'" :color="c.is_default ? 'warning' : undefined" data-test="llm-default-icon" />
          </v-btn>
        </template>
        <template #append>
          <span v-if="results[c.id]" class="text-body-2 mr-2" :class="results[c.id].ok ? 'text-success' : 'text-error'" data-test="llm-test-result">{{ testText(results[c.id]) }}</span>
          <v-btn variant="text" size="small" :loading="testing === c.id" data-test="llm-test" @click="runTest(c)">{{ t("ai.test") }}</v-btn>
          <v-btn variant="text" icon="mdi-pencil" size="small" :title="t('common.edit')" data-test="llm-edit" @click="openDialog(c)" />
          <v-btn variant="text" icon="mdi-delete" size="small" color="error" :title="t('common.delete')" data-test="llm-delete" @click="askDelete(c)" />
        </template>
      </v-list-item>
    </v-list>
  </v-card>

  <v-card class="mb-4" :title="t('ai.purposes.title')" :subtitle="t('ai.purposes.hint')" data-test="llm-purposes">
    <v-card-text>
      <v-select
        v-for="k in purposeKeys"
        :key="k"
        :model-value="purposeDraft[k]"
        :items="purposeItems"
        :label="t(`ai.purposes.${k}`)"
        :data-test="`llm-purpose-${k}`"
        @update:model-value="(v: number | null) => (purposeDraft[k] = v)"
      />
    </v-card-text>
    <v-card-actions>
      <v-spacer />
      <v-btn color="primary" variant="flat" :loading="savingPurposes" data-test="llm-purposes-save" @click="savePurposes">{{ t("common.save") }}</v-btn>
    </v-card-actions>
  </v-card>

  <v-card class="mb-4" :title="t('ai.fit.title')" data-test="llm-fit">
    <v-card-text>
      <v-switch v-model="settingsDraft.fit_auto" :label="t('ai.fit.auto')" color="primary" density="comfortable" hide-details data-test="llm-fit-auto" />
      <v-text-field
        v-model="settingsDraft.fit_concurrency"
        type="number"
        min="1"
        max="8"
        :label="t('ai.fit.concurrency')"
        :hint="t('ai.fit.hint')"
        persistent-hint
        :error-messages="settingsErrors.fit_concurrency"
        class="mt-2"
        data-test="llm-concurrency"
      />
      <v-select
        :model-value="settingsDraft.fit_language"
        :items="languageItems"
        :label="t('ai.fit.language')"
        :error-messages="settingsErrors.fit_language"
        data-test="llm-fit-language"
        @update:model-value="(v: 'en' | 'de') => (settingsDraft.fit_language = v)"
      />
      <h3 class="text-subtitle-1 mt-4 mb-2">{{ t("ai.limit.title") }}</h3>
      <div class="d-flex ga-2">
        <v-select
          :model-value="settingsDraft.kind"
          :items="kindItems"
          :label="t('ai.limit.kind')"
          :error-messages="settingsErrors.daily_limit_kind"
          data-test="llm-limit-kind"
          @update:model-value="(v: DailyLimitKind) => (settingsDraft.kind = v)"
        />
        <v-text-field
          v-if="settingsDraft.kind !== 'none'"
          v-model="settingsDraft.value"
          type="number"
          min="0"
          :step="settingsDraft.kind === 'tokens' ? 1 : 'any'"
          :label="t(settingsDraft.kind === 'tokens' ? 'ai.limit.tokensValue' : 'ai.limit.eurValue')"
          :hint="settingsDraft.kind === 'eur' ? t('ai.limit.eurHint') : undefined"
          :persistent-hint="settingsDraft.kind === 'eur'"
          :error-messages="settingsErrors.daily_limit_value"
          data-test="llm-limit-value"
        />
      </div>
    </v-card-text>
    <v-card-actions>
      <v-spacer />
      <v-btn color="primary" variant="flat" :loading="savingSettings" data-test="llm-settings-save" @click="saveSettings">{{ t("common.save") }}</v-btn>
    </v-card-actions>
  </v-card>

  <v-card class="mb-6" :title="t('ai.usage.title')" data-test="llm-usage">
    <v-card-text v-if="store.usage">
      <v-alert v-if="store.usage.limit_exceeded" type="warning" density="compact" class="mb-3" data-test="llm-limit-exceeded">{{ t("ai.usage.limitExceeded") }}</v-alert>
      <v-table density="compact">
        <tbody>
          <tr v-for="r in usageRows" :key="r.key" :data-test="`llm-usage-${r.key}`">
            <th class="text-left">{{ t(`ai.usage.${r.key}`) }}</th>
            <td>{{ r.tokens }}</td>
            <td>{{ r.eur }}</td>
          </tr>
        </tbody>
      </v-table>
    </v-card-text>
  </v-card>

  <LlmConfigDialog v-model="dialogOpen" :config="editing" />
  <ConfirmDialog
    v-model="confirmOpen"
    :title="t('ai.deleteTitle')"
    :text="toDelete ? t('ai.deleteConfirm', { name: toDelete.name }) : ''"
    @confirm="confirmDelete"
  />
</template>
