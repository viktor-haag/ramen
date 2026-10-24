<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { AppointmentKind, AppointmentOut } from "@/api/types";
import { APPOINTMENT_KINDS } from "@/api/types";
import { formatDateTime, fromLocalInput, toLocalInput } from "@/domain/time";
import { useApplicationDetailStore } from "@/stores/applicationDetail";
import ConfirmDialog from "./ConfirmDialog.vue";

const { t, locale } = useI18n();
const store = useApplicationDetailStore();
const items = computed(() => store.app?.appointments ?? []);

const dialog = ref(false);
const editId = ref<number | null>(null);
const kind = ref<AppointmentKind>("interview");
const startsAt = ref("");
const note = ref("");
const deleting = ref<AppointmentOut | null>(null);

function openNew() {
  editId.value = null;
  kind.value = "interview";
  startsAt.value = "";
  note.value = "";
  dialog.value = true;
}
function openEdit(a: AppointmentOut) {
  editId.value = a.id;
  kind.value = a.kind;
  startsAt.value = toLocalInput(a.starts_at);
  note.value = a.note ?? "";
  dialog.value = true;
}
async function save() {
  if (!startsAt.value) return;
  const body = { kind: kind.value, starts_at: fromLocalInput(startsAt.value), note: note.value.trim() || null };
  const ok = editId.value === null ? await store.addAppointment(body) : await store.updateAppointment(editId.value, body);
  if (ok) dialog.value = false;
}
const deleteBusy = ref(false);
async function confirmDelete() {
  if (!deleting.value || deleteBusy.value) return;
  deleteBusy.value = true;
  try {
    if (await store.removeAppointment(deleting.value.id)) deleting.value = null;
  } finally {
    deleteBusy.value = false;
  }
}
</script>

<template>
  <div>
    <v-btn prepend-icon="mdi-plus" variant="tonal" class="mb-3" data-test="appointment-add" @click="openNew">
      {{ t("detail.appointments.add") }}
    </v-btn>
    <div v-if="items.length === 0" class="text-medium-emphasis">{{ t("detail.appointments.empty") }}</div>
    <v-list v-else data-test="appointment-list">
      <v-list-item v-for="a in items" :key="a.id" :title="formatDateTime(a.starts_at, locale)" :subtitle="a.note ?? undefined">
        <template #prepend><v-chip size="small" label class="mr-3">{{ t(`appointmentKind.${a.kind}`) }}</v-chip></template>
        <template #append>
          <v-btn icon="mdi-pencil" variant="text" size="small" :aria-label="t('common.edit')" @click="openEdit(a)" />
          <v-btn icon="mdi-delete" variant="text" size="small" :aria-label="t('common.delete')" data-test="appointment-delete" @click="deleting = a" />
        </template>
      </v-list-item>
    </v-list>

    <v-dialog v-model="dialog" max-width="480">
      <v-card :title="editId === null ? t('detail.appointments.add') : t('detail.appointments.edit')">
        <v-card-text>
          <v-select v-model="kind" :label="t('detail.appointments.kind')" :items="APPOINTMENT_KINDS.map((k) => ({ value: k, title: t(`appointmentKind.${k}`) }))" />
          <v-text-field v-model="startsAt" type="datetime-local" :label="t('detail.appointments.startsAt')" />
          <v-textarea v-model="note" :label="t('detail.appointments.note')" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="dialog = false">{{ t("common.cancel") }}</v-btn>
          <v-btn color="primary" variant="flat" :disabled="!startsAt" data-test="appointment-save" @click="save">{{ t("common.save") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <ConfirmDialog
      :busy="deleteBusy"
      :model-value="deleting !== null"
      :title="t('detail.appointments.deleteTitle')"
      :text="t('detail.appointments.deleteText')"
      @update:model-value="deleting = null"
      @confirm="confirmDelete"
    />
  </div>
</template>
