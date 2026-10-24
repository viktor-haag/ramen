import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import { errorMessage, i18n, loadLocale, setLocale } from "@/i18n";
import de from "@/i18n/locales/de.json";
import en from "@/i18n/locales/en.json";

function keys(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj)
    .flatMap(([k, v]) =>
      v && typeof v === "object" ? keys(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`],
    )
    .sort();
}

beforeEach(() => {
  localStorage.clear();
  setLocale("en");
  localStorage.clear();
});

describe("i18n", () => {
  it("en.json and de.json have identical key sets", () => {
    expect(keys(de)).toEqual(keys(en));
  });

  it("loadLocale without a stored value is en", () => {
    expect(loadLocale()).toBe("en");
  });

  it("loadLocale reads the stored language", () => {
    localStorage.setItem("jobtracker.locale", "de");
    expect(loadLocale()).toBe("de");
    localStorage.setItem("jobtracker.locale", "fr");
    expect(loadLocale()).toBe("en");
  });

  it("setLocale stores and sets html lang", () => {
    setLocale("de");
    expect(localStorage.getItem("jobtracker.locale")).toBe("de");
    expect(document.documentElement.lang).toBe("de");
    expect(i18n.global.t("status.applied")).toBe("beworben");
  });

  it("errorMessage translates a known code with params and falls back to detail for an unknown one", () => {
    const known = new ApiError(409, "invalid_transition", { from: "saved", to: "offer" }, "Cannot change");
    expect(errorMessage(known)).toBe('The status cannot be changed from "saved" to "offer".');
    setLocale("de");
    expect(errorMessage(known)).toBe('Der Status kann nicht von "saved" zu "offer" wechseln.');
    const unknown = new ApiError(500, "something_new", {}, "English detail");
    expect(errorMessage(unknown)).toBe("English detail");
    expect(errorMessage(new ApiError(500, null, {}, "plain"))).toBe("plain");
  });
});

describe("backend error codes", () => {
  it("every error code sent by the backend has errors.<code> in both languages", () => {
    const root = join(__dirname, "../../../backend/app");
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        if (e.isDirectory()) walk(join(dir, e.name));
        else if (e.name.endsWith(".py")) files.push(join(dir, e.name));
      }
    };
    walk(root);
    const re = /(?:NotFoundError|ConflictError|UpstreamError|UnprocessableError|PayloadTooLargeError|AppError)\(\s*"([a-z_]+)"/g;
    const codes = new Set<string>(["not_found", "validation_error"]); // raised by the handlers in main.py / errors.py
    for (const f of files) for (const m of readFileSync(f, "utf8").matchAll(re)) codes.add(m[1]!);
    expect(codes.size).toBeGreaterThan(10);
    const missing: string[] = [];
    for (const [name, locale] of [["en", en], ["de", de]] as const) {
      const errors = (locale as { errors: Record<string, string> }).errors;
      for (const c of codes) if (typeof errors[c] !== "string") missing.push(`${name}:${c}`);
    }
    expect(missing).toEqual([]);
  });

  it("an empty reason gets a localized fallback instead of a dangling colon", () => {
    const e = new ApiError(502, "llm_unavailable", { reason: "" }, "The LLM provider request failed: no details provided");
    expect(errorMessage(e)).toBe("The LLM provider is not reachable: no details provided");
    setLocale("de");
    const de = errorMessage(e);
    expect(de).toContain("keine Details angegeben");
    expect(de).not.toMatch(/provided|:\s*$/);
    expect(errorMessage(new ApiError(502, "llm_unavailable", { reason: "timeout" }, "x"))).toContain("timeout");
  });

  it("the reset texts list everything that is deleted, the usage limit text is neutral", () => {
    for (const locale of [en, de] as const) {
      const danger = (locale as { settings: { danger: Record<string, string> } }).settings.danger;
      const text = `${danger.resetHint} ${danger.resetConfirm}`;
      for (const word of locale === en
        ? ["postings", "applications", "search profiles", "run history", "plugin settings", "API keys", "usage", "documents"]
        : ["Anzeigen", "Bewerbungen", "Suchprofile", "Laufhistorie", "Plugin-Einstellungen", "API-Schlüssel", "Nutzung", "Unterlagen"]) {
        expect(text).toContain(word);
      }
    }
    expect((en as { ai: { usage: { limitExceeded: string } } }).ai.usage.limitExceeded).toBe("Daily limit reached.");
    expect((de as { ai: { usage: { limitExceeded: string } } }).ai.usage.limitExceeded).toBe("Tageslimit erreicht.");
  });

  it("attachment_too_large shows MB instead of bytes", () => {
    const e = new ApiError(413, "attachment_too_large", { max_bytes: 25 * 1024 * 1024 }, "x");
    expect(errorMessage(e)).toContain("25 MB");
    setLocale("de");
    expect(errorMessage(e)).toContain("25 MB");
  });
});
