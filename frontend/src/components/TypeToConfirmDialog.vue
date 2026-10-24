<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ modelValue: boolean; title: string; text: string; busy?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [boolean]; confirm: [] }>();
const { t } = useI18n();

const typed = ref("");
// Surrounding whitespace is ignored; the comparison itself is exact (case-sensitive).
const matches = computed(() => typed.value.trim() === t("confirm.word"));

watch(
  () => props.modelValue,
  () => {
    typed.value = "";
  },
);
</script>

<template>
  <v-dialog :model-value="modelValue" max-width="440" persistent @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <v-card :title="title">
      <v-card-text>
        <p class="mb-4">{{ text }}</p>
        <v-text-field
          v-model="typed"
          :label="t('settings.danger.typeToConfirm', { word: t('confirm.word') })"
          autocomplete="off"
          autofocus
          data-test="ttc-input"
          @keydown.enter="matches && !busy && emit('confirm')"
        />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn :disabled="busy" data-test="ttc-cancel" @click="emit('update:modelValue', false)">{{ t("common.cancel") }}</v-btn>
        <v-btn color="error" variant="flat" :disabled="!matches || busy" :loading="busy" data-test="ttc-ok" @click="emit('confirm')">{{ t("common.delete") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
