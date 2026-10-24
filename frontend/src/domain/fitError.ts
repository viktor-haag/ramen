type Translate = (key: string, ...args: unknown[]) => string;

/** User-facing text of a fit error code: `fit.errors.<code>`, else the generic `errors.<code>`, else the raw code. */
export function fitErrorText(t: Translate, te: (key: string) => boolean, code: string | null): string {
  if (!code) return t("fit.state.error");
  if (te(`fit.errors.${code}`)) return t(`fit.errors.${code}`);
  if (te(`errors.${code}`)) return t(`errors.${code}`, { reason: t("common.noReason") });
  return code;
}
