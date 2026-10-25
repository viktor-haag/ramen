<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { DailyLimitKind, LlmConfigIn, LlmConfigOut, LlmModelsIn, LlmProvider, ThinkingLevel } from "@/api/types";
import { useLlmStore } from "@/stores/llm";
import { useNotifyStore } from "@/stores/notify";

const props = defineProps<{ modelValue: boolean; config: LlmConfigOut | null }>();
const emit = defineEmits<{ "update:modelValue": [boolean] }>();
const { t } = useI18n();
const store = useLlmStore();

const PROVIDERS: LlmProvider[] = ["anthropic", "openai", "openai_compatible"];
const LEVELS: ThinkingLevel[] = ["off", "low", "medium", "high", "max"];
const providerItems = computed(() => PROVIDERS.map((p) => ({ value: p, title: t(`ai.providers.${p}`) })));
const kindItems = computed(() => (["none", "tokens", "eur"] as const).map((k) => ({ value: k, title: t(`ai.limit.${k}`) })));
const thinkingItems = computed(() => LEVELS.map((l) => ({ value: l, title: t(`ai.thinking.${l}`) })));

interface Form {
  name: string;
  provider: LlmProvider;
  base_url: string;
  api_key: string;
  clearKey: boolean;
  model: string;
  thinking: ThinkingLevel;
  supports_images: boolean;
  extraBody: string;
  extraHeaders: string;
  price_in: string;
  price_out: string;
  limitKind: DailyLimitKind;
  limitValue: string;
}
const form = reactive<Form>(blank());
const models = ref<string[]>([]);
const serverErrors = ref<Record<string, string>>({});
const saving = ref(false);
const loadingModels = ref(false);
const panel = ref<number | undefined>(undefined);

/** supports_images default: true for the hosted providers, false for generic OpenAI-compatible endpoints. */
const imagesDefault = (p: LlmProvider) => p !== "openai_compatible";

function blank(): Form {
  return {
    name: "", provider: "anthropic", base_url: "", api_key: "", clearKey: false, model: "", thinking: "off",
    supports_images: true, extraBody: "", extraHeaders: "", price_in: "", price_out: "",
    limitKind: "none", limitValue: "",
  };
}
const pretty = (o: object) => (Object.keys(o).length ? JSON.stringify(o, null, 2) : "");
const priceText = (n: number | null) => (n === null ? "" : String(n));

function init() {
  const c = props.config;
  Object.assign(
    form,
    c
      ? {
          name: c.name, provider: c.provider, base_url: c.base_url ?? "", api_key: "", clearKey: false, model: c.model,
          thinking: c.thinking, supports_images: c.supports_images, extraBody: pretty(c.extra_body),
          extraHeaders: pretty(c.extra_headers), price_in: priceText(c.price_in), price_out: priceText(c.price_out),
          limitKind: c.daily_limit_kind, limitValue: priceText(c.daily_limit_value),
        }
      : blank(),
  );
  models.value = [];
  serverErrors.value = {};
  panel.value = undefined;
}
watch(() => props.modelValue, (open) => open && init(), { immediate: true });

function onProvider(p: LlmProvider) {
  form.provider = p;
  if (p !== "openai_compatible") form.base_url = "";
  if (p === "openai_compatible") form.thinking = "off";
  if (!props.config) form.supports_images = imagesDefault(p);
}

const compat = computed(() => form.provider === "openai_compatible");

