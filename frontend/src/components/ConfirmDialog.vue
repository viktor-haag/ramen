<script setup lang="ts">
import { useI18n } from "vue-i18n";

defineProps<{ modelValue: boolean; title: string; text: string; busy?: boolean; okLabel?: string }>();
const emit = defineEmits<{ "update:modelValue": [boolean]; confirm: [] }>();
const { t } = useI18n();
</script>

<template>
  <v-dialog :model-value="modelValue" max-width="400" @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <v-card :title="title" :text="text">
      <v-card-actions>
        <v-spacer />
        <v-btn data-test="confirm-cancel" @click="emit('update:modelValue', false)">{{ t("common.cancel") }}</v-btn>
        <v-btn color="error" variant="flat" :disabled="busy" :loading="busy" data-test="confirm-ok" @click="emit('confirm')">{{ okLabel ?? t("common.delete") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
