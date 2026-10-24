<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "@/api/client";
import type { FeedSort, FitFilterValue, PluginOut, ProfileOut, TriageStatus } from "@/api/types";
import { TRIAGE_STATUSES } from "@/api/types";
import { useFeedStore, type FoundRange } from "@/stores/feed";
import { useNotifyStore } from "@/stores/notify";

const { t } = useI18n();
const feed = useFeedStore();
const plugins = ref<PluginOut[]>([]);
const profiles = ref<ProfileOut[]>([]);
const q = ref<string | null>(feed.filter.q ?? "");
const location = ref<string | null>(feed.filter.location ?? "");
let timer: ReturnType<typeof setTimeout> | undefined;

const ranges: FoundRange[] = ["today", "7d", "30d", "all"];
const radii = [10, 25, 50, 100];
const employmentTypes = ["fulltime", "parttime"];

const rangeItems = computed(() => ranges.map((r) => ({ value: r, title: t(`feed.filters.range.${r}`) })));
const sourceItems = computed(() => [
  ...plugins.value.map((p) => ({ value: p.name, title: p.display_name })),
  { value: "manual", title: t("feed.filters.manual") },
]);
const profileItems = computed(() => profiles.value.map((p) => ({ value: p.id, title: p.name })));
const fitItems = computed(() => [
  { value: "good", title: t("fit.rating.good") },
  { value: "moderate", title: t("fit.rating.moderate") },
  { value: "poor", title: t("fit.rating.poor") },
  { value: "none", title: t("feed.filters.fitNone") },
]);
const sortItems = computed(() =>
  (["first_seen_at", "published_at", "fit"] as const).map((s) => ({ value: s, title: t(`feed.filters.sortOptions.${s}`) })),
);
const employmentItems = computed(() => employmentTypes.map((e) => ({ value: e, title: t(`feed.filters.employment.${e}`) })));

function apply() {
  void feed.reset();
}

function setNow<K extends keyof typeof feed.filter>(key: K, value: (typeof feed.filter)[K]) {
  feed.filter[key] = value;
  apply();
}

/** Text inputs: write to the filter after 300 ms of inactivity. */
function typed() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    // Vuetify's clearable sets the model to null.
    feed.filter.q = (q.value ?? "").trim() || null;
    feed.filter.location = (location.value ?? "").trim() || null;
    if (!feed.filter.location) feed.filter.radius_km = null;
    apply();
  }, 300);
}

function setTriage(value: TriageStatus[] | undefined) {
  setNow("triage", value ?? []);
}

onMounted(async () => {
  try {
    [plugins.value, profiles.value] = await Promise.all([
      api.get<PluginOut[]>("/plugins"),
      api.get<ProfileOut[]>("/profiles"),
    ]);
  } catch (e) {
    useNotifyStore().error(e);
  }
});
onUnmounted(() => clearTimeout(timer));
</script>

<template>
  <v-row dense class="align-center">
    <v-col cols="12" md="6" lg="3">
      <v-text-field
        v-model="q"
        :label="t('feed.filters.search')"
        prepend-inner-icon="mdi-magnify"
        clearable
        hide-details
        density="compact"
        data-test="filter-q"
        @update:model-value="typed"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-select
        :model-value="feed.foundRange"
        :items="rangeItems"
        :label="t('feed.filters.found')"
        hide-details
        density="compact"
        @update:model-value="(v: FoundRange) => { feed.foundRange = v; apply(); }"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-text-field
        v-model="location"
        :label="t('feed.filters.location')"
        data-test="filter-location"
        clearable
        hide-details
        density="compact"
        @update:model-value="typed"
      />
    </v-col>
    <v-col cols="6" md="3" lg="1">
      <v-select
        :model-value="feed.filter.radius_km ?? null"
        :items="radii"
        :label="t('feed.filters.radius')"
        :disabled="!location"
        clearable
        hide-details
        density="compact"
        @update:model-value="(v: number | null) => setNow('radius_km', v)"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-select
        :model-value="feed.filter.source ?? []"
        :items="sourceItems"
        :label="t('feed.filters.source')"
        multiple
        chips
        closable-chips
        hide-details
        density="compact"
        @update:model-value="(v: string[]) => setNow('source', v)"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-select
        :model-value="feed.filter.profile_id ?? null"
        :items="profileItems"
        :label="t('feed.filters.profile')"
        clearable
        hide-details
        density="compact"
        @update:model-value="(v: number | null) => setNow('profile_id', v)"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-select
        :model-value="feed.filter.employment_type ?? null"
        :items="employmentItems"
        :label="t('feed.filters.employmentType')"
        clearable
        hide-details
        density="compact"
        @update:model-value="(v: string | null) => setNow('employment_type', v)"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-switch
        :model-value="feed.filter.remote === true"
        :label="t('feed.filters.remote')"
        hide-details
        density="compact"
        color="primary"
        @update:model-value="(v: boolean | null) => setNow('remote', v ? true : null)"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-select
        :model-value="feed.filter.fit ?? []"
        :items="fitItems"
        :label="t('feed.filters.fit')"
        multiple
        chips
        closable-chips
        hide-details
        density="compact"
        data-test="filter-fit"
        @update:model-value="(v: FitFilterValue[]) => setNow('fit', v)"
      />
    </v-col>
    <v-col cols="6" md="3" lg="2">
      <v-select
        :model-value="feed.filter.sort ?? 'first_seen_at'"
        :items="sortItems"
        :label="t('feed.filters.sort')"
        hide-details
        density="compact"
        data-test="filter-sort"
        @update:model-value="(v: FeedSort) => setNow('sort', v)"
      />
    </v-col>
    <v-col cols="12" lg="6">
      <v-chip-group
        :model-value="feed.filter.triage ?? []"
        multiple
        filter
        :aria-label="t('feed.filters.triage')"
        data-test="filter-triage"
        @update:model-value="setTriage"
      >
        <v-chip v-for="s in TRIAGE_STATUSES" :key="s" :value="s" :data-test="`triage-${s}`">{{ t(`triage.${s}`) }}</v-chip>
      </v-chip-group>
    </v-col>
  </v-row>
</template>
