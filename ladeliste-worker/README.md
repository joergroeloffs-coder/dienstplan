# Dienstplan: WDR-Ladelisten und Sites

Sites: https://dienstplan-ladelisten.joerg-roeloffs.chatgpt.site
Bestehender Entwicklungszweig: ladeliste-worker-neu, PR 14.

## Architektur
WDR (Basic Auth) → Cloudflare Worker (2-Minuten-Cron) → KV je Schiff → private Sites-Serverroute → Browser.
Der Browser prüft alle 120 Sekunden und stößt bei manueller Aktualisierung einen Quellenabruf an. Das ist vom Hintergrund-Cron getrennt. Cron ist nicht sekundengenau. Cloudflare KV ist eventual consistent; eine manuelle Aktualisierung kann kurz verzögert sichtbar werden.

## Sichere Inbetriebnahme
1. GitHub Repository Secrets setzen: CLOUDFLARE_API_TOKEN (Workers Scripts, KV und Account Read passend eingeschränkt), CLOUDFLARE_ACCOUNT_ID, WDR_USER, WDR_PASS und WDR_WORKER_TOKEN (zufälliges gemeinsames API-Secret).
2. Workflow Cloudflare Ladeliste bereitstellen ausführen. Er richtet den KV-Namespace ein, publiziert den bestehenden Worker samt Cron und überträgt die Worker-Secrets WDR_USER, WDR_PASS und API_TOKEN. API_TOKEN erhält den Wert von WDR_WORKER_TOKEN.
3. Sites Runtime-Variablen setzen: WDR_WORKER_URL auf die tatsächlich veröffentlichte HTTPS-Worker-URL; WDR_WORKER_TOKEN auf dasselbe Secret. Keine Werte ins Repository oder Browser-JavaScript schreiben. Nach Änderung Sites erneut deployen.
4. Manuell aktualisieren. Alle vier Schiffe müssen einen erfolgreichen Abruf zeigen. Quellenstand mit WDR-Original abgleichen. Je eine Fahrt mit Zwischenhalt und Durchgangsbuchung prüfen. Zwei aufeinanderfolgende Cron-Abrufe bestätigen. Erst danach den bisherigen Abruf ablösen.

Die App ist bis dahin eine veröffentlichte Oberfläche mit explizitem Anbindungsstatus, kein bestätigter Live-Betrieb. Originaldaten, Namen, Kennzeichen und Buchungsnummern werden nicht gespeichert oder ausgegeben.

## Prüfregeln
Fehler eines Schiffes überschreiben dessen letzte erfolgreiche Ladeliste nicht. Andere Schiffe werden weiter aktualisiert. Erfolgreicher Abrufzeitpunkt und HTTP-Last-Modified der Quelle sind getrennt. Fehlt Last-Modified, ist Quellenfrische unbestätigt; eine wiederholt identische HTML-Antwort allein beweist weder veraltete noch aktuelle Daten. sourceUnchangedSince ist zusätzliche Diagnoseinformation.

Fünf-Minuten-Grenze, ungültige Zeitstempel und Berliner Datumswechsel werden geprüft. Fahrplanlücken bleiben sichtbar. Direkte Fahrten, Zwischenhalte, Durchgangsbuchungen, fünf Minuten Toleranz und nicht zugeordnete Buchungen folgen ladeliste_page.py. Unbekannte Fahrzeugzahlen bleiben null.

Tests: cd ladeliste-worker && npm test. Sie ersetzen keinen Abgleich mit WDR-Originaldaten.
