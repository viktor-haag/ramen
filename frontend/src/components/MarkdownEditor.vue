<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { renderMarkdown } from "@/domain/markdown";

const props = defineProps<{ modelValue: string; disabled?: boolean }>();
const emit = defineEmits<{
  "update:modelValue": [text: string];
  /** The editor lost focus; the parent decides whether anything changed. */
  save: [];
}>();
const { t } = useI18n();

const mode = ref<"edit" | "preview">("edit");
const html = computed(() => renderMarkdown(props.modelValue));
</script>

<template>
  <div>
    <v-btn-toggle v-model="mode" mandatory density="compact" variant="outlined" class="mb-2">
      <v-btn value="edit" size="small" prepend-icon="mdi-pencil" data-test="md-mode-edit">{{ t("me.markdown.edit") }}</v-btn>
      <v-btn value="preview" size="small" prepend-icon="mdi-eye" data-test="md-mode-preview">{{ t("me.markdown.preview") }}</v-btn>
    </v-btn-toggle>
    <v-textarea
      v-if="mode === 'edit'"
      :model-value="modelValue"
      :disabled="disabled"
      auto-grow
      rows="10"
      hide-details
      variant="outlined"
      class="font-monospace"
      data-test="md-input"
      @update:model-value="emit('update:modelValue', $event)"
      @blur="emit('save')"
    />
    <!-- renderMarkdown escapes raw HTML (markdown-it html: false), so v-html is safe here -->
    <div v-else-if="modelValue.trim()" class="markdown-preview pa-3" data-test="md-preview" v-html="html" />
    <div v-else class="text-medium-emphasis pa-3" data-test="md-preview">{{ t("me.markdown.empty") }}</div>
  </div>
</template>

<style scoped>
.markdown-preview :deep(h2) {
  font-size: 1.15rem;
  margin: 1rem 0 0.4rem;
}
.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  padding-left: 1.5rem;
}
.markdown-preview :deep(p) {
  margin-bottom: 0.5rem;
}
</style>
