<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useThemePreference, type ThemePref } from "@/composables/themePreference";

const { t } = useI18n();
const { pref, cycle } = useThemePreference();

const ICONS: Record<ThemePref, string> = {
  auto: "mdi-theme-light-dark",
  light: "mdi-white-balance-sunny",
  dark: "mdi-weather-night",
};
const label = computed(() => t("theme.label", { mode: t(`theme.${pref.value}`) }));
</script>

<template>
  <v-btn
    data-test="theme-switch"
    :icon="ICONS[pref]"
    variant="text"
    density="comfortable"
    :aria-label="label"
    :title="label"
    @click="cycle"
  />
</template>
