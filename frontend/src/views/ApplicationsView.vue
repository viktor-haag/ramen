<script setup lang="ts">
import { onMounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useDisplay } from "vuetify";
import ApplicationBoard from "@/components/ApplicationBoard.vue";
import ApplicationTable from "@/components/ApplicationTable.vue";
import { useApplicationsStore } from "@/stores/applications";

const { t } = useI18n();
const store = useApplicationsStore();
const { xs } = useDisplay();

onMounted(() => void store.load());
watch(() => store.showTerminal, () => void store.load());
</script>

<template>
  <div class="d-flex align-center flex-wrap ga-4 mb-4">
    <h1 class="text-h5">{{ t("applications.title") }}</h1>
    <v-spacer />
    <v-switch v-model="store.showTerminal" :label="t('applications.showFinished')" hide-details density="compact" color="primary" />
    <v-switch v-model="store.hideSaved" :label="t('applications.hideSaved')" hide-details density="compact" color="primary" />
    <v-menu>
      <template #activator="{ props }">
        <v-btn
          v-bind="props"
          data-test="apps-export"
          variant="outlined"
          prepend-icon="mdi-download"
          :icon="xs ? 'mdi-download' : undefined"
          :text="xs ? undefined : t('applications.export.button')"
          :aria-label="t('applications.export.button')"
        />
      </template>
      <v-list density="compact">
        <v-list-item data-test="apps-export-csv" tag="a" :href="store.exportUrl('csv')" download :title="t('applications.export.csv')" prepend-icon="mdi-file-delimited-outline" />
        <v-list-item data-test="apps-export-xlsx" tag="a" :href="store.exportUrl('xlsx')" download :title="t('applications.export.xlsx')" prepend-icon="mdi-file-excel-outline" />
      </v-list>
    </v-menu>
    <v-btn-toggle v-model="store.view" mandatory density="comfortable" variant="outlined" divided>
      <v-btn value="board" prepend-icon="mdi-view-column">{{ t("applications.board") }}</v-btn>
      <v-btn value="table" prepend-icon="mdi-table">{{ t("applications.table") }}</v-btn>
    </v-btn-toggle>
  </div>
  <ApplicationBoard v-if="store.view === 'board'" />
  <ApplicationTable v-else />
</template>
