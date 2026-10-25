<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { PluginOut, ProfileIn, ProfileOut } from "@/api/types";
import { MAX_KEYWORDS, MAX_KEYWORD_LENGTH, MAX_LOCATIONS, MAX_LOCATION_LENGTH, SCHEDULE_HOURS, isUsableSearch, normalizeKeywords, splitKeywords, toPayload, type ProfileForm } from "@/stores/profiles";

const props = withDefaults(defineProps<{ modelValue: boolean; profile: ProfileOut | null; plugins: PluginOut[]; busy?: boolean; pluginsLoaded?: boolean }>(), { pluginsLoaded: true });
const emit = defineEmits<{ "update:modelValue": [boolean]; save: [ProfileIn] }>();
const { t } = useI18n();

const form = reactive<ProfileForm>(blank());
const checked = ref<string[]>([]);

function blank(): ProfileForm {
  return { name: "", keywords: [], locations: [], radius_km: null, employment_type: null, remote: false, enabled: true, schedule_hours: null };
}

const searchPlugins = computed(() => props.plugins.filter((p) => p.capabilities.includes("search") || p.error !== null));
const usable = computed(() => searchPlugins.value.filter(isUsableSearch).map((p) => p.name));

function reset() {
  const p = props.profile;
  Object.assign(form, p
    ? {
        name: p.name, keywords: [...p.keywords], locations: [...(p.locations ?? [])], radius_km: p.radius_km ?? null,
        employment_type: p.employment_type ?? null, remote: p.remote === true, enabled: p.enabled, schedule_hours: p.schedule_hours ?? null,
      }
    : blank());
  checked.value = p && p.plugins.length > 0 ? usable.value.filter((n) => p.plugins.includes(n)) : [...usable.value];
}
watch(() => props.modelValue, (open) => open && reset(), { immediate: true });
watch(usable, () => props.modelValue && reset());

const scheduleItems = SCHEDULE_HOURS.map((h) => ({ value: h, title: h === null ? t("profiles.schedule.off") : t("profiles.schedule.every", { n: h }) }));
const employmentItems = computed(() => [
  { value: null, title: t("profiles.fields.anyHours") },
  { value: "fulltime", title: t("feed.filters.employment.fulltime") },
  { value: "parttime", title: t("feed.filters.employment.parttime") },
]);

const keywordSearch = ref("");
const keywordError = computed(() => {
  if (form.keywords.length > MAX_KEYWORDS) return t("profiles.keywordsTooMany", { max: MAX_KEYWORDS });
  if (form.keywords.some((k) => k.length > MAX_KEYWORD_LENGTH)) return t("profiles.keywordsTooLong", { max: MAX_KEYWORD_LENGTH });
  return null;
});

function setKeywords(v: string[]) {
  form.keywords = normalizeKeywords(v.flatMap((k) => splitKeywords(k)));
}
/** Typed or pasted text containing commas becomes chips right away. */
function onSearch(text: string) {
  keywordSearch.value = text;
  if (!text.includes(",")) return;
  const parts = text.split(",");
  const rest = parts.pop() ?? "";
  setKeywords([...form.keywords, ...parts]);
  keywordSearch.value = rest;
}

const locationSearch = ref("");
const locationError = computed(() => {
  if (form.locations.length > MAX_LOCATIONS) return t("profiles.locationsTooMany", { max: MAX_LOCATIONS });
  if (form.locations.some((c) => c.length > MAX_LOCATION_LENGTH)) return t("profiles.locationsTooLong", { max: MAX_LOCATION_LENGTH });
  return null;
});

function setLocations(v: string[]) {
  form.locations = normalizeKeywords(v.flatMap((c) => splitKeywords(c)));
}
/** Typed or pasted text containing commas becomes city chips right away. */
function onLocationSearch(text: string) {
  locationSearch.value = text;
  if (!text.includes(",")) return;
  const parts = text.split(",");
  const rest = parts.pop() ?? "";
  setLocations([...form.locations, ...parts]);
  locationSearch.value = rest;
}

