<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { ApiError, api } from "@/api/client";
import type { FromUrlIn, ManualPostingIn, PostingOut } from "@/api/types";
import { errorMessage } from "@/i18n";
import { useFeedStore } from "@/stores/feed";
import { useNotifyStore } from "@/stores/notify";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();

type Step = "url" | "preview" | "manual";
type Employment = "none" | "fulltime" | "parttime";
type Remote = "unknown" | "yes" | "no";

const { t } = useI18n();
const router = useRouter();
const feed = useFeedStore();

const step = ref<Step>("url");
const url = ref("");
const busy = ref(false);
const error = ref("");
const hint = ref("");
const preview = ref<PostingOut | null>(null);

function emptyForm() {
  return { title: "", company: "", location: "", url: "", description: "", employment: "none" as Employment, remote: "unknown" as Remote };
}
const form = ref(emptyForm());

function reset() {
  step.value = "url";
  url.value = "";
  busy.value = false;
  error.value = "";
  hint.value = "";
  preview.value = null;
  form.value = emptyForm();
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) reset();
  },
);

// Only http(s) links are rendered; the URL comes from third-party sites.
const safeUrl = computed(() => (preview.value?.url && /^https?:\/\//i.test(preview.value.url) ? preview.value.url : null));
const canFetch = computed(() => url.value.trim().length > 0 && !busy.value);
const canSaveManual = computed(() => form.value.title.trim().length > 0 && !busy.value);

function close() {
  emit("update:modelValue", false);
}

async function finish(applicationId: number) {
  close();
  reset();
  void feed.reset();
  await router.push(`/applications/${applicationId}`);
}

async function fetchUrl() {
  if (!canFetch.value) return;
  busy.value = true;
  error.value = "";
  const body: FromUrlIn = { url: url.value.trim() };
  try {
    preview.value = await api.post<PostingOut>("/postings/from-url", body);
    step.value = "preview";
  } catch (e) {
    if (e instanceof ApiError && e.status === 404 && e.code === "no_plugin_for_url") {
      form.value = { ...emptyForm(), url: body.url };
      hint.value = errorMessage(e);
      step.value = "manual";
    } else {
      error.value = e instanceof ApiError ? errorMessage(e) : e instanceof Error ? e.message : String(e);
    }
  } finally {
    busy.value = false;
  }
}

function skip() {
  hint.value = "";
  form.value = { ...emptyForm(), url: url.value.trim() };
  step.value = "manual";
}

async function savePreview() {
  const p = preview.value;
  if (!p || busy.value) return;
  busy.value = true;
  try {
    const out = await api.post<{ application_id: number }>(`/postings/${p.id}/save`);
    await finish(out.application_id);
  } catch (e) {
    if (e instanceof ApiError && e.code === "already_saved") {
      try {
        // The preview may be stale: re-read the posting to find its application.
        const fresh = await api.get<PostingOut>(`/postings/${p.id}`);
        if (fresh.application_id !== null) {
          await finish(fresh.application_id);
          return;
        }
      } catch {
        /* fall through to the generic error */
      }
    }
    useNotifyStore().error(e);
  } finally {
    busy.value = false;
  }
}

async function openExisting() {
  if (preview.value?.application_id != null) await finish(preview.value.application_id);
}

async function saveManual() {
  if (!canSaveManual.value) return;
  busy.value = true;
  const f = form.value;
  const body: ManualPostingIn = {
    title: f.title.trim(),
    company: f.company.trim() || null,
    location: f.location.trim() || null,
    url: f.url.trim() || null,
    description: f.description.trim() || null,
    employment_type: f.employment === "none" ? null : f.employment,
    remote: f.remote === "unknown" ? null : f.remote === "yes",
  };
  try {
    const out = await api.post<{ application_id: number }>("/postings", body);
    await finish(out.application_id);
  } catch (e) {
    useNotifyStore().error(e);
  } finally {
    busy.value = false;
  }
}

const employmentItems = computed(() =>
  (["none", "fulltime", "parttime"] as Employment[]).map((v) => ({ value: v, title: t(`addPosting.employment.${v}`) })),
);
const remoteItems = computed(() =>
  (["unknown", "yes", "no"] as Remote[]).map((v) => ({ value: v, title: t(`addPosting.remote.${v}`) })),
);
</script>

<template>
  <v-dialog :model-value="modelValue" max-width="640" scrollable @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <v-card :title="step === 'manual' ? t('addPosting.manualTitle') : t('addPosting.title')">
      <v-card-text>
        <template v-if="step === 'url'">
          <v-text-field
            v-model="url"
            :label="t('addPosting.urlLabel')"
            :hint="t('addPosting.urlHint')"
            persistent-hint
            autofocus
            data-test="ap-url"
            @keydown.enter="fetchUrl"
          />
          <v-alert v-if="error" type="error" variant="tonal" class="mt-4" data-test="ap-error">{{ error }}</v-alert>
        </template>

        <div v-else-if="step === 'preview' && preview" data-test="ap-preview">
          <h3 class="text-h6">{{ preview.title }}</h3>
          <div class="text-subtitle-1">{{ preview.company }}</div>
          <div class="text-body-2 text-medium-emphasis">{{ preview.location }}</div>
          <v-btn
            v-if="safeUrl"
            size="small"
            variant="text"
            prepend-icon="mdi-open-in-new"
            :href="safeUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="px-0"
          >
            {{ safeUrl }}
          </v-btn>
          <v-alert v-if="preview.application_id !== null" type="info" variant="tonal" density="compact" class="my-3">
            {{ t("addPosting.alreadyApplication") }}
          </v-alert>
          <v-divider class="my-3" />
          <div v-if="preview.description" class="description" data-test="ap-preview-description">{{ preview.description }}</div>
          <div v-else class="text-medium-emphasis">{{ t("addPosting.noDescription") }}</div>
        </div>

        <div v-else data-test="ap-manual">
          <v-alert v-if="hint" type="info" variant="tonal" class="mb-4" data-test="ap-hint">{{ hint }}</v-alert>
          <v-text-field v-model="form.title" :label="t('addPosting.fields.title')" required data-test="ap-m-title" />
          <v-text-field v-model="form.company" :label="t('addPosting.fields.company')" data-test="ap-m-company" />
          <v-text-field v-model="form.location" :label="t('addPosting.fields.location')" data-test="ap-m-location" />
          <v-text-field v-model="form.url" :label="t('addPosting.fields.url')" data-test="ap-m-url" />
          <v-textarea v-model="form.description" :label="t('addPosting.fields.description')" rows="5" data-test="ap-m-description" />
          <v-select v-model="form.employment" :items="employmentItems" :label="t('addPosting.fields.employmentType')" data-test="ap-m-employment" />
          <v-select v-model="form.remote" :items="remoteItems" :label="t('addPosting.fields.remote')" data-test="ap-m-remote" />
        </div>
      </v-card-text>

      <v-card-actions>
        <v-btn v-if="step === 'url'" variant="text" data-test="ap-skip" @click="skip">{{ t("addPosting.skip") }}</v-btn>
        <v-btn v-else variant="text" data-test="ap-back" @click="step = 'url'">{{ t("addPosting.back") }}</v-btn>
        <v-spacer />
        <v-btn variant="text" @click="close">{{ t("common.cancel") }}</v-btn>
        <v-btn v-if="step === 'url'" color="primary" variant="flat" :disabled="!canFetch" :loading="busy" data-test="ap-fetch" @click="fetchUrl">
          {{ t("addPosting.fetch") }}
        </v-btn>
        <template v-else-if="step === 'preview' && preview">
          <v-btn
            v-if="preview.application_id !== null"
            color="primary"
            variant="flat"
            data-test="ap-open"
            @click="openExisting"
          >
            {{ t("addPosting.open") }}
          </v-btn>
          <v-btn v-else color="primary" variant="flat" :loading="busy" data-test="ap-save" @click="savePreview">
            {{ t("addPosting.save") }}
          </v-btn>
        </template>
        <v-btn v-else color="primary" variant="flat" :disabled="!canSaveManual" :loading="busy" data-test="ap-m-save" @click="saveManual">
          {{ t("common.save") }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.description {
  white-space: pre-line;
  overflow-wrap: anywhere;
}
</style>
