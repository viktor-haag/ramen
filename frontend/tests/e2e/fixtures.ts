import { test as base, expect } from "@playwright/test";
import { type ChildProcess, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Local servers are never reached through a developer's HTTP(S)_PROXY. */
const NO_PROXY = { NO_PROXY: "127.0.0.1,localhost", no_proxy: "127.0.0.1,localhost" };

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const BACKEND = resolve(FRONTEND, "../backend");

function freePort(): Promise<number> {
  return new Promise((ok, fail) => {
    const s = createServer();
    s.once("error", fail);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address() as { port: number };
      s.close(() => ok(port));
    });
  });
}

async function waitHealthy(url: string, proc: ChildProcess, log: () => string) {
  for (let i = 0; i < 100; i++) {
    if (proc.exitCode !== null) throw new Error(`backend exited early:\n${log()}`);
    try {
      if ((await fetch(`${url}/api/health`)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`backend did not become healthy:\n${log()}`);
}

async function waitUp(url: string, proc: ChildProcess, log: () => string) {
  for (let i = 0; i < 50; i++) {
    if (proc.exitCode !== null) throw new Error(`fake llm server exited early:\n${log()}`);
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`fake llm server did not come up:\n${log()}`);
}

/** `baseURL` points at a fresh backend (own port, own empty data dir, only the fake plugin). */
export const test = base.extend<{ baseURL: string; fakeLlmUrl: string }>({
  /** Base URL (including /v1) of a fresh fake OpenAI-compatible server on its own port. */
  fakeLlmUrl: async ({}, use) => {
    const port = await freePort();
    let output = "";
    const proc = spawn(process.env.E2E_PYTHON ?? join(BACKEND, ".venv/bin/python"), [join(FRONTEND, "tests/e2e/fake_llm.py"), String(port)], {
      detached: true,
      env: { ...process.env, ...NO_PROXY },
    });
    proc.stdout?.on("data", (d) => (output += d));
    proc.stderr?.on("data", (d) => (output += d));
    // A failed spawn (e.g. missing interpreter) is reported by waitUp instead of crashing the worker.
    proc.on("error", (e) => (output += `spawn error: ${e.message}\n`));
    try {
      await waitUp(`http://127.0.0.1:${port}/v1/models`, proc, () => output);
      await use(`http://127.0.0.1:${port}/v1`);
    } finally {
      try {
        process.kill(-proc.pid!, "SIGTERM");
      } catch {
        /* already gone */
      }
    }
  },

  baseURL: async ({}, use) => {
    const dataDir = mkdtempSync(join(tmpdir(), "jobtracker-e2e-"));
    const port = await freePort();
    let output = "";
    const proc = spawn(
      process.env.E2E_PYTHON ?? join(BACKEND, ".venv/bin/python"),
      ["-m", "uvicorn", "app.main:create_app", "--factory", "--port", String(port)],
      {
        cwd: BACKEND,
        detached: true,
        env: {
          ...process.env,
          ...NO_PROXY,
          JOBTRACKER_DATA_DIR: dataDir,
          JOBTRACKER_PLUGIN_DIRS: join(FRONTEND, "tests/e2e/plugins"),
          JOBTRACKER_FRONTEND_DIST: join(FRONTEND, "dist"),
          JOBTRACKER_POOL_SIZE: "1",
          JOBTRACKER_UPDATE_CHECK: "false",
        },
      },
    );
    proc.stdout?.on("data", (d) => (output += d));
    proc.stderr?.on("data", (d) => (output += d));
    proc.on("error", (e) => (output += `spawn error: ${e.message}\n`));
    const url = `http://127.0.0.1:${port}`;
    try {
      await waitHealthy(url, proc, () => output);
      await use(url);
    } finally {
      // The runner pool spawns child processes: kill the whole process group.
      try {
        process.kill(-proc.pid!, "SIGTERM");
      } catch {
        /* already gone */
      }
      rmSync(dataDir, { recursive: true, force: true });
    }
  },
});

export { expect };
