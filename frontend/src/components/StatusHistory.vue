<script setup lang="ts">
import { useI18n } from "vue-i18n";
import type { StatusChangeOut } from "@/api/types";
import { formatDateTime } from "@/domain/time";

defineProps<{ changes: StatusChangeOut[] }>();
const { t, locale } = useI18n();
</script>

<template>
  <div v-if="changes.length === 0" class="text-medium-emphasis">{{ t("detail.history.empty") }}</div>
  <v-timeline v-else side="end" density="compact" align="start" data-test="status-history">
    <v-timeline-item v-for="c in [...changes].reverse()" :key="c.id" size="small" dot-color="primary">
      <div class="font-weight-medium">
        {{
          c.from_status
            ? t("detail.history.change", { from: t(`status.${c.from_status}`), to: t(`status.${c.to_status}`) })
            : t("detail.history.initial", { to: t(`status.${c.to_status}`) })
        }}
      </div>
      <div class="text-caption text-medium-emphasis">{{ formatDateTime(c.changed_at, locale) }}</div>
      <div v-if="c.comment" class="comment">{{ c.comment }}</div>
    </v-timeline-item>
  </v-timeline>
</template>

<style scoped>
.comment {
  white-space: pre-line;
  overflow-wrap: anywhere;
}
</style>
