<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import type { CoverLetterOut } from "@/api/types";
import CoverLetterDialog from "@/components/CoverLetterDialog.vue";
import { useCoverLetterStore } from "@/stores/coverLetter";

const props = defineProps<{ applicationId: number }>();
const { t } = useI18n();
const router = useRouter();
const store = useCoverLetterStore();

// The store keeps the previous application's letter while the next one loads: only show our own.
const letter = computed<CoverLetterOut | null>(() => (store.letter?.application_id === props.applicationId ? store.letter : null));
const busy = computed(() => letter.value !== null && letter.value.status !== "idle");
const dialog = ref(false);

watch(() => props.applicationId, (id) => void store.load(id), { immediate: true });
onBeforeUnmount(() => store.stopPolling());

function open() {
  void router.push({ name: "cover-letter", params: { id: String(props.applicationId) } });
}
</script>

<template>
  <section data-test="cover-letter-section">
    <div class="d-flex align-center ga-2">
      <h3 class="text-subtitle-1 flex-grow-1">{{ t("coverLetter.section") }}</h3>
      <v-btn v-if="letter" size="small" variant="text" :disabled="busy" data-test="cl-regenerate" @click="dialog = true">
        {{ t("coverLetter.dialog.regenerate") }}
      </v-btn>
      <v-btn v-if="letter" size="small" variant="tonal" prepend-icon="mdi-open-in-new" data-test="cl-open" @click="open">{{ t("coverLetter.open") }}</v-btn>
      <v-btn v-else size="small" variant="tonal" prepend-icon="mdi-text-box-edit-outline" :loading="store.loading" data-test="cl-create" @click="dialog = true">
        {{ t("coverLetter.create") }}
      </v-btn>
    </div>
    <div v-if="letter" class="text-body-2 text-medium-emphasis mt-1" data-test="cl-state">
      {{ busy ? t(`coverLetter.status.${letter.status}`) : t("coverLetter.exists") }}
    </div>
    <div v-else class="text-body-2 text-medium-emphasis mt-1" data-test="cl-none">{{ t("coverLetter.none") }}</div>
    <CoverLetterDialog v-if="dialog" v-model="dialog" :application-id="applicationId" :existing="letter" />
  </section>
</template>
