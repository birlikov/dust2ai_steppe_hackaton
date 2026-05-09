import type { APIRoute } from "astro";
import { fetchCatalog } from "../lib/api";

const SITE = "https://happycake.us";

const STATIC_ROUTES = [
  "/",
  "/about",
  "/policies",
  "/order",
  "/custom",
  "/guides/cake-for-x-guests",
];

export const GET: APIRoute = async () => {
  const catalog = await fetchCatalog();
  const productSlugs = catalog?.products?.map((p) => p.slug) ?? [
    "honey-cake-slice",
    "pistachio-roll",
  ];
  const urls = [
    ...STATIC_ROUTES,
    ...productSlugs.map((slug) => `/cake/${slug}`),
  ];
  const now = new Date().toISOString();
  const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls
  .map(
    (path) =>
      `  <url><loc>${SITE}${path}</loc><lastmod>${now}</lastmod></url>`,
  )
  .join("\n")}
</urlset>
`;
  return new Response(body, {
    headers: { "Content-Type": "application/xml" },
  });
};
