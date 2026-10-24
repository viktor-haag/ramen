<script setup lang="ts">
import { useI18n } from "vue-i18n";
import logo from "@/assets/ramen-logo.svg?no-inline";

const { t } = useI18n();
</script>

<template>
  <span class="ramen-brand">
    <img :src="logo" alt="" class="ramen-brand__logo" />
    <span class="ramen-brand__name d-none d-sm-inline" data-test="brand-name">{{ t("app.title") }}</span>
    <span class="ramen-brand__tagline d-none d-sm-inline" data-test="brand-tagline">{{ t("app.tagline") }}</span>
  </span>
</template>
