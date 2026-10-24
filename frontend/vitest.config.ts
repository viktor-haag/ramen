import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/unit/**/*.spec.ts"],
    setupFiles: ["tests/unit/setup.ts"],
    css: { include: [/.+/] },
    pool: "forks",
    poolOptions: { forks: { singleFork: true } },
    testTimeout: 20000,
    deps: { optimizer: { web: { include: ["vuetify"] } } },
    server: { deps: { inline: ["vuetify"] } },
  },
});
