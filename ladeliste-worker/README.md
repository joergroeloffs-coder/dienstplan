# Neuer Ladelisten-Abruf (Vorbereitung, noch NICHT produktiv)

Dieser Zweig trennt den Datenabruf von GitHub Actions und GitHub Pages.

## Bestandteile
- `src/worker.js`: Cloudflare Worker, ruft die vier Original-Ladelisten per Basic Auth ab, entfernt Kundennamen und Kennzeichen, speichert ein JSON in Cloudflare KV.
- `wrangler.toml`: 2-Minuten-Cron und KV-Bindung.
- `../docs/kal-76a4a349015c4272fe03f77806423a4b/ladeliste-neu.html`: zusätzliche mobile Vorschauseite. Die bisherige `ladeliste.html` bleibt unverändert.

## Inbetriebnahme
1. Cloudflare-Konto/Worker einrichten und Workers KV Namespace erstellen.
2. Dessen ID in `wrangler.toml` hinterlegen.
3. `WDR_USER` und `WDR_PASS` als Cloudflare Worker **Secrets** hinterlegen. Zugangsdaten niemals als Code committen.
4. Worker über Wrangler oder Cloudflare bereitstellen, Cron Trigger aktivieren.
5. Worker-Cron starten lassen und `https://<worker-domain>/api/ladeliste` überprüfen. Es muss `status: aktuell` und ein aktueller `updatedAt`-Wert zurückkommen.
6. Tatsächliche Worker-URL anstelle von `REPLACE_WITH_WORKER_URL` in `ladeliste-neu.html` eintragen.
7. Daten mit WDR-Original und Fahrplan auf Zwischenhalte und Durchgangsbuchungen testen.
8. Erst nach erfolgreichem Test die alte Ladeliste verlinken/ersetzen und den GitHub-Workflow deaktivieren.

## Wichtige Einschränkungen
- Cloudflare-Cron ist nicht sekundengenau. Angegebene zwei Minuten sind ein Intervall, keine garantierte Datenfrische.
- Die Fahrplanzuordnung aus `ladeliste_page.py` ist portiert: Zwischenhalte, Direktfahrten, Toleranz von fünf Minuten und separate Durchgangsbuchungen am Verladehafen. Unbekannte Zahlen werden nicht als null Fahrzeuge ausgegeben.
- Der Worker lädt bei jedem Lauf den bestehenden Fahrplanexport aus `main/fahrplan_schedule.json`. Dessen stündlicher Export bleibt notwendig. Fehlende Tagesetappen werden als Hinweis angezeigt.
- Abruffehler werden separat als `health` gespeichert; die letzte vollständige Momentaufnahme aller vier Schiffe bleibt erhalten. Die Oberfläche prüft das Alter auch ohne erfolgreichen neuen Abruf.
- Automatische Tests: `cd ladeliste-worker && npm test`. Ein Live-Abgleich und zwei aufeinanderfolgende Cron-Läufe sind vor Umschaltung zusätzlich erforderlich.
- Der Worker zeigt ausschließlich zusammengefasste Fahrzeugzahlen und Sonderfahrzeugarten/-längen an. Keine Namen, Kennzeichen oder Buchungsnummern. Öffentlich zugängliche Betriebs-/Buchungsdaten müssen vor Bereitstellung auf Freigabe durch Dateninhaber geprüft werden.
- Ein fehlgeschlagener Abruf überschreibt den letzten erfolgreichen Stand nicht. Die API gibt bei Alter über fünf Minuten oder abweichendem Datum `status: veraltet` zurück.
- Die HTML-Vorschauseite ist mangels Cloudflare-Einrichtung derzeit noch nicht mit Live-Daten verbunden.

## Stand dieser Überarbeitung

Worker und mobile Vorschau sind technisch überarbeitet und mit synthetischen Tests geprüft. Keine produktive Umschaltung: Cloudflare-Anmeldung, KV-ID, Secrets und Live-Vergleich fehlen noch. Alte Workflows und bestehende Dienstplan-/Ladelistenseiten bleiben aktiv. CORS ist kein Zugriffsschutz; die API enthält nur freigegebene Feldtypen, keine persönlichen Buchungsdetails.
