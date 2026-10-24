<script setup lang="ts">
import { onMounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import ApplicationBoard from "@/components/ApplicationBoard.vue";
import ApplicationTable from "@/components/ApplicationTable.vue";
import { useApplicationsStore } from "@/stores/applications";

const { t } = useI18n();
const store = useApplicationsStore();

onMounted(() => void store.load());
watch(() => store.showTerminal, () => void store.load());
</script>

<template>
  <div class="d-flex align-center flex-wrap ga-4 mb-4">
    <h1 class="text-h5">{{ t("applications.title") }}</h1>
    <v-spacer />
    <v-switch v-model="store.showTerminal" :label="t('applications.showFinished')" hide-details density="compact" color="primary" />
    <v-switch v-model="store.hideSaved" :label="t('applications.hideSaved')" hide-details density="compact" color="primary" />
    <v-btn-toggle v-model="store.view" mandatory density="comfortable" variant="outlined" divided>
      <v-btn value="board" prepend-icon="mdi-view-column">{{ t("applications.board") }}</v-btn>
      <v-btn value="table" prepend-icon="mdi-table">{{ t("applications.table") }}</v-btn>
    </v-btn-toggle>
  </div>
  <ApplicationBoard v-if="store.view === 'board'" />
  <ApplicationTable v-else />
</template>
