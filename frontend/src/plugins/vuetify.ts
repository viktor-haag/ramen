import "@mdi/font/css/materialdesignicons.css";
import "vuetify/styles";
import { createVuetify } from "vuetify";
import * as components from "vuetify/components";
import * as directives from "vuetify/directives";
import { createVueI18nAdapter } from "vuetify/locale/adapters/vue-i18n";
import { useI18n } from "vue-i18n";
import { i18n } from "@/i18n";

type VueI18nOption = Parameters<typeof createVueI18nAdapter>[0]["i18n"];

export const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: "ramenLight",
    themes: {
      ramenLight: {
        dark: false,
        colors: {
          background: "#FBF7F2",
          surface: "#FFFFFF",
          primary: "#C45220",
          secondary: "#5B2A1F",
          success: "#6A994E",
          "on-background": "#34241E",
          "on-surface": "#34241E",
          heading: "#5B2A1F",
          tagline: "#A88A78",
          "nav-text": "#6B5248",
          "border-subtle": "#EFE4DA",
          "edge-neutral": "#D9CFC7",
          link: "#C45220",
          "app-bar": "#FFFFFF",
          "surface-variant": "#E9DFD6",
          "on-surface-variant": "#4A3A33",
          info: "#3B6EA5",
          "surface-bright": "#FFFFFF",
          "surface-light": "#F3ECE5",
          error: "#B3382C",
          warning: "#D9822B",
        },
      },
      ramenDark: {
        dark: true,
        colors: {
          background: "#151B29",
          surface: "#1E2638",
          primary: "#EC804C",
          secondary: "#F6DCC6",
          success: "#8DBB6E",
          "on-background": "#E8E2D8",
          "on-surface": "#E8E2D8",
          heading: "#F6DCC6",
          tagline: "#8E99B3",
          "nav-text": "#B9C1D4",
          "border-subtle": "#2B3449",
          "edge-neutral": "#46506A",
          link: "#F2A57E",
          "app-bar": "#1A2132",
          "surface-variant": "#3A4560",
          "on-surface-variant": "#D8DDEA",
          info: "#8FB3E0",
          "surface-bright": "#B9C1D4",
          "surface-light": "#2A3349",
          error: "#E8837A",
          warning: "#F0A860",
        },
      },
    },
  },
  locale: { adapter: createVueI18nAdapter({ i18n: i18n as unknown as VueI18nOption, useI18n }) },
});
