import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, toQuery, validationFieldErrors } from "@/api/client";

async function fail(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("expected rejection");
}

afterEach(() => vi.unstubAllGlobals());

describe("toQuery", () => {
  it("repeats arrays and omits empty values", () => {
    expect(toQuery({ triage: ["new", "saved"], q: "", limit: 50 })).toBe("triage=new&triage=saved&limit=50");
    expect(toQuery({ a: undefined, b: null, c: false, d: 0 })).toBe("c=false&d=0");
  });
});

describe("api", () => {
  it("turns an error response into ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "x" }), { status: 409 })),
    );
    const err = await fail(api.post("/x"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.message).toBe("x");
    expect(err.code).toBeNull();
  });

  it("parses code and params, sends JSON and query", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ code: "not_saved", params: { posting_id: 3 }, detail: "d" }), { status: 409 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const err = await fail(api.get("/a"));
    expect(err.code).toBe("not_saved");
    expect(err.params).toEqual({ posting_id: 3 });
    expect(await api.patch("/b", { n: 1 })).toEqual({ ok: 1 });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/b");
    expect(fetchMock.mock.calls[1][1].body).toBe('{"n":1}');
    expect(await api.del("/c")).toBeUndefined();
  });

  it("wraps network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("boom")));
    const err = await fail(api.get("/a"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.code).toBe("network_error");
  });

  it("raises ApiError for a 2xx response with a non-JSON body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 200 })));
    const err = await fail(api.get("/a"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(200);
    expect(err.code).toBeNull();
  });
});

describe("validationFieldErrors", () => {
  const err = (errors: unknown) => new ApiError(422, "validation_error", { errors }, "invalid");

  it("maps the first message per field below the prefix", () => {
    const e = err([
      { loc: ["body", "price_in"], msg: "first" },
      { loc: ["body", "price_in"], msg: "second" },
      { loc: ["body", "name"], msg: "required" },
    ]);
    expect(validationFieldErrors(e, ["body"])).toEqual({ price_in: "first", name: "required" });
  });

  it("honours a longer prefix and skips other locations", () => {
    const e = err([
      { loc: ["body", "settings", "radius"], msg: "too big" },
      { loc: ["body", "enabled"], msg: "not a bool" },
      { loc: ["query", "x"], msg: "other" },
    ]);
    expect(validationFieldErrors(e, ["body", "settings"])).toEqual({ radius: "too big" });
  });

  it("ignores errors that are not below the prefix, have no string message or no list at all", () => {
    expect(validationFieldErrors(err([{ loc: ["body"], msg: "whole body" }, { loc: ["body", "a"], msg: 3 }, {}]), ["body"])).toEqual({});
    expect(validationFieldErrors(err("nope"), ["body"])).toEqual({});
    expect(validationFieldErrors(new ApiError(422, "validation_error", {}, "x"), ["body"])).toEqual({});
  });
});
