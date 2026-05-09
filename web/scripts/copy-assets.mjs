/**
 * Copies brand assets from ../assets/brand/ into public/brand/
 * so Astro's static server can serve them.
 *
 * Run automatically as part of `npm run dev` and `npm run build`.
 */

import { cp, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webRoot = join(__dirname, "..");
const src = join(webRoot, "..", "assets", "brand");
const dest = join(webRoot, "public", "brand");

try {
  await mkdir(dest, { recursive: true });
  await cp(src, dest, { recursive: true, force: true });
  console.log(`[setup-assets] Copied brand assets → public/brand/`);
} catch (err) {
  console.warn(`[setup-assets] Could not copy assets: ${err.message}`);
  console.warn("[setup-assets] Continuing without brand assets — images may be missing in dev.");
}
