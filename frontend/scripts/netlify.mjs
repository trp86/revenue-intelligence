// Netlify forwarding rules for the hosted app (story #193). Netlify proxies /api/* to the
// API on Railway, so the browser sees one site (a first-party session cookie, no CORS), and
// every other path serves the single-page app, so reloading /opportunities/<id> works.

/** The Railway address, checked: https, a host, no path, no trailing slash. */
export function apiOrigin(raw) {
  let url;
  try {
    url = new URL(String(raw ?? "").trim());
  } catch {
    throw new Error("give the Railway address, for example https://revint-api.up.railway.app");
  }
  if (url.protocol !== "https:") throw new Error("the Railway address must start with https://");
  if (url.pathname !== "/" || url.search || url.hash) {
    throw new Error("give only the address (https://<name>.up.railway.app), without a path");
  }
  return url.origin;
}

/** The contents of dist/_redirects. Netlify applies the first matching rule. */
export function redirects(raw) {
  const origin = apiOrigin(raw);
  return `/api/*  ${origin}/api/:splat  200\n/*      /index.html  200\n`;
}
