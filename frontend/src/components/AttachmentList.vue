<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { AttachmentKind, AttachmentOut } from "@/api/types";
import { ATTACHMENT_KINDS } from "@/api/types";
import { useApplicationDetailStore } from "@/stores/applicationDetail";
import ConfirmDialog from "./ConfirmDialog.vue";

const { t } = useI18n();
const store = useApplicationDetailStore();
const items = computed(() => store.app?.attachments ?? []);

const kind = ref<AttachmentKind>("cv");
const file = ref<File | null>(null);
const uploading = ref(false);
const deleting = ref<AttachmentOut | null>(null);

function onFile(v: File | File[] | null) {
  file.value = Array.isArray(v) ? (v[0] ?? null) : v;
}
async function upload() {
  if (!file.value) return;
  uploading.value = true;
  try {
    if (await store.uploadAttachment(file.value, kind.value)) file.value = null;
  } finally {
    uploading.value = false;
  }
}
const deleteBusy = ref(false);
async function confirmDelete() {
  if (!deleting.value || deleteBusy.value) return;
  deleteBusy.value = true;
  try {
    if (await store.removeAttachment(deleting.value.id)) deleting.value = null;
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
        :label="t('detail.attachments.file')"
        density="comfortable"
        hide-details
        style="min-width: 240px; flex: 1"
        data-test="attachment-file"
        @update:model-value="onFile"
      />
      <v-select
        v-model="kind"
        :label="t('detail.attachments.kind')"
        density="comfortable"
        hide-details
        style="max-width: 200px"
        :items="ATTACHMENT_KINDS.map((k) => ({ value: k, title: t(`attachmentKind.${k}`) }))"
      />
      <v-btn color="primary" prepend-icon="mdi-upload" :disabled="!file" :loading="uploading" data-test="attachment-upload" @click="upload">
        {{ t("detail.attachments.upload") }}
      </v-btn>
    </div>
    <div v-if="items.length === 0" class="text-medium-emphasis">{{ t("detail.attachments.empty") }}</div>
    <v-list v-else data-test="attachment-list">
      <v-list-item v-for="a in items" :key="a.id" :title="a.display_name || a.filename">
        <template #prepend><v-chip size="small" label class="mr-3">{{ t(`attachmentKind.${a.kind}`) }}</v-chip></template>
        <template #append>
          <v-btn
            icon="mdi-download"
            variant="text"
            size="small"
            :href="`/api/attachments/${a.id}/download`"
            :aria-label="t('detail.attachments.download')"
          />
          <v-btn icon="mdi-delete" variant="text" size="small" :aria-label="t('common.delete')" data-test="attachment-delete" @click="deleting = a" />
        </template>
      </v-list-item>
    </v-list>
    <ConfirmDialog
      :busy="deleteBusy"
      :model-value="deleting !== null"
      :title="t('detail.attachments.deleteTitle')"
      :text="t('detail.attachments.deleteText', { name: deleting?.display_name || deleting?.filename || '' })"
      @update:model-value="deleting = null"
      @confirm="confirmDelete"
    />
  </div>
</template>
