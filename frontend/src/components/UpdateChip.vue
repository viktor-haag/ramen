<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useVersionStore } from "@/stores/version";

const { t } = useI18n();
const store = useVersionStore();
</script>

<template>
  <span v-if="store.showChip && store.info?.latest" class="d-inline-flex align-center">
    <v-chip
      class="d-none d-sm-inline-flex"
      color="primary"
      variant="tonal"
      prepend-icon="mdi-arrow-up-circle"
      :href="store.info.release_url ?? undefined"
      target="_blank"
      rel="noopener noreferrer"
      data-test="update-chip"
    >{{ t("update.chip", { version: store.info.latest }) }}</v-chip>
    <v-btn
      class="d-sm-none"
      color="primary"
      variant="tonal"
      icon="mdi-arrow-up-circle"
      size="small"
      :href="store.info.release_url ?? undefined"
      target="_blank"
      rel="noopener noreferrer"
      :title="t('update.chip', { version: store.info.latest })"
      :aria-label="t('update.chip', { version: store.info.latest })"
      data-test="update-chip-icon"
    />
    <v-btn
      variant="text"
      icon="mdi-close"
      size="x-small"
      :title="t('update.dismiss')"
      :aria-label="t('update.dismiss')"
      data-test="update-chip-dismiss"
      @click="store.dismiss(store.info.latest)"
    />
  </span>
</template>
