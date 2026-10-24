<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { setLocale, type Locale } from "@/i18n";
import AddPostingDialog from "@/components/AddPostingDialog.vue";
import ThemeSwitch from "@/components/ThemeSwitch.vue";
import RamenBrand from "@/components/RamenBrand.vue";
import NotifySnackbar from "@/components/NotifySnackbar.vue";

const { t, locale } = useI18n();
const drawer = ref(true);
const addOpen = ref(false);

const items = [
  { to: "/", icon: "mdi-home", key: "nav.dashboard" },
  { to: "/feed", icon: "mdi-inbox-full", key: "nav.feed" },
  { to: "/applications", icon: "mdi-briefcase-check", key: "nav.applications" },
  { to: "/profiles", icon: "mdi-magnify", key: "nav.profiles" },
  { to: "/me", icon: "mdi-account-circle", key: "nav.me" },
  { to: "/settings", icon: "mdi-cog", key: "nav.settings" },
];
const locales: Locale[] = ["en", "de"];
</script>

<template>
  <v-app>
    <v-navigation-drawer v-model="drawer">
      <v-list nav>
        <v-list-item
          v-for="item in items"
          :key="item.to"
          :to="item.to"
          :prepend-icon="item.icon"
          :title="t(item.key)"
          exact
        />
      </v-list>
    </v-navigation-drawer>

    <v-app-bar flat border>
      <v-app-bar-nav-icon @click="drawer = !drawer" />
      <v-app-bar-title class="ramen-app-title"><RamenBrand /></v-app-bar-title>
      <v-spacer />
      <v-btn id="add-posting" class="d-none d-sm-inline-flex" variant="tonal" prepend-icon="mdi-plus" @click="addOpen = true">{{ t("addPosting.button") }}</v-btn>
      <v-btn
        class="d-sm-none"
        variant="tonal"
        icon="mdi-plus"
        size="small"
        :title="t('addPosting.button')"
        :aria-label="t('addPosting.button')"
        data-test="add-posting-icon"
        @click="addOpen = true"
      />
      <v-btn-toggle
        :model-value="locale"
        mandatory
        density="compact"
        variant="outlined"
        class="ml-2 ml-sm-4"
        :aria-label="t('nav.language')"
        @update:model-value="setLocale($event as Locale)"
      >
        <v-btn v-for="l in locales" :key="l" :value="l" size="small">{{ l.toUpperCase() }}</v-btn>
      </v-btn-toggle>
      <ThemeSwitch class="ml-2" />
    </v-app-bar>

    <v-main>
      <v-container fluid>
        <router-view />
      </v-container>
    </v-main>

    <AddPostingDialog v-model="addOpen" />

    <NotifySnackbar />
  </v-app>
</template>
