import "@fontsource/m-plus-rounded-1c/latin-700.css";
import "@fontsource/m-plus-rounded-1c/latin-800.css";
import "@fontsource/nunito/latin-400.css";
import "@fontsource/nunito/latin-400-italic.css";
import "@fontsource/nunito/latin-600.css";
import "@fontsource/nunito/latin-700.css";
import { createPinia } from "pinia";
import { createApp } from "vue";
import App from "./App.vue";
import { i18n } from "./i18n";
import { installThemePreference } from "./composables/themePreference";
import { vuetify } from "./plugins/vuetify";
import { router } from "./router";
import "./styles/ramen.css";

document.documentElement.lang = i18n.global.locale.value;
installThemePreference(vuetify); // before mount: a stored "dark" must not flash light
createApp(App).use(createPinia()).use(i18n).use(vuetify).use(router).mount("#app");