type Parsed = { value: Record<string, unknown> } | { error: string };
function parseObject(text: string, stringValues: boolean): Parsed {
  if (!text.trim()) return { value: {} };
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch {
    return { error: t("ai.dialog.jsonObject") };
  }
  if (v === null || typeof v !== "object" || Array.isArray(v)) return { error: t("ai.dialog.jsonObject") };
  if (stringValues && Object.values(v).some((x) => typeof x !== "string")) return { error: t("ai.dialog.jsonStrings") };
  return { value: v as Record<string, unknown> };
}
const body = computed(() => parseObject(form.extraBody, false));
const headers = computed(() => parseObject(form.extraHeaders, true));
const bodyError = computed(() => ("error" in body.value ? body.value.error : serverErrors.value.extra_body));
const headersError = computed(() => ("error" in headers.value ? headers.value.error : serverErrors.value.extra_headers));
const advancedError = computed(
  () => bodyError.value || headersError.value || serverErrors.value.price_in || serverErrors.value.price_out,
);
// Errors inside the collapsed panel must not stay hidden.
watch(advancedError, (e) => {
  if (e) panel.value = 0;
});
const canSave = computed(
  () => !("error" in body.value) && !("error" in headers.value) && form.name.trim() !== "" && form.model.trim() !== "",
);

const price = (s: string) => (s.trim() === "" ? null : Number(s));

function payload(): LlmConfigIn | null {
  if ("error" in body.value || "error" in headers.value) return null;
  const out: LlmConfigIn = {
    name: form.name.trim(),
    provider: form.provider,
    base_url: compat.value ? form.base_url.trim() || null : null,
    model: form.model.trim(),
    thinking: compat.value ? "off" : form.thinking,
    supports_images: form.supports_images,
    extra_body: body.value.value,
    extra_headers: headers.value.value as Record<string, string>,
    price_in: price(form.price_in),
    price_out: price(form.price_out),
    daily_limit_kind: form.limitKind,
    daily_limit_value: form.limitKind === "none" ? null : price(form.limitValue),
  };
  // PUT semantics: omitted api_key keeps the stored key, "" clears it.
  if (form.clearKey) out.api_key = "";
  else if (form.api_key.trim() !== "") out.api_key = form.api_key.trim();
  return out;
}

async function save() {
  const data = payload();
  if (!data || saving.value) return;
  saving.value = true;
  serverErrors.value = {};
  const visible = ["name", "provider", "api_key", "model", "extra_body", "extra_headers", "price_in", "price_out", "daily_limit_kind", "daily_limit_value"];
  visible.push(compat.value ? "base_url" : "thinking");
  const res = await store.save(data, props.config?.id, visible);
  saving.value = false;
  if (res.ok) {
    useNotifyStore().show(t("settings.saved"), "success");
    emit("update:modelValue", false);
  } else serverErrors.value = res.errors;
}

async function loadModels() {
  const input: LlmModelsIn = { provider: form.provider, base_url: compat.value ? form.base_url.trim() || null : null };
  // The stored key and headers are only reused for the unchanged provider, and not while the key is being cleared.
  if (props.config && props.config.provider === form.provider && !form.clearKey) input.config_id = props.config.id;
  if (form.api_key.trim() !== "") input.api_key = form.api_key.trim();
  if (!("error" in body.value) && Object.keys(body.value.value).length) input.extra_body = body.value.value;
  if (!("error" in headers.value) && Object.keys(headers.value.value).length) input.extra_headers = headers.value.value as Record<string, string>;
  loadingModels.value = true;
  const res = await store.loadModels(input);
  loadingModels.value = false;
  if (res) {
    models.value = res;
    useNotifyStore().show(t("ai.dialog.modelsLoaded", { count: res.length }), "success");
  }
}
</script>

