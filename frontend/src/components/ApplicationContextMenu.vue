<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import type { ApplicationOut } from "@/api/types";
import { ACTIVE_STATUSES, allowedTargets } from "@/domain/status";
import { useApplicationsStore } from "@/stores/applications";

const props = defineProps<{ application: ApplicationOut | null; x: number; y: number; modelValue: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();

const { t } = useI18n();
const router = useRouter();
const store = useApplicationsStore();

const isActive = computed(() => !!props.application && ACTIVE_STATUSES.includes(props.application.status));
const targets = computed(() => (props.application ? (isActive.value ? allowedTargets(props.application.status) : ACTIVE_STATUSES) : []));

function close() {
  emit("update:modelValue", false);
}

function choose(to: (typeof targets.value)[number]) {
  const a = props.application;
  close();
  if (!a) return;
  if (isActive.value) void store.move(a.id, to);
  else void store.reopen(a.id, to);
}

function open() {
  const a = props.application;
  close();
  if (a) void router.push("/applications/" + a.id);
}
</script>

<template>
  <v-menu :model-value="modelValue" :target="[x, y]" @update:model-value="emit('update:modelValue', $event)">
    <v-list v-if="application" density="compact">
      <v-list-subheader>{{ isActive ? t("applications.menu.changeStatus") : t("applications.menu.reopen") }}</v-list-subheader>
      <v-list-item
        v-for="s in targets"
        :key="s"
        :data-test="(isActive ? 'cm-status-' : 'cm-reopen-') + s"
        :title="t(`status.${s}`)"
        @click="choose(s)"
      />
      <v-divider />
      <v-list-item data-test="cm-open" prepend-icon="mdi-open-in-new" :title="t('applications.menu.open')" @click="open" />
    </v-list>
  </v-menu>
</template>
