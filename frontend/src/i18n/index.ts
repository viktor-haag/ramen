import { createI18n } from "vue-i18n";
import { de as vuetifyDe, en as vuetifyEn } from "vuetify/locale";
import type { ApiError } from "@/api/client";
import de from "./locales/de.json";
import en from "./locales/en.json";

export type Locale = "en" | "de";
const STORAGE_KEY = "jobtracker.locale";

export function loadLocale(): Locale {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "en" || v === "de") return v;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

export const i18n = createI18n({
  legacy: false,
  locale: loadLocale(),
  fallbackLocale: "en",
  messages: {
    en: { ...en, $vuetify: vuetifyEn },
    de: { ...de, $vuetify: vuetifyDe },
  },
});

export function setLocale(l: Locale): void {
  i18n.global.locale.value = l;
  try {
    localStorage.setItem(STORAGE_KEY, l);
  } catch {
    /* storage unavailable */
  }
  document.documentElement.lang = l;
  // Vuetify follows i18n.global.locale through the vue-i18n adapter (see plugins/vuetify.ts).
}

/** Translated message for a backend error; falls back to the (English) detail text. */
export function errorMessage(e: ApiError): string {
  const { t, te } = i18n.global;
  if (e.code === "daily_limit_reached" && e.params?.scope === "config" && te("errors.daily_limit_reached_config")) {
    return t("errors.daily_limit_reached_config", { config_name: String(e.params.config_name ?? "") });
  }
  if (e.code && te(`errors.${e.code}`)) {
    const params: Record<string, unknown> = { ...(e.params ?? {}) };
    if (typeof params.reason === "string" && !params.reason.trim()) params.reason = t("common.noReason");
    if (typeof params.max_bytes === "number") params.max_mb = Math.round(params.max_bytes / (1024 * 1024));
    return t(`errors.${e.code}`, params);
  }
  return typeof e.detail === "string" ? e.detail : e.message;
}
