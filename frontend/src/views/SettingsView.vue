<script setup lang="ts">
import { onMounted, reactive } from "vue";
import { useI18n } from "vue-i18n";
import { useDisplay } from "vuetify";
import type { PluginOut } from "@/api/types";
import AboutCard from "@/components/AboutCard.vue";
import AiSettings from "@/components/AiSettings.vue";
import DangerZone from "@/components/DangerZone.vue";
import SchemaForm from "@/components/SchemaForm.vue";
import { setLocale, type Locale } from "@/i18n";
import { useNotifyStore } from "@/stores/notify";
import { useSettingsPluginsStore } from "@/stores/plugins";

const { t, locale } = useI18n();
const { xs } = useDisplay();
const store = useSettingsPluginsStore();

const languages = [
  { value: "en", title: "English" },
  { value: "de", title: "Deutsch" },
];

interface Draft {
  enabled: boolean;
  settings: Record<string, unknown>;
  errors: Record<string, string>;
  saving: boolean;
  toggling: boolean;
}
const drafts = reactive<Record<string, Draft>>({});

function syncDraft(p: PluginOut) {
  drafts[p.name] = { enabled: p.enabled, settings: { ...p.settings }, errors: {}, saving: false, toggling: false };
}
onMounted(async () => {
  await store.load();
  store.items.forEach(syncDraft);
});

async function save(p: PluginOut) {
  const d = drafts[p.name];
  d.saving = true;
  d.errors = {};
  const res = await store.save(p.name, { enabled: d.enabled, settings: d.settings });
  d.saving = false;
  if (res.ok) {
    const fresh = store.items.find((x) => x.name === p.name);
    if (fresh) syncDraft(fresh);
    useNotifyStore().show(t("settings.saved"));
  } else d.errors = res.errors;
}

/** Header switch: persist the enabled flag right away; unsaved draft settings are neither saved nor lost. */
async function toggleEnabled(p: PluginOut, value: boolean | null) {
  const d = drafts[p.name];
  const enabled = value === true;
  const previous = d.enabled;
  d.enabled = enabled; // optimistic, so the switch can visibly revert on failure
  d.toggling = true;
  d.errors = {};
  const res = await store.save(p.name, { enabled, settings: p.settings });
  d.toggling = false;
  if (res.ok) useNotifyStore().show(t("settings.saved"));
  else {
    d.enabled = previous;
    d.errors = res.errors;
  }
}
</script>

<template>
  <h1 class="text-h5 mb-4">{{ t("settings.title") }}</h1>

  <v-card class="mb-6" :title="t('settings.language')">
    <v-card-text>
      <v-select
        :model-value="locale"
        :items="languages"
        :label="t('nav.language')"
        data-test="language-select"
        @update:model-value="(v: string) => setLocale(v as Locale)"
      />
    </v-card-text>
  </v-card>

  <h2 class="text-h6 mb-2">{{ t("settings.plugins") }}</h2>
  <v-expansion-panels multiple class="mb-6">
    <v-expansion-panel v-for="p in store.items" :key="p.name" :data-test="`plugin-${p.name}`">
      <v-expansion-panel-title>
        <div class="d-flex align-center ga-2 flex-grow-1">
          <span class="text-subtitle-1">{{ p.display_name }}</span>
          <v-chip v-for="c in p.capabilities" :key="c" size="small" label class="d-none d-sm-inline-flex">{{ t(`settings.capability.${c}`) }}</v-chip>
          <v-chip v-if="p.error !== null" size="small" label color="error" data-test="plugin-error-chip">{{ t("settings.notLoadable") }}</v-chip>
          <v-spacer />
          <div v-if="p.error === null && drafts[p.name]" class="mr-2" @click.stop @keydown.stop @keyup.stop>
            <v-switch
              :model-value="drafts[p.name].enabled"
              :label="xs ? undefined : t('settings.enabled')"
              :aria-label="t('settings.enabled')"
              :loading="drafts[p.name].toggling"
              :disabled="drafts[p.name].toggling || drafts[p.name].saving"
              color="primary"
              density="compact"
              hide-details
              data-test="plugin-enabled"
              @update:model-value="(v) => toggleEnabled(p, v)"
            />
          </div>
        </div>
      </v-expansion-panel-title>
      <v-expansion-panel-text>
        <v-alert v-if="p.error !== null" type="error" density="compact" data-test="plugin-error">
          <strong>{{ t("settings.notLoadable") }}</strong>: {{ p.error }}
        </v-alert>
        <template v-else-if="drafts[p.name]">
          <SchemaForm
            v-if="p.settings_schema"
            v-model="drafts[p.name].settings"
            :schema="p.settings_schema"
            :errors="drafts[p.name].errors"
          />
          <div v-else class="text-medium-emphasis">{{ t("settings.noSettings") }}</div>
          <div class="d-flex mt-2">
            <v-spacer />
            <v-btn color="primary" variant="flat" :loading="drafts[p.name].saving" :disabled="drafts[p.name].toggling" data-test="plugin-save" @click="save(p)">{{ t("common.save") }}</v-btn>
          </div>
        </template>
      </v-expansion-panel-text>
    </v-expansion-panel>
  </v-expansion-panels>

  <AiSettings />

  <AboutCard />

  <DangerZone />
</template>
