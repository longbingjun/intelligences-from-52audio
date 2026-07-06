import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

const repoBase = "/intelligences-from-52audio/";

export default defineConfig({
  site: "https://longbingjun.github.io",
  base: repoBase,
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
  outDir: "../site",
  build: {
    format: "directory",
    assets: "assets",
  },
  trailingSlash: "ignore",
});
