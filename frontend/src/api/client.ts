import type { ErrorBody } from "./types";

export class ApiError extends Error {
  status: number;
  code: string | null;
  params: Record<string, unknown>;
  detail: unknown;

  constructor(status: number, code: string | null, params: Record<string, unknown>, detail: unknown, message?: string) {
    super(message ?? (typeof detail === "string" ? detail : `HTTP ${status}`));
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.params = params;
    this.detail = detail;
  }
}

/**
 * Per-field messages from a 422 `validation_error`. An error counts when its `loc` starts with `prefix`
 * (e.g. ["body"] or ["body", "settings"]); the next `loc` element names the field.
 */
export function validationFieldErrors(e: ApiError, prefix: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  const list = e.params.errors;
  if (!Array.isArray(list)) return out;
  for (const item of list as { loc?: unknown[]; msg?: unknown }[]) {
    const loc = item.loc ?? [];
    if (loc.length > prefix.length && prefix.every((p, i) => loc[i] === p) && typeof item.msg === "string") {
      out[String(loc[prefix.length])] ??= item.msg;
    }
  }
  return out;
}

/** Build a query string: arrays become repeated parameters; undefined/null/"" are omitted. */
export function toQuery(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const values = Array.isArray(value) ? value : [value];
    for (const v of values) {
      if (v === undefined || v === null || v === "") continue;
      sp.append(key, String(v));
    }
  }
  return sp.toString();
}

const BASE = "/api";

async function toError(res: Response): Promise<ApiError> {
  let body: ErrorBody | null = null;
  try {
    body = (await res.json()) as ErrorBody;
  } catch {
    body = null;
  }
  const code = typeof body?.code === "string" ? body.code : null;
  const params = body?.params && typeof body.params === "object" ? body.params : {};
  return new ApiError(res.status, code, params, body?.detail ?? res.statusText);
}

async function request<T>(method: string, path: string, init: { params?: Record<string, unknown>; body?: unknown; form?: FormData } = {}): Promise<T> {
  const query = init.params ? toQuery(init.params) : "";
  const url = `${BASE}${path}${query ? `?${query}` : ""}`;
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (init.form) {
    body = init.form;
  } else if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body });
  } catch (e) {
    throw new ApiError(0, "network_error", {}, String(e), "Network error");
  }
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, null, {}, "Invalid JSON in response", "Invalid response");
  }
}

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) => request<T>("GET", path, { params }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  del: <T = void>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
};
