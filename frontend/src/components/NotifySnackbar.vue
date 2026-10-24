<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useNotifyStore } from "@/stores/notify";

const { t } = useI18n();
const notify = useNotifyStore();
</script>

<template>
  <v-snackbar v-model="notify.visible" :color="notify.color" :timeout="6000" multi-line>
    {{ notify.message }}
    <template #actions>
      <v-btn v-if="notify.action" variant="text" :to="notify.action.to" data-test="notify-action" @click="notify.visible = false">
        {{ notify.action.label }}
      </v-btn>
      <v-btn variant="text" @click="notify.visible = false">{{ t("common.close") }}</v-btn>
    </template>
  </v-snackbar>
</template>
