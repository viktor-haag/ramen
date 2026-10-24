import { ref, type Ref } from "vue";

export type ThemePref = "auto" | "light" | "dark";
export const THEME_KEY = "jobtracker.theme";

const ORDER: ThemePref[] = ["auto", "light", "dark"];
const DARK_QUERY = "(prefers-color-scheme: dark)";

export interface ThemePreference {
  pref: Ref<ThemePref>;
  setPref(p: ThemePref): void;
  cycle(): void;
}

/** The minimal slice of the Vuetify instance this module needs. */
interface ThemeHost {
  theme: { change(name: string): void };
}

export function readThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === "auto" || v === "light" || v === "dark") return v;
  } catch {
    /* storage unavailable */
  }
  return "auto";
}

export function resolveTheme(pref: ThemePref, prefersDark: boolean): "ramenLight" | "ramenDark" {
  const dark = pref === "auto" ? prefersDark : pref === "dark";
  return dark ? "ramenDark" : "ramenLight";
}

let instance: ThemePreference | null = null;

/**
 * Creates the singleton, applies the resolved theme right away (call before mount to avoid a flash)
 * and follows system colour-scheme changes while the preference is "auto".
 */
export function installThemePreference(host: ThemeHost): ThemePreference {
  const mql = typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
  const pref = ref<ThemePref>(readThemePref());

  const apply = () => host.theme.change(resolveTheme(pref.value, mql?.matches ?? false));

  function setPref(p: ThemePref): void {
    pref.value = p;
    try {
      localStorage.setItem(THEME_KEY, p);
    } catch {
      /* storage unavailable */
    }
    apply();
  }

  mql?.addEventListener("change", () => {
    if (pref.value === "auto") apply();
  });

  apply();
  instance = {
    pref,
    setPref,
    cycle: () => setPref(ORDER[(ORDER.indexOf(pref.value) + 1) % ORDER.length]),
  };
  return instance;
}

export function useThemePreference(): ThemePreference {
  if (!instance) throw new Error("installThemePreference() must be called before useThemePreference()");
  return instance;
}

/** Test-only: drops the singleton so each test starts clean. */
export function resetThemePreferenceForTests(): void {
  instance = null;
}
