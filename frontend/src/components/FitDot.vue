<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { FitOut } from "@/api/types";
import { fitErrorText } from "@/domain/fitError";

const props = defineProps<{ fit: FitOut | null }>();
const { t, te } = useI18n();

type Kind = "good" | "moderate" | "poor" | "none" | "pending" | "error";

const kind = computed<Kind>(() => {
  const f = props.fit;
  if (!f) return "none";
  if (f.status === "queued" || f.status === "running") return "pending";
  if (f.status === "error") return "error";
  return f.rating ?? "none";
});

const errorText = (code: string | null) => fitErrorText(t as never, te, code);

/** The text alternative of the dot: colour is never the only signal. */
const label = computed(() => {
  const f = props.fit;
  switch (kind.value) {
    case "pending":
      return t(`fit.state.${f!.status}`);
    case "error":
      return `${t("fit.state.error")}: ${errorText(f!.error)}`;
    case "none":
      return f?.status === "done" ? t("fit.state.done") : t("fit.state.none");
    default: {
      const parts = [t(`fit.rating.${kind.value}`)];
      if (f?.explanation) parts.push(f.explanation);
      if (f?.outdated) parts.push(t("fit.outdated"));
      return parts.join(" – ");
    }
  }
});
/** A glyph per rating next to the colour (colour is never the only visual signal). */
const GLYPH = { good: "mdi-check", moderate: "mdi-minus", poor: "mdi-close" } as const;
const glyph = computed(() => (kind.value in GLYPH ? GLYPH[kind.value as keyof typeof GLYPH] : null));
const outdated = computed(() => !!props.fit?.outdated && kind.value !== "pending" && kind.value !== "error");
</script>

<template>
  <span
    role="img"
    class="fit-dot-wrap"
    :aria-label="label"
    data-test="fit-dot"
    :class="[`fit-dot--${kind}`, { 'fit-dot--outdated': outdated }]"
  >
    <v-progress-circular v-if="kind === 'pending'" indeterminate size="14" width="2" aria-hidden="true" />
    <v-icon v-else-if="kind === 'error'" size="16" color="warning" aria-hidden="true">mdi-alert</v-icon>
    <span v-else class="fit-dot" aria-hidden="true">
      <v-icon v-if="glyph" class="fit-dot__glyph" size="10" aria-hidden="true" data-test="fit-dot-glyph">{{ glyph }}</v-icon>
    </span>
    <v-tooltip activator="parent" location="bottom" max-width="360">{{ label }}</v-tooltip>
  </span>
</template>

<style scoped>
.fit-dot-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex: none;
}
.fit-dot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--fit-color);
  background: var(--fit-color);
}
.fit-dot--good {
  --fit-color: rgb(var(--v-theme-success));
}
.fit-dot--moderate {
  --fit-color: rgb(var(--v-theme-warning));
}
.fit-dot--poor {
  --fit-color: rgb(var(--v-theme-error));
}
.fit-dot--none {
  --fit-color: rgba(var(--v-theme-on-surface), 0.38);
}
.fit-dot__glyph {
  color: rgb(var(--v-theme-surface));
}
/* Outdated result: ring instead of a filled dot. */
.fit-dot--outdated .fit-dot {
  background: transparent;
}
.fit-dot--outdated .fit-dot__glyph {
  color: var(--fit-color);
}
</style>
