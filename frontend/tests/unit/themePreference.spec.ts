import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createVuetify } from "vuetify";
import * as components from "vuetify/components";
import ThemeSwitch from "@/components/ThemeSwitch.vue";
import {
  THEME_KEY,
  installThemePreference,
  readThemePref,
  resetThemePreferenceForTests,
  resolveTheme,
  useThemePreference,
} from "@/composables/themePreference";
import { i18n, setLocale } from "@/i18n";

type Listener = (e: { matches: boolean }) => void;
let listeners: Listener[] = [];
let prefersDark = false;

function fireMedia(matches: boolean) {
  prefersDark = matches;
  listeners.forEach((l) => l({ matches }));
}

function makeVuetify() {
  return createVuetify({
    components,
    theme: {
      defaultTheme: "ramenLight",
      themes: {
        ramenLight: { dark: false, colors: { background: "#FBF7F2" } },
        ramenDark: { dark: true, colors: { background: "#151B29" } },
      },
    },
  });
}

beforeEach(() => {
  listeners = [];
  prefersDark = false;
  localStorage.clear();
  resetThemePreferenceForTests();
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation(() => ({
      get matches() {
        return prefersDark;
      },
      addEventListener: (_: string, l: Listener) => listeners.push(l),
      removeEventListener: (_: string, l: Listener) => {
        listeners = listeners.filter((x) => x !== l);
      },
    })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("readThemePref", () => {
  it("defaults to auto", () => {
    expect(readThemePref()).toBe("auto");
  });
  it("returns a stored valid value", () => {
    localStorage.setItem(THEME_KEY, "dark");
    expect(readThemePref()).toBe("dark");
  });
  it("falls back to auto for an unknown value", () => {
    localStorage.setItem(THEME_KEY, "purple");
    expect(readThemePref()).toBe("auto");
  });
  it("falls back to auto when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readThemePref()).toBe("auto");
  });
});

describe("resolveTheme", () => {
  it("maps preference and system scheme to a theme name", () => {
    expect(resolveTheme("auto", true)).toBe("ramenDark");
    expect(resolveTheme("auto", false)).toBe("ramenLight");
    expect(resolveTheme("light", true)).toBe("ramenLight");
    expect(resolveTheme("dark", false)).toBe("ramenDark");
  });
});

describe("installThemePreference", () => {
  it("applies a stored dark preference synchronously", () => {
    localStorage.setItem(THEME_KEY, "dark");
    const vuetify = makeVuetify();
    installThemePreference(vuetify);
    expect(vuetify.theme.global.name.value).toBe("ramenDark");
  });

  it("follows the system scheme while pref is auto", () => {
    const vuetify = makeVuetify();
    installThemePreference(vuetify);
    expect(vuetify.theme.global.name.value).toBe("ramenLight");
    fireMedia(true);
    expect(vuetify.theme.global.name.value).toBe("ramenDark");
  });

  it("ignores system changes for an explicit preference", () => {
    localStorage.setItem(THEME_KEY, "light");
    const vuetify = makeVuetify();
    installThemePreference(vuetify);
    fireMedia(true);
    expect(vuetify.theme.global.name.value).toBe("ramenLight");
  });

  it("cycles auto -> light -> dark -> auto and persists each value", () => {
    const vuetify = makeVuetify();
    const tp = installThemePreference(vuetify);
    const seen: string[] = [];
    for (let i = 0; i < 3; i++) {
      tp.cycle();
      seen.push(tp.pref.value);
      expect(localStorage.getItem(THEME_KEY)).toBe(tp.pref.value);
    }
    expect(seen).toEqual(["light", "dark", "auto"]);
    expect(useThemePreference()).toBe(tp);
  });

  it("does not throw when storage setItem throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    const vuetify = makeVuetify();
    const tp = installThemePreference(vuetify);
    expect(() => tp.cycle()).not.toThrow();
    expect(tp.pref.value).toBe("light");
    expect(vuetify.theme.global.name.value).toBe("ramenLight");
  });
});

describe("ThemeSwitch", () => {
  function mountSwitch() {
    const vuetify = makeVuetify();
    installThemePreference(vuetify);
    return mount(ThemeSwitch, { global: { plugins: [i18n, vuetify] } });
  }

  beforeEach(() => {
    setLocale("en");
    localStorage.clear();
  });

  it("shows icon and label per mode and cycles on click", async () => {
    const w = mountSwitch();
    const btn = () => w.get('[data-test="theme-switch"]');
    expect(btn().find("i").classes()).toContain("mdi-theme-light-dark");
    expect(btn().attributes("aria-label")).toBe("Theme: Auto");
    expect(btn().attributes("title")).toBe("Theme: Auto");
    await btn().trigger("click");
    expect(btn().find("i").classes()).toContain("mdi-white-balance-sunny");
    expect(btn().attributes("aria-label")).toBe("Theme: Light");
    await btn().trigger("click");
    expect(btn().find("i").classes()).toContain("mdi-weather-night");
    expect(btn().attributes("aria-label")).toBe("Theme: Dark");
  });

  it("translates the label", async () => {
    const w = mountSwitch();
    setLocale("de");
    localStorage.clear();
    await w.vm.$nextTick();
    expect(w.get('[data-test="theme-switch"]').attributes("aria-label")).toBe("Design: Automatisch");
  });
});
