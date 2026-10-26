<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { PromptOut, PromptPurpose } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { useNotifyStore } from "@/stores/notify";
import { usePromptsStore } from "@/stores/prompts";

const MAX_PROMPT_CHARS = 20000;

const { t, locale } = useI18n();
const store = usePromptsStore();
const notify = useNotifyStore();

const purposes = ["fit", "profile", "extraction", "cover_letter"] as const;
const tab = ref<PromptPurpose>("fit");
// One draft per tab, so switching tabs never loses edits.
const drafts = reactive<Record<PromptPurpose, string>>({ fit: "", profile: "", extraction: "", cover_letter: "" });
const saving = ref(false);
const confirmOpen = ref(false);
const resetting = ref(false);

onMounted(() => store.load());

// Keep drafts in sync with the server text, but never overwrite a draft the user is editing.
watch(
  () => store.items,
  (list, old) => {
    for (const p of list) {
      const before = old?.find((o) => o.purpose === p.purpose);
      if (!before || drafts[p.purpose] === before.text) drafts[p.purpose] = p.text;
    }
  },
  { immediate: true, deep: true },
);

const byPurpose = (p: PromptPurpose): PromptOut | undefined => store.items.find((i) => i.purpose === p);
const current = computed(() => byPurpose(tab.value));
const dirty = computed(() => !!current.value && drafts[tab.value] !== current.value.text);
const blank = computed(() => drafts[tab.value].trim() === "");
const tooLong = computed(() => drafts[tab.value].length > MAX_PROMPT_CHARS);
const rules = [(v: string) => v.length <= MAX_PROMPT_CHARS || t("prompts.tooLong", { max: new Intl.NumberFormat(locale.value).format(MAX_PROMPT_CHARS) })];

/** The raw fixed part reads naturally: placeholder -> localized hint, doubled braces -> single. */
function fixedText(p: PromptOut): string {
  return p.fixed_text.replaceAll("{language_line}", t("prompts.languageLine")).replaceAll("{format_line}", t("prompts.formatLine")).replaceAll("{{", "{").replaceAll("}}", "}");
}

async function save() {
  const p = tab.value;
  saving.value = true;
  const ok = await store.save(p, drafts[p]);
  saving.value = false;
  if (ok) {
    drafts[p] = byPurpose(p)?.text ?? drafts[p];
    notify.show(t("settings.saved"), "success");
  }
}
async function doReset() {
  const p = tab.value;
  resetting.value = true;
  const ok = await store.reset(p);
  resetting.value = false;
  confirmOpen.value = false;
  if (ok) drafts[p] = byPurpose(p)?.text ?? drafts[p];
}
</script>

<template>
  <v-card class="mb-4" :title="t('prompts.title')" :subtitle="t('prompts.hint')" data-test="prompts-card">
    <v-tabs v-model="tab" color="primary" show-arrows>
      <v-tab v-for="p in purposes" :key="p" :value="p" :data-test="`prompt-tab-${p}`">{{ t(`prompts.tabs.${p}`) }}</v-tab>
    </v-tabs>
    <v-card-text v-if="current">
      <div class="d-flex align-center mb-2" style="min-height: 28px">
        <v-chip v-if="current.customized" size="small" color="primary" variant="tonal" data-test="prompt-customized">{{ t("prompts.customized") }}</v-chip>
      </div>
      <v-textarea
        v-model="drafts[tab]"
        :label="t('prompts.text')"
        auto-grow
        rows="6"
        variant="outlined"
        hide-details="auto"
        :counter="MAX_PROMPT_CHARS"
        persistent-counter
        :rules="rules"
        data-test="prompt-text"
      />
      <div v-if="current.fixed_text" class="mt-4" data-test="prompt-fixed">
        <div class="text-subtitle-2 mb-1">{{ t("prompts.fixed") }}</div>
        <pre class="text-medium-emphasis text-body-2" style="white-space: pre-wrap; overflow-wrap: anywhere">{{ fixedText(current) }}</pre>
      </div>
    </v-card-text>
    <v-card-actions v-if="current" class="flex-wrap">
      <v-btn :disabled="!current.customized" data-test="prompt-reset" @click="confirmOpen = true">{{ t("prompts.reset") }}</v-btn>
      <v-spacer />
      <v-btn color="primary" variant="flat" :disabled="!dirty || blank || tooLong" :loading="saving" data-test="prompt-save" @click="save">{{ t("common.save") }}</v-btn>
    </v-card-actions>
  </v-card>

  <ConfirmDialog v-model="confirmOpen" :title="t('prompts.resetTitle')" :text="t('prompts.resetConfirm')" :busy="resetting" :ok-label="t('prompts.reset')" @confirm="doReset" />
</template>
