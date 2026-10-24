<script setup lang="ts">
import { computed, ref, watch } from "vue";

type Schema = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const props = defineProps<{
  schema: Schema;
  modelValue: Record<string, unknown>;
  errors?: Record<string, string>;
}>();
const emit = defineEmits<{ "update:modelValue": [Record<string, unknown>] }>();

/** Follow a local $ref and unwrap Optional (anyOf with null) so pydantic schemas map to simple kinds. */
function resolve(s: Schema): Schema {
  let cur = s;
  for (let i = 0; i < 5; i++) {
    if (typeof cur.$ref === "string") {
      const target = cur.$ref.replace(/^#\/\$defs\//, "");
      const def = props.schema.$defs?.[target];
      if (!def) break;
      cur = { ...def, ...cur, $ref: undefined };
    } else if (Array.isArray(cur.anyOf)) {
      const rest = cur.anyOf.filter((x: Schema) => x.type !== "null");
      if (rest.length !== 1) break;
      const { anyOf: _a, ...own } = cur;
      cur = { ...rest[0], ...own };
    } else break;
  }
  return cur;
}

type Kind = "password" | "string" | "number" | "boolean" | "enum" | "json";
interface Field {
  key: string;
  label: string;
  hint: string | undefined;
  kind: Kind;
  integer: boolean;
  min?: number;
  max?: number;
  options: unknown[];
}

const fields = computed<Field[]>(() =>
  Object.entries((props.schema.properties ?? {}) as Record<string, Schema>).map(([key, raw]) => {
    const s = resolve(raw);
    let kind: Kind = "json";
    if (Array.isArray(s.enum)) kind = "enum";
    else if (s.type === "string") kind = s.format === "password" ? "password" : "string";
    else if (s.type === "integer" || s.type === "number") kind = "number";
    else if (s.type === "boolean") kind = "boolean";
    return {
      key,
      label: raw.title ?? s.title ?? key,
      hint: raw.description ?? s.description,
      kind,
      integer: s.type === "integer",
      min: s.minimum,
      max: s.maximum,
      options: s.enum ?? [],
    };
  }),
);

const defaults = computed(() => props.schema.properties ?? {});
function value(key: string): unknown {
  return key in props.modelValue ? props.modelValue[key] : resolve(defaults.value[key]).default ?? defaults.value[key]?.default;
}

// Server errors are hidden for a field as soon as it is edited, until new errors arrive.
const edited = ref<Set<string>>(new Set());
watch(() => props.errors, () => (edited.value = new Set()));

function set(key: string, v: unknown) {
  edited.value = new Set(edited.value).add(key);
  const next = { ...props.modelValue };
  if (v === undefined) delete next[key];
  else next[key] = v;
  emit("update:modelValue", next);
}

// Number fields keep the raw input while focused (an empty field must not snap back to the default).
const numText = ref<Record<string, string>>({});
function setNumber(key: string, raw: string | number | null) {
  const text = raw === null ? "" : String(raw);
  numText.value[key] = text;
  edited.value = new Set(edited.value).add(key);
  const n = Number(text);
  if (text.trim() !== "" && Number.isFinite(n)) set(key, n);
}
function endNumber(key: string) {
  if ((numText.value[key] ?? "x").trim() === "") set(key, undefined);
  delete numText.value[key];
}

// JSON fallback: keep the raw text locally so half-typed JSON is not lost.
const jsonText = ref<Record<string, string>>({});
const jsonError = ref<Record<string, boolean>>({});
function syncJson() {
  for (const f of fields.value) {
    if (f.kind !== "json") continue;
    const v = value(f.key);
    jsonText.value[f.key] = v === undefined ? "" : JSON.stringify(v);
    jsonError.value[f.key] = false;
  }
}
watch(() => [props.schema, props.modelValue], syncJson, { immediate: true });

function setJson(key: string, text: string) {
  jsonText.value[key] = text;
  if (text.trim() === "") {
    jsonError.value[key] = false;
    return set(key, undefined);
  }
  try {
    const parsed = JSON.parse(text);
    jsonError.value[key] = false;
    emit("update:modelValue", { ...props.modelValue, [key]: parsed });
  } catch {
    jsonError.value[key] = true;
  }
}

const msg = (key: string) => (edited.value.has(key) ? undefined : props.errors?.[key]);
</script>

<template>
  <div data-test="schema-form">
    <template v-for="f in fields" :key="f.key">
      <v-switch
        v-if="f.kind === 'boolean'"
        :model-value="Boolean(value(f.key))"
        :label="f.label"
        :hint="f.hint"
        :error-messages="msg(f.key)"
        persistent-hint
        color="primary"
        density="comfortable"
        :data-test="`field-${f.key}`"
        @update:model-value="(v) => set(f.key, Boolean(v))"
      />
      <v-select
        v-else-if="f.kind === 'enum'"
        :model-value="value(f.key) as string | null | undefined"
        :items="f.options as string[]"
        :label="f.label"
        :hint="f.hint"
        :error-messages="msg(f.key)"
        persistent-hint
        :data-test="`field-${f.key}`"
        @update:model-value="(v) => set(f.key, v)"
      />
      <v-text-field
        v-else-if="f.kind === 'number'"
        type="number"
        :model-value="numText[f.key] ?? (value(f.key) as number | undefined)"
        :label="f.label"
        :hint="f.hint"
        :min="f.min"
        :max="f.max"
        :step="f.integer ? 1 : 'any'"
        :error-messages="msg(f.key)"
        persistent-hint
        :data-test="`field-${f.key}`"
        @update:model-value="(v) => setNumber(f.key, v)"
        @blur="endNumber(f.key)"
      />
      <v-text-field
        v-else-if="f.kind === 'string' || f.kind === 'password'"
        :type="f.kind === 'password' ? 'password' : 'text'"
        :model-value="(value(f.key) as string | undefined) ?? ''"
        :label="f.label"
        :hint="f.hint"
        :error-messages="msg(f.key)"
        persistent-hint
        :data-test="`field-${f.key}`"
        @update:model-value="(v) => set(f.key, v)"
      />
      <v-text-field
        v-else
        :model-value="jsonText[f.key] ?? ''"
        :label="f.label"
        :hint="f.hint"
        :error="jsonError[f.key]"
        :error-messages="msg(f.key)"
        persistent-hint
        class="font-monospace"
        :data-test="`field-${f.key}`"
        @update:model-value="(v) => setJson(f.key, v)"
      />
    </template>
  </div>
</template>