<template>
  <v-dialog :model-value="modelValue" max-width="640" scrollable persistent @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <v-card :title="config ? t('ai.dialog.editTitle') : t('ai.dialog.addTitle')" data-test="llm-dialog">
      <v-card-text>
        <v-text-field v-model="form.name" :label="t('ai.dialog.name')" :error-messages="serverErrors.name" data-test="llm-name" />
        <v-select
          :model-value="form.provider"
          :items="providerItems"
          :label="t('ai.dialog.provider')"
          :error-messages="serverErrors.provider"
          data-test="llm-provider"
          @update:model-value="onProvider"
        />
        <v-text-field
          v-if="compat"
          v-model="form.base_url"
          :label="t('ai.dialog.baseUrl')"
          placeholder="http://localhost:11434/v1"
          :error-messages="serverErrors.base_url"
          data-test="llm-base-url"
        />
        <v-text-field
          v-model="form.api_key"
          type="password"
          autocomplete="new-password"
          :label="t('ai.dialog.apiKey')"
          :placeholder="config?.api_key ?? ''"
          persistent-placeholder
          :disabled="form.clearKey"
          :error-messages="serverErrors.api_key"
          data-test="llm-api-key"
        />
        <v-checkbox
          v-if="config?.has_api_key && compat"
          v-model="form.clearKey"
          :label="t('ai.dialog.clearKey')"
          density="compact"
          hide-details
          data-test="llm-clear-key"
        />
        <div class="d-flex ga-2 align-start mt-2">
          <v-combobox
            :model-value="form.model"
            :items="models"
            :label="t('ai.dialog.model')"
            :error-messages="serverErrors.model"
            class="flex-grow-1"
            data-test="llm-model"
            @update:model-value="(v: string | null) => (form.model = v ?? '')"
          />
          <v-btn class="mt-1" variant="tonal" :loading="loadingModels" data-test="llm-load-models" @click="loadModels">{{ t("ai.dialog.loadModels") }}</v-btn>
        </div>
        <v-select
          v-if="!compat"
          v-model="form.thinking"
          :items="thinkingItems"
          :label="t('ai.dialog.thinking')"
          :error-messages="serverErrors.thinking"
          data-test="llm-thinking"
        />
        <v-switch v-model="form.supports_images" :label="t('ai.dialog.supportsImages')" color="primary" density="comfortable" hide-details data-test="llm-images" />

        <h3 class="text-subtitle-1 mt-4 mb-2">{{ t("ai.limit.title") }}</h3>
        <div class="d-flex ga-2 flex-wrap">
          <v-select
            :model-value="form.limitKind"
            :items="kindItems"
            :label="t('ai.limit.kind')"
            :error-messages="serverErrors.daily_limit_kind"
            class="flex-grow-1"
            data-test="llm-limit-kind"
            @update:model-value="(v: DailyLimitKind) => (form.limitKind = v)"
          />
          <v-text-field
            v-model="form.limitValue"
            type="number"
            min="0"
            :step="form.limitKind === 'tokens' ? 1 : 'any'"
            :label="t(form.limitKind === 'eur' ? 'ai.limit.eurValue' : 'ai.limit.tokensValue')"
            :hint="form.limitKind === 'eur' ? t('ai.limit.eurHint') : undefined"
            :persistent-hint="form.limitKind === 'eur'"
            :disabled="form.limitKind === 'none'"
            :error-messages="serverErrors.daily_limit_value"
            class="flex-grow-1"
            data-test="llm-limit-value"
          />
        </div>

        <v-expansion-panels v-model="panel" variant="accordion" class="mt-4">
          <v-expansion-panel :value="0" eager data-test="llm-advanced">
            <v-expansion-panel-title>{{ t("ai.dialog.advanced") }}</v-expansion-panel-title>
            <v-expansion-panel-text>
              <v-textarea v-model="form.extraBody" :label="t('ai.dialog.extraBody')" rows="3" auto-grow :error-messages="bodyError" data-test="llm-extra-body" />
              <v-textarea v-model="form.extraHeaders" :label="t('ai.dialog.extraHeaders')" rows="3" auto-grow :error-messages="headersError" data-test="llm-extra-headers" />
              <v-text-field v-model="form.price_in" type="number" min="0" step="any" :label="t('ai.dialog.priceIn')" :error-messages="serverErrors.price_in" data-test="llm-price-in" />
              <v-text-field v-model="form.price_out" type="number" min="0" step="any" :label="t('ai.dialog.priceOut')" :error-messages="serverErrors.price_out" data-test="llm-price-out" />
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn :disabled="saving" data-test="llm-cancel" @click="emit('update:modelValue', false)">{{ t("common.cancel") }}</v-btn>
        <v-btn color="primary" variant="flat" :disabled="!canSave" :loading="saving" data-test="llm-save" @click="save">{{ t("common.save") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
