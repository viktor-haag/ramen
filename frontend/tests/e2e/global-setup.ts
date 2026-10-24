import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Build the frontend once; the per-test backends serve frontend/dist. */
export default function globalSetup() {
  execFileSync("npm", ["run", "build"], { cwd: resolve(dirname(fileURLToPath(import.meta.url)), "../.."), stdio: "inherit" });
}
