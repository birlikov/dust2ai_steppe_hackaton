import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";

export default defineConfig({
  site: "https://happycake.us",
  integrations: [tailwind()],
  output: "static",
});
