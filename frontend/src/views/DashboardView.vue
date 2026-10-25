<script setup lang="ts">
import { onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { formatDateTime, relativeTime } from "@/domain/time";
import { useDashboardStore } from "@/stores/dashboard";

const { t, locale } = useI18n();
const store = useDashboardStore();
onMounted(() => store.load());

const failed = (status: string) => status === "error" || status === "timeout";
</script>

<template>
  <div class="d-flex align-center mb-4">
    <h1 class="text-h5 flex-grow-1">{{ t("dashboard.title") }}</h1>
    <v-btn icon="mdi-refresh" variant="text" :loading="store.loading" :aria-label="t('dashboard.reload')" @click="store.load()" />
  </div>
  <v-progress-linear v-if="store.loading && !store.data" indeterminate />
  <v-row v-if="store.data">
    <v-col cols="12" md="6">
      <v-card :title="t('dashboard.newPostings')" height="100%" data-test="dash-new">
        <v-card-text>
          <div class="text-h2 ramen-stat" data-test="dash-new-count">{{ store.data.new_count }}</div>
        </v-card-text>
        <v-card-actions>
          <v-btn to="/feed" variant="text" data-test="dash-new-link">{{ t("dashboard.newPostingsOpen") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-col>

    <v-col cols="12" md="6">
      <v-card :title="t('dashboard.upcoming')" height="100%" data-test="dash-upcoming">
        <v-list v-if="store.data.upcoming.length" lines="two">
          <v-list-item
            v-for="u in store.data.upcoming"
            :key="u.appointment.id"
            :to="`/applications/${u.application_id}`"
            :title="u.title || t('dashboard.untitled')"
            :subtitle="[formatDateTime(u.appointment.starts_at, locale), u.company, t(`appointmentKind.${u.appointment.kind}`)].filter(Boolean).join(' · ')"
          />
        </v-list>
        <v-card-text v-else class="text-medium-emphasis">{{ t("dashboard.noUpcoming") }}</v-card-text>
      </v-card>
    </v-col>

    <v-col cols="12" md="6">
      <v-card :title="t('dashboard.stale')" height="100%" data-test="dash-stale">
        <v-list v-if="store.data.stale.length" lines="two">
          <v-list-item
            v-for="a in store.data.stale"
            :key="a.id"
            :to="`/applications/${a.id}`"
            :title="a.posting.title || t('dashboard.untitled')"
            :subtitle="[a.posting.company, a.last_status_change_at ? relativeTime(a.last_status_change_at, locale) : ''].filter(Boolean).join(' · ')"
          />
        </v-list>
        <v-card-text v-else class="text-medium-emphasis">{{ t("dashboard.noStale") }}</v-card-text>
      </v-card>
    </v-col>

    <v-col cols="12" md="6">
      <v-card :title="t('dashboard.runs')" height="100%" data-test="dash-runs">
        <v-list v-if="store.data.recent_runs.length" lines="two">
          <v-list-item
            v-for="r in store.data.recent_runs"
            :key="r.id"
            :class="{ 'text-error': failed(r.status) }"
            :data-failed="failed(r.status)"
            :title="`${r.profile_name ?? '—'} · ${r.plugin}`"
          >
            <v-list-item-subtitle class="text-wrap">
              {{ relativeTime(r.started_at, locale) }} ·
              <template v-if="failed(r.status)">
                <span data-test="dash-run-error">{{ r.error || t("dashboard.noError") }}</span>
              </template>
              <template v-else>{{ t("dashboard.runResult", { n: r.new_count }) }}</template>
            </v-list-item-subtitle>
          </v-list-item>
        </v-list>
        <v-card-text v-else class="text-medium-emphasis">{{ t("dashboard.noRuns") }}</v-card-text>
        <v-card-actions v-if="store.data.older_failed_count" data-test="dash-older-failed">
          <v-icon icon="mdi-alert-circle-outline" color="error" class="ms-2" />
          <span class="text-error text-body-2 ms-1">{{ t("dashboard.olderFailed", { n: store.data.older_failed_count }, store.data.older_failed_count) }}</span>
          <v-spacer />
          <v-btn to="/profiles" variant="text" size="small">{{ t("dashboard.toHistory") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-col>
  </v-row>
</template>
