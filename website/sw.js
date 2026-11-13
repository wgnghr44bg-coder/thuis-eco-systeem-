// Service worker: laat de app ook zonder internet openen met het laatste plan.
const CACHE = "energieplan-v3";
const SCHIL = ["./", "index.html", "manifest.webmanifest", "icoon-192.png", "icoon-512.png", "apple-touch-icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SCHIL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(namen => Promise.all(namen.filter(n => n !== CACHE).map(n => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

// Altijd eerst het netwerk (vers plan), en bij geen verbinding de laatste versie uit de cache.
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  const sleutel = url.pathname.endsWith("plan.json") ? new Request(url.origin + url.pathname) : e.request;
  e.respondWith(
    fetch(e.request)
      .then(antwoord => {
        if (antwoord.ok) {
          const kopie = antwoord.clone();
          caches.open(CACHE).then(c => c.put(sleutel, kopie));
        }
        return antwoord;
      })
      .catch(() => caches.match(sleutel).then(r => r || caches.match("index.html")))
  );
});
