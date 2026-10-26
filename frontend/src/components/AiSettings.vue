<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { DailyLimitKind, LlmConfigOut, UsageTotals } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import LlmConfigDialog from "@/components/LlmConfigDialog.vue";
import PromptsCard from "@/components/PromptsCard.vue";
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
const purposeKeys = ["profile", "fit", "extraction", "cover_letter"] as const;
const purposeDraft = reactive<Record<(typeof purposeKeys)[number], number | null>>({ profile: null, fit: null, extraction: null, cover_letter: null });
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
const tokensText = (u: UsageTotals) => t("ai.usage.tokens", { input: num(u.input_tokens), output: num(u.output_tokens) });
const eurText = (u: UsageTotals, deleted = false) => (u.eur === null ? t(deleted ? "ai.usage.costUnknown" : "ai.usage.noPrices") : eur(u.eur));
interface LimitView { used: string; limit: string; percent: number; exceeded: boolean }
/** Progress of today's usage against a limit; null when there is no limit. */
function limitView(today: UsageTotals, limit: { kind: DailyLimitKind; value: number | null }, exceeded: boolean): LimitView | null {
  if (limit.kind === "none" || limit.value === null) return null;
  const tokens = limit.kind === "tokens";
  const used = tokens ? today.input_tokens + today.output_tokens : (today.eur ?? 0);
  const fmt = (n: number) => (tokens ? num(n) : eur(n));
  return { used: fmt(used), limit: fmt(limit.value), percent: limit.value > 0 ? Math.min(100, (used / limit.value) * 100) : 100, exceeded };
}
const usageRows = computed(() => {
  const u = store.usage;
  if (!u) return [];
  return (u.per_config ?? []).map((c) => ({
    key: c.config_id === null ? "deleted" : String(c.config_id),
    name: c.deleted ? t("ai.usage.deleted") : (c.name ?? ""),
    deleted: c.deleted,
    today: c.today,
    month: c.month,
    limit: limitView(c.today, c.limit, c.limit_exceeded),
  }));
});
/** True when the euro total leaves out tokens of configurations that have no price. */
const totalExcludesUnpriced = computed(() =>
  (store.usage?.per_config ?? []).some((c) => [c.today, c.month].some((x) => x.input_tokens + x.output_tokens > 0 && x.eur === null)),
);
const totalRow = computed(() => {
  const u = store.usage;
  return u ? { today: u.today, month: u.month, limit: limitView(u.today, u.limit, u.limit_exceeded) } : null;
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

  <PromptsCard />

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
      <div class="overflow-x-auto">
        <v-table density="compact" data-test="llm-usage-table">
          <thead>
            <tr>
              <th class="text-left">{{ t("ai.usage.config") }}</th>
              <th class="text-left">{{ t("ai.usage.today") }}</th>
              <th class="text-left">{{ t("ai.usage.month") }}</th>
              <th class="text-left">{{ t("ai.usage.limit") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in usageRows" :key="r.key" :data-test="`llm-usage-row-${r.key}`">
              <th class="text-left">{{ r.name }}</th>
              <td class="text-no-wrap">{{ tokensText(r.today) }}<br />{{ eurText(r.today, r.deleted) }}</td>
              <td class="text-no-wrap">{{ tokensText(r.month) }}<br />{{ eurText(r.month, r.deleted) }}</td>
              <td class="usage-limit">
                <template v-if="r.limit">
                  <v-progress-linear :model-value="r.limit.percent" :color="r.limit.exceeded ? 'error' : 'primary'" :class="{ 'text-error': r.limit.exceeded }" height="6" rounded />
                  <span class="text-caption text-no-wrap">{{ r.limit.used }} / {{ r.limit.limit }}</span>
                </template>
                <template v-else>–</template>
              </td>
            </tr>
          </tbody>
          <tfoot v-if="totalRow">
            <tr data-test="llm-usage-total" class="font-weight-bold">
              <th class="text-left">
                {{ t("ai.usage.total") }}
                <div v-if="totalExcludesUnpriced" class="text-caption font-weight-regular text-medium-emphasis" data-test="llm-usage-total-note">{{ t("ai.usage.totalExcludesUnpriced") }}</div>
              </th>
              <td class="text-no-wrap">{{ tokensText(totalRow.today) }}<br />{{ eurText(totalRow.today) }}</td>
              <td class="text-no-wrap">{{ tokensText(totalRow.month) }}<br />{{ eurText(totalRow.month) }}</td>
              <td class="usage-limit">
                <template v-if="totalRow.limit">
                  <v-progress-linear :model-value="totalRow.limit.percent" :color="totalRow.limit.exceeded ? 'error' : 'primary'" :class="{ 'text-error': totalRow.limit.exceeded }" height="6" rounded />
                  <span class="text-caption text-no-wrap">{{ totalRow.limit.used }} / {{ totalRow.limit.limit }}</span>
                </template>
                <template v-else>–</template>
              </td>
            </tr>
          </tfoot>
        </v-table>
      </div>
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

<style scoped>
.usage-limit {
  min-width: 140px;
}
</style>
