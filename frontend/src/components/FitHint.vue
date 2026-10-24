<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useFitStore } from "@/stores/fit";

defineOptions({ inheritAttrs: false });
const { t } = useI18n();
const fit = useFitStore();
</script>

<template>
  <!-- Why fit evaluation is unavailable, with a link to the place that fixes it; nothing while ready or unknown. -->
  <div v-if="fit.statusLoaded && !fit.ready" v-bind="$attrs">
    <router-link v-if="!fit.status.profile" to="/me">{{ t("fit.needsProfile") }}</router-link>
    <router-link v-else to="/settings">{{ t("fit.needsLlm") }}</router-link>
  </div>
</template>
