import { mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { describe, expect, it } from "vitest";
import App from "@/App.vue";
import { installThemePreference } from "@/composables/themePreference";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";

describe("App bar", () => {
  it("has a text add-posting button for sm+ and an icon-only one with aria-label below sm", () => {
    installThemePreference(vuetify);
    const w = mount(App, {
      global: {
        plugins: [createPinia(), i18n, vuetify],
        stubs: { RouterView: true, AddPostingDialog: true, NotifySnackbar: true },
      },
    });
    const text = w.get("#add-posting");
    expect(text.classes()).toEqual(expect.arrayContaining(["d-none", "d-sm-inline-flex"]));
    const icon = w.get('[data-test="add-posting-icon"]');
    expect(icon.classes()).toContain("d-sm-none");
    expect(icon.attributes("aria-label")).toBe(text.text());
    expect(icon.text()).toBe("");
    w.unmount();
  });
});
