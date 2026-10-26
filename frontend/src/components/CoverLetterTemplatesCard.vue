<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { CoverLetterTemplate } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { useCoverLetterTemplatesStore } from "@/stores/coverLetterTemplates";

const { t } = useI18n();
const store = useCoverLetterTemplatesStore();

onMounted(() => store.load());

// --- upload ---
const file = ref<File | null>(null);
const uploading = ref(false);
function onFile(v: File | File[] | null) {
  file.value = Array.isArray(v) ? (v[0] ?? null) : v;
}
async function upload() {
  if (!file.value) return;
  uploading.value = true;
  try {
    if (await store.upload(file.value)) file.value = null;
  } finally {
    uploading.value = false;
  }
}

// --- rename ---
const renaming = ref<CoverLetterTemplate | null>(null);
const renameDraft = ref("");
const renameBusy = ref(false);
function openRename(item: CoverLetterTemplate) {
  renaming.value = item;
  renameDraft.value = item.name;
}
async function saveRename() {
  if (!renaming.value || renameBusy.value) return;
  const name = renameDraft.value.trim();
  if (!name) return;
  renameBusy.value = true;
  try {
    if (name === renaming.value.name || (await store.rename(renaming.value.id, name))) renaming.value = null;
  } finally {
    renameBusy.value = false;
  }
}

// --- delete ---
const deleting = ref<CoverLetterTemplate | null>(null);
const deleteBusy = ref(false);
async function confirmDelete() {
  if (!deleting.value || deleteBusy.value) return;
  deleteBusy.value = true;
  try {
    if (await store.remove(deleting.value.id)) deleting.value = null;
  } finally {
    deleteBusy.value = false;
  }
}
</script>

<template>
  <v-card class="mb-6" :title="t('coverTemplates.title')" :subtitle="t('coverTemplates.hint')" data-test="cover-templates-card">
    <v-card-text>
      <div class="d-flex ga-3 align-start flex-wrap mb-3">
        <v-file-input
          :model-value="file"
          :label="t('coverTemplates.file')"
          accept=".tex"
          density="comfortable"
          hide-details
          style="min-width: 240px; flex: 1"
          data-test="cover-template-file"
          @update:model-value="onFile"
        />
        <v-btn color="primary" prepend-icon="mdi-upload" :disabled="!file" :loading="uploading" data-test="cover-template-upload" @click="upload">
          {{ t("coverTemplates.upload") }}
        </v-btn>
      </div>
      <div v-if="store.items.length === 0" class="text-medium-emphasis" data-test="cover-template-empty">{{ t("coverTemplates.empty") }}</div>
      <v-list v-else data-test="cover-template-list">
        <v-list-item v-for="item in store.items" :key="item.id" :data-test="`cover-template-${item.id}`">
          <v-list-item-title>
            {{ item.name }}
            <v-chip v-if="item.builtin" class="ml-2" size="x-small" label :data-test="`cover-template-builtin-${item.id}`">{{ t("coverTemplates.builtin") }}</v-chip>
          </v-list-item-title>
          <template #append>
            <v-btn
              icon="mdi-download"
              variant="text"
              size="small"
              :href="`/api/cover-letter-templates/${item.id}/download`"
              :aria-label="t('coverTemplates.download')"
              :title="t('coverTemplates.download')"
              :data-test="`cover-template-download-${item.id}`"
            />
            <v-btn
              v-if="!item.builtin"
              icon="mdi-pencil"
              variant="text"
              size="small"
              :aria-label="t('coverTemplates.rename')"
              :title="t('coverTemplates.rename')"
              :data-test="`cover-template-rename-${item.id}`"
              @click="openRename(item)"
            />
            <v-btn
              v-if="!item.builtin"
              icon="mdi-delete"
              variant="text"
              size="small"
              :aria-label="t('common.delete')"
              :data-test="`cover-template-delete-${item.id}`"
              @click="deleting = item"
            />
          </template>
        </v-list-item>
      </v-list>
    </v-card-text>

    <v-dialog :model-value="renaming !== null" max-width="400" @update:model-value="renaming = null">
      <v-card :title="t('coverTemplates.renameTitle')">
        <v-card-text>
          <v-text-field
            v-model="renameDraft"
            :label="t('coverTemplates.name')"
            hide-details
            autofocus
            data-test="cover-template-rename-input"
            @keydown.enter="saveRename"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn data-test="cover-template-rename-cancel" @click="renaming = null">{{ t("common.cancel") }}</v-btn>
          <v-btn color="primary" variant="flat" :loading="renameBusy" :disabled="!renameDraft.trim()" data-test="cover-template-rename-save" @click="saveRename">{{ t("common.save") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      :busy="deleteBusy"
      :model-value="deleting !== null"
      :title="t('coverTemplates.deleteTitle')"
      :text="t('coverTemplates.deleteText', { name: deleting?.name ?? '' })"
      @update:model-value="deleting = null"
      @confirm="confirmDelete"
    />
  </v-card>
</template>