const valid = computed(() => props.pluginsLoaded && form.name.trim() !== "" && form.keywords.length > 0 && keywordError.value === null && locationError.value === null && (usable.value.length === 0 || checked.value.length > 0));

function submit() {
  // Text typed but not yet committed (no Enter/comma) still counts.
  if (keywordSearch.value.trim()) {
    setKeywords([...form.keywords, keywordSearch.value]);
    keywordSearch.value = "";
  }
  if (locationSearch.value.trim()) {
    setLocations([...form.locations, locationSearch.value]);
    locationSearch.value = "";
  }
  if (valid.value) emit("save", toPayload(form, checked.value, props.plugins));
}
</script>

<template>
  <v-dialog :model-value="modelValue" max-width="640" scrollable @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <v-card :title="profile ? t('profiles.dialog.edit') : t('profiles.dialog.new')">
      <v-card-text>
        <v-text-field v-model="form.name" :label="t('profiles.fields.name')" data-test="pf-name" />
        <v-combobox
          :model-value="form.keywords"
          :search="keywordSearch"
          multiple
          chips
          closable-chips
          :delimiters="[',']"
          :items="[]"
          :hide-no-data="true"
          :label="t('profiles.fields.keywords')"
          :hint="t('profiles.keywordsHint')"
          data-test="pf-keywords"
          @update:model-value="setKeywords"
          @update:search="onSearch"
        />
        <div v-if="keywordError" class="text-error text-caption mb-2" data-test="pf-keywords-error">{{ keywordError }}</div>
        <v-row dense>
          <v-col cols="12" sm="8">
            <v-combobox
              :model-value="form.locations"
              :search="locationSearch"
              multiple
              chips
              closable-chips
              :delimiters="[',']"
              :items="[]"
              :hide-no-data="true"
              :label="t('profiles.fields.locations')"
              :hint="t('profiles.locationsHint')"
              data-test="pf-locations"
              @update:model-value="setLocations"
              @update:search="onLocationSearch"
            />
            <div v-if="locationError" class="text-error text-caption mb-2" data-test="pf-locations-error">{{ locationError }}</div>
          </v-col>
          <v-col cols="12" sm="4">
            <v-text-field v-model.number="form.radius_km" type="number" min="0" :label="t('profiles.fields.radius')" :disabled="form.locations.length === 0" data-test="pf-radius" />
          </v-col>
        </v-row>
        <v-select v-model="form.employment_type" :items="employmentItems" :label="t('profiles.fields.employmentType')" data-test="pf-employment" />
        <v-switch v-model="form.remote" :label="t('profiles.fields.remote')" color="primary" density="comfortable" />
        <v-select v-model="form.schedule_hours" :items="scheduleItems" :label="t('profiles.fields.schedule')" data-test="pf-schedule" />
        <v-switch v-model="form.enabled" :label="t('profiles.fields.enabled')" color="primary" density="comfortable" />

        <div class="text-subtitle-2 mt-2">{{ t("profiles.fields.extractors") }}</div>
        <div v-if="!pluginsLoaded" class="text-error text-caption" data-test="pf-plugins-failed">{{ t("profiles.pluginsFailed") }}</div>
        <div v-else-if="searchPlugins.length === 0" class="text-medium-emphasis">{{ t("profiles.noExtractors") }}</div>
        <div v-for="p in searchPlugins" :key="p.name">
          <v-checkbox
            v-model="checked"
            :value="p.name"
            :label="p.display_name"
            :disabled="!isUsableSearch(p)"
            :hint="p.error !== null ? t('profiles.notLoadable') : !p.enabled ? t('profiles.disabledInSettings') : undefined"
            :persistent-hint="!isUsableSearch(p)"
            density="compact"
            :data-test="`pf-plugin-${p.name}`"
          />
        </div>
        <div v-if="usable.length > 0 && checked.length === 0" class="text-error text-caption">{{ t("profiles.pickOne") }}</div>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn data-test="pf-cancel" @click="emit('update:modelValue', false)">{{ t("common.cancel") }}</v-btn>
        <v-btn color="primary" variant="flat" :disabled="!valid || busy" :loading="busy" data-test="pf-save" @click="submit">{{ t("common.save") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
