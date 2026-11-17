# Dienstplan: WDR-Ladelisten und Sites

Bestehender Entwicklungszweig: ladeliste-worker-neu, PR 14.

## Architektur (Entscheidung A)
WDR (Basic Auth) → Cloudflare Worker `dienstplan-ladeliste` (2-Minuten-Cron) → KV je Schiff →
Cloudflare Worker `dienstplan-ladelisten-sites` (serverseitiger Proxy, hält WDR_WORKER_TOKEN
geheim) → Browser.

Beide Worker werden über die kostenlose `workers.dev`-Subdomain des Cloudflare-Accounts
veröffentlicht (kein eigener Domain-Umzug nötig). Die bestehende GitHub-Pages-Seite
(docs/kal-.../ladeliste.html) bleibt unverändert, bis die neue Lösung nachweislich
funktioniert; danach wird dort nur ein Link/Hinweis auf die neue Adresse ergänzt.

Der Browser prüft alle 120 Sekunden und stößt bei manueller Aktualisierung einen
Quellenabruf an. Das ist vom Hintergrund-Cron getrennt. Cron ist nicht sekundengenau.
Cloudflare KV ist eventual consistent; eine manuelle Aktualisierung kann kurz verzögert
sichtbar werden.

## Sichere Inbetriebnahme
1. GitHub Repository Secrets setzen (Settings → Secrets and variables → Actions):
   - CLOUDFLARE_API_TOKEN (Rechte: Workers Scripts Edit, Workers KV Storage Edit, Account Settings Read)
   - CLOUDFLARE_ACCOUNT_ID
   - WDR_WORKER_TOKEN (selbst erzeugtes, zufälliges Secret, z. B. `openssl rand -hex 32`)
   - WDR_USER / WDR_PASS (falls noch nicht vorhanden, sonst übernimmt der bestehende Workflow sie)
2. Workflow "Cloudflare Ladeliste bereitstellen" ausführen. Er:
   - richtet den KV-Namespace ein und deployt `dienstplan-ladeliste` (Cron, Quellenabruf),
   - ermittelt danach automatisch dessen `workers.dev`-Adresse,
   - deployt `dienstplan-ladelisten-sites` (Proxy + Oberfläche) und hinterlegt dort
     WDR_WORKER_URL und WDR_WORKER_TOKEN als Worker-Secrets.
   Keine Werte müssen manuell ins Repository oder Browser-JavaScript eingetragen werden.
3. Manuell aktualisieren. Alle vier Schiffe müssen einen erfolgreichen Abruf zeigen.
   Quellenstand mit WDR-Original abgleichen. Je eine Fahrt mit Zwischenhalt und
   Durchgangsbuchung prüfen. Zwei aufeinanderfolgende Cron-Abrufe bestätigen.
   Erst danach die bestehende Ladeliste-Seite verlinken/ablösen.

Die App ist bis dahin eine veröffentlichte Oberfläche mit explizitem Anbindungsstatus, kein
bestätigter Live-Betrieb. Originaldaten, Namen, Kennzeichen und Buchungsnummern werden nicht
gespeichert oder ausgegeben.

## Prüfregeln
Fehler eines Schiffes überschreiben dessen letzte erfolgreiche Ladeliste nicht. Andere
Schiffe werden weiter aktualisiert. Erfolgreicher Abrufzeitpunkt und HTTP-Last-Modified der
Quelle sind getrennt. Fehlt Last-Modified, ist Quellenfrische unbestätigt; eine wiederholt
identische HTML-Antwort allein beweist weder veraltete noch aktuelle Daten.
sourceUnchangedSince ist zusätzliche Diagnoseinformation.

Fünf-Minuten-Grenze, ungültige Zeitstempel und Berliner Datumswechsel werden geprüft.
Fahrplanlücken bleiben sichtbar. Direkte Fahrten, Zwischenhalte, Durchgangsbuchungen, fünf
Minuten Toleranz und nicht zugeordnete Buchungen folgen ladeliste_page.py. Unbekannte
Fahrzeugzahlen bleiben null.

Tests: cd ladeliste-worker && npm test. Sie ersetzen keinen Abgleich mit WDR-Originaldaten.
