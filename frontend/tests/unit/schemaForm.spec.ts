import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";
import { VLayout } from "vuetify/components";
import SchemaForm from "@/components/SchemaForm.vue";
import { i18n } from "@/i18n";
import { vuetify } from "@/plugins/vuetify";

const schema = {
  type: "object",
  properties: {
    max_results: { type: "integer", title: "Max results", description: "Upper bound", minimum: 1, maximum: 200 },
    verbose: { type: "boolean", title: "Verbose" },
    api_key: { type: "string", format: "password" },
    mode: { enum: ["a", "b"], title: "Mode" },
    extra: { type: "array", title: "Extra" },
  },
};

function setup(modelValue: Record<string, unknown>, errors?: Record<string, string>) {
  const Host = defineComponent({ render: () => h(VLayout, null, () => h(SchemaForm, { schema, modelValue, errors })) });
  const w = mount(Host, { global: { plugins: [vuetify, i18n] } });
  return { w, form: () => w.findComponent(SchemaForm) };
}

describe("SchemaForm", () => {
  it("renders integer with minimum", () => {
    const { w } = setup({ max_results: 50 });
    const input = w.find("[data-test=field-max_results] input");
    expect(input.attributes("type")).toBe("number");
    expect(input.attributes("min")).toBe("1");
    expect(input.attributes("max")).toBe("200");
    expect((input.element as HTMLInputElement).value).toBe("50");
    expect(w.text()).toContain("Max results");
    expect(w.text()).toContain("Upper bound");
    expect(w.find("[data-test=field-api_key] input").attributes("type")).toBe("password");
    expect(w.text()).toContain("api_key");
  });

  it("boolean as a switch", () => {
    const { w } = setup({ verbose: true });
    const sw = w.find("[data-test=field-verbose] input");
    expect(sw.attributes("type")).toBe("checkbox");
    expect((sw.element as HTMLInputElement).checked).toBe(true);
  });

  it("emits on change without mutating the prop", async () => {
    const model = { max_results: 50, verbose: false };
    const { w, form } = setup(model);
    await w.find("[data-test=field-max_results] input").setValue("75");
    const emitted = form().emitted("update:modelValue")!;
    expect(emitted[0][0]).toEqual({ max_results: 75, verbose: false });
    expect(emitted[0][0]).not.toBe(model);
    expect(model).toEqual({ max_results: 50, verbose: false });
    await w.find("[data-test=field-extra] input").setValue("[1,2]");
    expect(form().emitted("update:modelValue")!.at(-1)![0]).toEqual({ max_results: 50, verbose: false, extra: [1, 2] });
  });

  it("empty number field does not snap back to the default; error disappears on edit", async () => {
    const s = { type: "object", properties: { n: { type: "integer", default: 7 } } };
    const model = { n: 3 };
    const Host = defineComponent({
      render: () => h(VLayout, null, () => h(SchemaForm, { schema: s, modelValue: model, errors: { n: "bad value" } })),
    });
    const w = mount(Host, { global: { plugins: [vuetify, i18n] } });
    const input = w.find("[data-test=field-n] input");
    expect(w.text()).toContain("bad value");
    await input.setValue("");
    expect((input.element as HTMLInputElement).value).toBe("");
    expect(w.text()).not.toContain("bad value");
    await input.trigger("blur");
    expect(w.findComponent(SchemaForm).emitted("update:modelValue")!.at(-1)![0]).toEqual({});
  });

  it("shows errors per field", () => {
    const { w } = setup({}, { max_results: "must be >= 1" });
    expect(w.find("[data-test=field-max_results]").text()).toContain("must be >= 1");
  });
});
