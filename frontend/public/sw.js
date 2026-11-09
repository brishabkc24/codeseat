// CodeSeat's service worker. It makes the app installable and keeps the page's
// shell available when the network is not, so an installed app opens to its own
// "connection lost" state rather than a browser error page.
//
// The live parts always go to the network: the API, the class socket and the
// Python runtime (which the browser's own cache already keeps). Hashed build
// files under /assets/ never change, so they are served from the cache once
// seen. Everything else of the site is fetched fresh, with the cache as the
// fallback, so a new deploy takes effect on the next load.

const VERSION = "codeseat-shell-v1";
const SHELL = ["/", "/manifest.webmanifest", "/favicon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  const path = url.pathname;
  if (path.startsWith("/api/") || path.startsWith("/ws/") || path.startsWith("/pyodide/")) return;

  if (request.mode === "navigate") {
    // Every page is the same shell, so any address can fall back to the cached "/".
    event.respondWith(networkFirst(request, "/"));
  } else if (path.startsWith("/assets/")) {
    event.respondWith(cacheFirst(request));
  } else {
    event.respondWith(networkFirst(request));
  }
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(VERSION);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirst(request, shellKey) {
  const cache = await caches.open(VERSION);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(shellKey ?? request, response.clone());
    return response;
  } catch (error) {
    const cached = (await cache.match(request)) ?? (shellKey ? await cache.match(shellKey) : undefined);
    if (cached) return cached;
    throw error;
  }
}
