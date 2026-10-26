<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { AppStatus, ApplicationPatch } from "@/api/types";
import AppointmentList from "@/components/AppointmentList.vue";
import AttachmentList from "@/components/AttachmentList.vue";
import ContactList from "@/components/ContactList.vue";
import CoverLetterSection from "@/components/CoverLetterSection.vue";
import FitSection from "@/components/FitSection.vue";
import StatusHistory from "@/components/StatusHistory.vue";
import { ACTIVE_STATUSES, allowedTargets } from "@/domain/status";
import { useApplicationDetailStore } from "@/stores/applicationDetail";

const props = defineProps<{ id: string }>();
const { t } = useI18n();
const store = useApplicationDetailStore();

const app = computed(() => store.app);
const posting = computed(() => app.value?.posting ?? null);
// Only http(s) links are rendered; the URL comes from third-party sites.
const safeUrl = computed(() => (posting.value?.url && /^https?:\/\//i.test(posting.value.url) ? posting.value.url : null));
const targets = computed(() => (app.value ? allowedTargets(app.value.status) : []));
const finished = computed(() => !!app.value && !ACTIVE_STATUSES.includes(app.value.status));

watch(
  () => props.id,
  (id) => void store.load(Number(id)),
  { immediate: true },
);

// --- status change / reopen (both go through one dialog with an optional comment) ---
const dialog = ref<null | { mode: "status" | "reopen"; to: AppStatus }>(null);
const comment = ref("");
const busy = ref(false);

function askStatus(to: AppStatus) {
  comment.value = "";
  dialog.value = { mode: "status", to };
}
function askReopen() {
  comment.value = "";
  dialog.value = { mode: "reopen", to: ACTIVE_STATUSES[0]! };
}
async function confirmDialog() {
  const d = dialog.value;
  if (!d) return;
  busy.value = true;
  try {
    const ok = d.mode === "reopen" ? await store.reopen(d.to, comment.value.trim() || null) : await store.changeStatus(d.to, comment.value.trim() || null);
    if (ok) dialog.value = null;
  } finally {
    busy.value = false;
  }
}

// --- autosave on blur, only when changed ---
type Field = "notes" | "salary_expectation" | "channel";
const local = ref<Record<Field, string>>({ notes: "", salary_expectation: "", channel: "" });
const hint = ref<Record<Field, "saved" | "error" | null>>({ notes: null, salary_expectation: null, channel: null });
const hintTimers: Partial<Record<Field, ReturnType<typeof setTimeout>>> = {};
const norm = (v: string | null | undefined) => (v == null || v.trim() === "" ? null : v);

for (const f of ["notes", "salary_expectation", "channel"] as Field[]) {
  // One watcher per field: saving one field must not overwrite another field that is being edited.
  // The local text is replaced by the server value only for another application or when the user
  // has not typed anything newer than the last known server value.
  watch(
    () => [app.value?.id, app.value?.[f] ?? ""] as const,
    ([id, v], old) => {
      if (!old || id !== old[0] || local.value[f] === old[1]) local.value[f] = v;
    },
    { immediate: true },
  );
}

function setHint(f: Field, h: "saved" | "error" | null) {
  clearTimeout(hintTimers[f]);
  hint.value[f] = h;
  if (h === "saved") hintTimers[f] = setTimeout(() => (hint.value[f] = null), 2000);
}
function hintText(f: Field) {
  return hint.value[f] === "saved" ? t("detail.saved") : hint.value[f] === "error" ? t("detail.unsaved") : undefined;
}

async function autosave(f: Field) {
  const sent = local.value[f];
  if (norm(sent) === norm(app.value?.[f])) return;
  const body: ApplicationPatch = { [f]: norm(sent) };
  // On failure the typed text stays (retried on the next blur); a late response never touches newer typing.
  setHint(f, (await store.patch(body)) ? "saved" : "error");
}

const tab = ref("posting");
</script>

<template>
  <div v-if="app && posting" data-test="application-detail">
    <v-btn variant="text" prepend-icon="mdi-arrow-left" :to="{ name: 'applications' }" class="mb-2">{{ t("detail.back") }}</v-btn>

    <div class="d-flex align-start flex-wrap ga-4 mb-4">
      <div class="flex-grow-1">
        <h1 class="text-h5">{{ posting.title || t("applications.untitled") }}</h1>
        <div class="text-subtitle-1">{{ posting.company || t("applications.noCompany") }}</div>
        <div class="text-body-2 text-medium-emphasis">{{ posting.location }}</div>
        <v-btn
          v-if="safeUrl"
          size="small"
          variant="text"
          prepend-icon="mdi-open-in-new"
          :href="safeUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="px-0"
        >
          {{ t("detail.openSource") }}
        </v-btn>
      </div>
      <div class="d-flex align-center ga-3">
        <v-chip label data-test="current-status">{{ t(`status.${app.status}`) }}</v-chip>
        <v-btn v-if="finished" color="primary" variant="tonal" prepend-icon="mdi-restore" data-test="reopen" @click="askReopen">
          {{ t("detail.reopen") }}
        </v-btn>
        <v-select
          v-else
          :model-value="null as AppStatus | null"
          :label="t('detail.changeStatus')"
          :items="targets.map((s) => ({ value: s, title: t(`status.${s}`) }))"
          density="comfortable"
          hide-details
          style="min-width: 200px"
          data-test="status-select"
          @update:model-value="(s: AppStatus | null) => s && askStatus(s)"
        />
      </div>
    </div>

    <v-row class="mb-2">
      <v-col cols="12" md="6">
        <v-text-field
          v-model="local.salary_expectation"
          :label="t('detail.fields.salary')"
          :hint="hintText('salary_expectation')"
          :error="hint.salary_expectation === 'error'"
          persistent-hint
          data-test="field-salary"
          @blur="autosave('salary_expectation')"
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-text-field
          v-model="local.channel"
          :label="t('detail.fields.channel')"
          :hint="hintText('channel')"
          :error="hint.channel === 'error'"
          persistent-hint
          data-test="field-channel"
          @blur="autosave('channel')"
        />
      </v-col>
    </v-row>

    <v-tabs v-model="tab" show-arrows>
      <v-tab value="posting">{{ t("detail.tabs.posting") }}</v-tab>
      <v-tab value="history">{{ t("detail.tabs.history") }}</v-tab>
      <v-tab value="appointments">{{ t("detail.tabs.appointments") }} ({{ app.appointments.length }})</v-tab>
      <v-tab value="contacts">{{ t("detail.tabs.contacts") }} ({{ app.contacts.length }})</v-tab>
      <v-tab value="attachments">{{ t("detail.tabs.attachments") }} ({{ app.attachments.length }})</v-tab>
      <v-tab value="notes">{{ t("detail.tabs.notes") }}</v-tab>
    </v-tabs>
    <v-divider />
    <v-tabs-window v-model="tab" class="pt-4">
      <v-tabs-window-item value="posting">
        <FitSection :key="posting.id" :posting-id="posting.id" :fit="posting.fit" class="mb-4" />
        <CoverLetterSection :application-id="app.id" class="mb-4" />
        <div v-if="posting.description" class="description" data-test="posting-description">{{ posting.description }}</div>
        <div v-else class="text-medium-emphasis">{{ t("detail.noDescription") }}</div>
      </v-tabs-window-item>
      <v-tabs-window-item value="history"><StatusHistory :changes="app.status_changes" /></v-tabs-window-item>
      <v-tabs-window-item value="appointments"><AppointmentList /></v-tabs-window-item>
      <v-tabs-window-item value="contacts"><ContactList /></v-tabs-window-item>
      <v-tabs-window-item value="attachments"><AttachmentList /></v-tabs-window-item>
      <v-tabs-window-item value="notes">
        <v-textarea
          v-model="local.notes"
          :label="t('detail.fields.notes')"
          :hint="hintText('notes')"
          :error="hint.notes === 'error'"
          persistent-hint
          rows="8"
          auto-grow
          data-test="field-notes"
          @blur="autosave('notes')"
        />
      </v-tabs-window-item>
    </v-tabs-window>

    <v-dialog :model-value="dialog !== null" max-width="440" @update:model-value="dialog = null">
      <v-card v-if="dialog" :title="dialog.mode === 'reopen' ? t('detail.reopen') : t('detail.changeStatus')">
        <v-card-text>
          <v-select
            v-if="dialog.mode === 'reopen'"
            v-model="dialog.to"
            :label="t('detail.reopenTo')"
            :items="ACTIVE_STATUSES.map((s) => ({ value: s, title: t(`status.${s}`) }))"
            data-test="reopen-target"
          />
          <div v-else class="mb-3">{{ t(`status.${app.status}`) }} → {{ t(`status.${dialog.to}`) }}</div>
          <v-textarea v-model="comment" :label="t('detail.comment')" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="dialog = null">{{ t("common.cancel") }}</v-btn>
          <v-btn color="primary" variant="flat" :loading="busy" data-test="dialog-confirm" @click="confirmDialog">
            {{ dialog.mode === "reopen" ? t("detail.reopenConfirm") : t("common.save") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
  <v-progress-linear v-else-if="store.loading" indeterminate />
</template>

<style scoped>
.description {
  white-space: pre-line;
  overflow-wrap: anywhere;
}
</style>
