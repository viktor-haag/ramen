<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { ContactOut } from "@/api/types";
import { useApplicationDetailStore } from "@/stores/applicationDetail";
import ConfirmDialog from "./ConfirmDialog.vue";

const { t } = useI18n();
const store = useApplicationDetailStore();
const items = computed(() => store.app?.contacts ?? []);

const dialog = ref(false);
const editId = ref<number | null>(null);
const form = ref({ name: "", role: "", email: "", phone: "" });
const deleting = ref<ContactOut | null>(null);

function openNew() {
  editId.value = null;
  form.value = { name: "", role: "", email: "", phone: "" };
  dialog.value = true;
}
function openEdit(c: ContactOut) {
  editId.value = c.id;
  form.value = { name: c.name, role: c.role ?? "", email: c.email ?? "", phone: c.phone ?? "" };
  dialog.value = true;
}
async function save() {
  const f = form.value;
  if (!f.name.trim()) return;
  const body = { name: f.name.trim(), role: f.role.trim() || null, email: f.email.trim() || null, phone: f.phone.trim() || null };
  const ok = editId.value === null ? await store.addContact(body) : await store.updateContact(editId.value, body);
  if (ok) dialog.value = false;
}
const deleteBusy = ref(false);
async function confirmDelete() {
  if (!deleting.value || deleteBusy.value) return;
  deleteBusy.value = true;
  try {
    if (await store.removeContact(deleting.value.id)) deleting.value = null;
  } finally {
    deleteBusy.value = false;
  }
}
</script>

<template>
  <div>
    <v-btn prepend-icon="mdi-plus" variant="tonal" class="mb-3" data-test="contact-add" @click="openNew">
      {{ t("detail.contacts.add") }}
    </v-btn>
    <div v-if="items.length === 0" class="text-medium-emphasis">{{ t("detail.contacts.empty") }}</div>
    <v-list v-else data-test="contact-list">
      <v-list-item v-for="c in items" :key="c.id" :title="c.name" :subtitle="[c.role, c.email, c.phone].filter(Boolean).join(' · ')">
        <template #append>
          <v-btn icon="mdi-pencil" variant="text" size="small" :aria-label="t('common.edit')" @click="openEdit(c)" />
          <v-btn icon="mdi-delete" variant="text" size="small" :aria-label="t('common.delete')" data-test="contact-delete" @click="deleting = c" />
        </template>
      </v-list-item>
    </v-list>

    <v-dialog v-model="dialog" max-width="480">
      <v-card :title="editId === null ? t('detail.contacts.add') : t('detail.contacts.edit')">
        <v-card-text>
          <v-text-field v-model="form.name" :label="t('detail.contacts.name')" />
          <v-text-field v-model="form.role" :label="t('detail.contacts.role')" />
          <v-text-field v-model="form.email" type="email" :label="t('detail.contacts.email')" />
          <v-text-field v-model="form.phone" type="tel" :label="t('detail.contacts.phone')" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="dialog = false">{{ t("common.cancel") }}</v-btn>
          <v-btn color="primary" variant="flat" :disabled="!form.name.trim()" data-test="contact-save" @click="save">{{ t("common.save") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <ConfirmDialog
      :busy="deleteBusy"
      :model-value="deleting !== null"
      :title="t('detail.contacts.deleteTitle')"
      :text="t('detail.contacts.deleteText', { name: deleting?.name ?? '' })"
      @update:model-value="deleting = null"
      @confirm="confirmDelete"
    />
  </div>
</template>
