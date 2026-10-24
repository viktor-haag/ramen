<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { ProfileDocumentOut } from "@/api/types";
import { useMeStore } from "@/stores/me";
import ConfirmDialog from "./ConfirmDialog.vue";

const { t } = useI18n();
const store = useMeStore();

// --- upload ---
const file = ref<File | null>(null);
const description = ref("");
const uploading = ref(false);
function onFile(v: File | File[] | null) {
  file.value = Array.isArray(v) ? (v[0] ?? null) : v;
}
async function upload() {
  if (!file.value) return;
  uploading.value = true;
  try {
    if (await store.upload(file.value, description.value)) {
      file.value = null;
      description.value = "";
    }
  } finally {
    uploading.value = false;
  }
}

// --- description (saved on blur when changed) ---
const drafts = ref<Record<number, string>>({});
const descriptionOf = (d: ProfileDocumentOut) => drafts.value[d.id] ?? d.description ?? "";
async function saveDescription(d: ProfileDocumentOut) {
  const value = descriptionOf(d);
  if (value === (d.description ?? "")) {
    delete drafts.value[d.id];
    return;
  }
  // keep the typed text in the field when the save fails
  if (await store.updateDocument(d.id, { description: value || null })) delete drafts.value[d.id];
}

// --- text dialog ---
const editing = ref<ProfileDocumentOut | null>(null);
const textOpen = ref(false);
const textDraft = ref("");
const savingText = ref(false);
function openText(d: ProfileDocumentOut) {
  editing.value = d;
  textDraft.value = d.text ?? "";
  textOpen.value = true;
}
async function saveText() {
  if (!editing.value) return;
  savingText.value = true;
  try {
    if (textDraft.value === (editing.value.text ?? "") || (await store.updateDocument(editing.value.id, { text: textDraft.value }))) textOpen.value = false;
  } finally {
    savingText.value = false;
  }
}

// --- extraction ---
const needsExtraction = (d: ProfileDocumentOut) => d.kind === "pdf_scan" || d.kind === "image";
const extractHint = computed(() => {
  if (store.canExtract) return "";
  return store.extractionConfig ? t("me.documents.extractNoImages") : t("me.documents.extractNoConfig");
});

// --- delete ---
const deleting = ref<ProfileDocumentOut | null>(null);
const deleteBusy = ref(false);
async function confirmDelete() {
  if (!deleting.value || deleteBusy.value) return;
  deleteBusy.value = true;
  try {
    if (await store.removeDocument(deleting.value.id)) deleting.value = null;
  } finally {
    deleteBusy.value = false;
  }
}
</script>

<template>
  <div>
    <div class="d-flex ga-3 align-start flex-wrap mb-3">
      <v-file-input
        :model-value="file"
        :label="t('me.documents.file')"
        accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md"
        density="comfortable"
        hide-details
        style="min-width: 240px; flex: 1"
        data-test="doc-file"
        @update:model-value="onFile"
      />
      <v-text-field
        v-model="description"
        :label="t('me.documents.description')"
        density="comfortable"
        hide-details
        style="min-width: 240px; flex: 1"
        data-test="doc-upload-description"
      />
      <v-btn color="primary" prepend-icon="mdi-upload" :disabled="!file" :loading="uploading" data-test="doc-upload" @click="upload">
        {{ t("me.documents.upload") }}
      </v-btn>
    </div>
    <div v-if="store.documents.length === 0" class="text-medium-emphasis" data-test="doc-empty">{{ t("me.documents.empty") }}</div>
    <v-list v-else data-test="doc-list" lines="two">
      <v-list-item v-for="d in store.documents" :key="d.id" :data-test="`doc-${d.id}`">
        <template #prepend>
          <v-chip size="small" label class="mr-3" :data-test="`doc-kind-${d.id}`">{{ t(`me.documents.kind.${d.kind}`) }}</v-chip>
        </template>
        <v-list-item-title>{{ d.display_name }}</v-list-item-title>
        <v-list-item-subtitle class="mt-1">
          <v-chip
            size="x-small"
            label
            :color="d.usable ? 'success' : 'warning'"
            variant="tonal"
            :data-test="`doc-status-${d.id}`"
          >
            {{ d.usable ? t("me.documents.usable") : t("me.documents.unusable") }}
            <template v-if="d.usable && d.text_source"> ({{ t(`me.documents.source.${d.text_source}`) }})</template>
          </v-chip>
        </v-list-item-subtitle>
        <v-text-field
          :model-value="descriptionOf(d)"
          :label="t('me.documents.description')"
          density="compact"
          hide-details
          variant="underlined"
          class="mt-1"
          style="max-width: 480px"
          :data-test="`doc-description-${d.id}`"
          @update:model-value="drafts[d.id] = $event"
          @blur="saveDescription(d)"
        />
        <template #append>
          <v-btn
            icon="mdi-text-box-edit-outline"
            variant="text"
            size="small"
            :aria-label="t('me.documents.viewText')"
            :title="t('me.documents.viewText')"
            :data-test="`doc-text-${d.id}`"
            @click="openText(d)"
          />
          <span v-if="needsExtraction(d)" :title="extractHint" :data-test="`doc-extract-tip-${d.id}`">
            <v-btn
              icon="mdi-text-recognition"
              variant="text"
              size="small"
              :disabled="!store.canExtract"
              :loading="store.extracting.has(d.id)"
              :aria-label="t('me.documents.extract')"
              :title="store.canExtract ? t('me.documents.extract') : undefined"
              :data-test="`doc-extract-${d.id}`"
              @click="store.extract(d.id)"
            />
          </span>
          <v-btn
            icon="mdi-download"
            variant="text"
            size="small"
            :href="`/api/me/documents/${d.id}/download`"
            :aria-label="t('me.documents.download')"
            :title="t('me.documents.download')"
          />
          <v-btn
            icon="mdi-delete"
            variant="text"
            size="small"
            :aria-label="t('common.delete')"
            :data-test="`doc-delete-${d.id}`"
            @click="deleting = d"
          />
        </template>
      </v-list-item>
    </v-list>

    <v-dialog v-model="textOpen" max-width="800">
      <v-card :title="editing?.display_name ?? ''">
        <v-card-text>
          <p class="text-body-2 text-medium-emphasis mb-3">{{ t("me.documents.textHint") }}</p>
          <v-textarea v-model="textDraft" auto-grow rows="12" hide-details variant="outlined" data-test="doc-text-input" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn data-test="doc-text-cancel" @click="textOpen = false">{{ t("common.cancel") }}</v-btn>
          <v-btn color="primary" variant="flat" :loading="savingText" data-test="doc-text-save" @click="saveText">{{ t("common.save") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      :busy="deleteBusy"
      :model-value="deleting !== null"
      :title="t('me.documents.deleteTitle')"
      :text="t('me.documents.deleteText', { name: deleting?.display_name ?? '' })"
      @update:model-value="deleting = null"
      @confirm="confirmDelete"
    />
  </div>
</template>
