// Minimaler Service Worker - wird nur benoetigt, damit Chrome/Android die
// Seite als installierbare Vollbild-App erkennt ("Zum Startbildschirm
// hinzufuegen" -> echte App statt nur Lesezeichen). Kein Caching, die
// Seite soll immer frisch geladen werden.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
