import { readFileSync } from "node:fs";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import RamenBrand from "@/components/RamenBrand.vue";
import { i18n, setLocale } from "@/i18n";
import de from "@/i18n/locales/de.json";
import en from "@/i18n/locales/en.json";
import { vuetify } from "@/plugins/vuetify";

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  localStorage.clear();
});

function mountBrand() {
  return mount(RamenBrand, { global: { plugins: [i18n, vuetify] } });
}

describe("RamenBrand", () => {
  it("shows the name RAMEN, hidden below 600 px (logo only)", () => {
    const name = mountBrand().get('[data-test="brand-name"]');
    expect(name.text()).toBe("RAMEN");
    expect(name.classes()).toEqual(expect.arrayContaining(["d-none", "d-sm-inline"]));
  });

  it("shows the tagline, hidden below 600 px", () => {
    const tag = mountBrand().get('[data-test="brand-tagline"]');
    expect(tag.text()).toBe("Applications Made Every Night");
    expect(tag.classes()).toEqual(expect.arrayContaining(["d-none", "d-sm-inline"]));
  });

  it("shows the decorative logo", () => {
    const img = mountBrand().get("img");
    expect(img.attributes("src")).toContain("ramen-logo");
    expect(img.attributes("alt")).toBe("");
  });

  it("keeps the brand text identical in both locales", () => {
    expect(en.app.title).toBe("RAMEN");
    expect(de.app.title).toBe("RAMEN");
    expect(en.app.tagline).toBe("Applications Made Every Night");
    expect(de.app.tagline).toBe("Applications Made Every Night");
  });
});

describe("themes", () => {
  it("registers ramenLight (default) and ramenDark with the spec colors", () => {
    const { themes, global } = vuetify.theme;
    expect(global.name.value).toBe("ramenLight");
    expect(themes.value.ramenLight.dark).toBe(false);
    expect(themes.value.ramenDark.dark).toBe(true);
    expect(themes.value.ramenLight.colors.primary).toBe("#C45220");
    expect(themes.value.ramenDark.colors.background).toBe("#151B29");
    expect(themes.value.ramenDark.colors["app-bar"]).toBe("#1A2132");
  });

  it("defines every Vuetify default theme color that components use (no default leaks) in both themes", () => {
    const { themes } = vuetify.theme;
    for (const name of ["ramenLight", "ramenDark"] as const) {
      for (const c of ["surface-variant", "on-surface-variant", "info", "surface-bright", "surface-light", "error", "warning"]) {
        expect(themes.value[name].colors[c]).toMatch(/^#[0-9A-Fa-f]{6}$/);
      }
    }
    expect(themes.value.ramenDark.colors["surface-variant"]).toBe("#3A4560");
    expect(themes.value.ramenDark.colors["surface-bright"]).toBe("#B9C1D4");
    expect(themes.value.ramenLight.colors["surface-light"]).toBe("#F3ECE5");
    expect(themes.value.ramenLight.colors.info).toBe("#3B6EA5");
  });

  it("exposes the custom colors as --v-theme-* CSS variables", () => {
    const css = String(vuetify.theme.styles.value);
    for (const name of ["heading", "tagline", "nav-text", "border-subtle", "edge-neutral", "link", "app-bar"]) {
      expect(css).toContain(`--v-theme-${name}:`);
    }
  });
});

describe("ramen.css dark logo glow", () => {
  it("keeps the logo size and layout unchanged (content-box, symmetric negative margin)", () => {
    const css = readFileSync("src/styles/ramen.css", "utf8");
    const rule = css.match(/\.v-theme--ramenDark \.ramen-brand__logo\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(rule).toContain("box-sizing: content-box");
    expect(rule).toContain("padding: 7px");
    expect(rule).toMatch(/margin:\s*-7px;/);
  });
});

describe("ramen.css typography and polish", () => {
  const css = readFileSync("src/styles/ramen.css", "utf8");
  it("overrides Vuetify's forced Roboto for heading and body typography classes", () => {
    expect(css).toMatch(/\.text-h6\s*\{[^}]*M PLUS Rounded 1c[^}]*!important/);
    expect(css).toMatch(/\.text-body-2,[^{]*\{[^}]*Nunito[^}]*!important/);
  });
  it("styles the dashboard number and uses the mockup glow with a stronger dark card shadow", () => {
    expect(css).toMatch(/\.ramen-stat\s*\{[^}]*--v-theme-primary/);
    expect(css).toContain("drop-shadow(0 0 3px rgba(236, 128, 76, 0.35))");
    expect(css).toContain("rgba(0, 0, 0, 0.28)");
  });
});
