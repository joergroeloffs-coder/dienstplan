# GPS-Ansageautomatik

Web-App für automatische Bordansagen auf Basis der GPS-Position (Einlaufen/Ablegen im Hafen).

## Nutzung

1. `gps_ansage/index.html` auf dem Handy im Browser öffnen (z.B. per lokalem Webserver, da `stations.json` per `fetch` geladen wird — direktes Öffnen als `file://` funktioniert in den meisten Browsern nicht wegen CORS).
   - Schnelltest: im Verzeichnis `gps_ansage` z.B. `python3 -m http.server 8000` ausführen und `http://<handy-ip>:8000` öffnen.
2. Standortzugriff erlauben.
3. "GPS-Tracking starten" drücken.

## Konfiguration (`stations.json`)

- `textTemplates.arrival`: Objekt mit einer Vorlage je Anleger-Typ – `ohneSeitenausstieg` und `mitSeitenausstieg`. Platzhalter `{hafen}` wird automatisch durch den Stationsnamen ersetzt. Fehlt eine Vorlage (z.B. `mitSeitenausstieg: null`), wird für Stationen ohne eigenen Text keine Ansage abgespielt (siehe Log-Hinweis).
- `textTemplates.departure`: eine gemeinsame Ablege-Vorlage für alle Stationen (aktuell keine Anleger-Typ-Unterscheidung).
- `stations`: Liste der Häfen/Stationen mit `lat`/`lon` und Einlaufen-Radius. `arrival.texts.<berthType>` überschreibt pro Station die globale Vorlage für einen bestimmten Anleger-Typ (z.B. weil der Hafen eine eigene Formulierung braucht). `departure.text` überschreibt entsprechend die Ablege-Vorlage.
- `arrival.radiusMeters`: Ab dieser Entfernung zum Hafen wird die Einlaufen-Ansage ausgelöst.
- **Anleger-Typ-Auswahl (mit/mit Seitenausstieg)**: GPS kann die beiden Anleger je Hafen nicht unterscheiden, da sie zu nah beieinander liegen. Im UI wählt die Crew daher pro Station manuell per Dropdown "Ohne Seitenausstieg" / "Mit Seitenausstieg", bevor der Hafen angelaufen wird. Die Automatik löst weiterhin per GPS aus, spielt aber den zur Auswahl passenden Text.
- `hysteresisFactor`: Verhindert Mehrfachauslösung durch GPS-Schwankungen am Radius-Rand (gilt für Einlaufen).
- `departureDetection`: globale Ablege-Erkennung (nicht pro Station, siehe unten):
  - `stableRadiusMeters` (Default 20): Umkreis, in dem das Schiff als "still liegend" gilt.
  - `stableDurationMinutes` (Default 7): So lange muss das Schiff innerhalb von `stableRadiusMeters` bleiben, damit die Position als Ablege-Anker gilt ("angelegt").
  - `departureRadiusMeters` (Default 50): Entfernung vom Anker, ab der ein Ablegen erkannt wird.
  - `departureWindowMinutes` (Default 2): Diese Entfernung muss innerhalb dieses Zeitfensters erreicht werden – sonst gilt es als langsames Wegdriften statt echtem Ablegen, und es wird nichts ausgelöst.
  - `stationMatchRadiusMeters` (Default 300): Umkreis, in dem der erkannte Ablege-Anker einer konfigurierten Station zugeordnet wird (für den passenden Ansagetext).
  - `genericText`: Fallback-Ansagetext, falls der Anker keiner Station zugeordnet werden kann.
- `secondaryAnnouncements`: manuell auslösbare Zusatzansagen, unabhängig von GPS (z.B. `autodeckFreigabe` – Crew drückt im UI einen eigenen Button, sobald das Autodeck zum Verlassen freigegeben werden soll).

**Wichtig:** Die Koordinaten in `stations.json` sind Platzhalter und müssen durch die echten Hafenpositionen der Wikingerdampfschiffsreederei ersetzt werden. Ebenso sind die Ansagetexte nur Beispiele.

## Referenzpunkte per Karte setzen (`karte.html`)

Statt Koordinaten manuell zu suchen: `gps_ansage/karte.html` im Browser öffnen (funktioniert auch direkt als Datei, keine `fetch`-Abhängigkeit). Zeigt eine OpenStreetMap-Karte, zentriert auf das nordfriesische Wattenmeer.

1. Auf die Karte klicken → setzt einen Referenzpunkt (Marker ist verschiebbar).
2. In der Tabelle darunter Name sowie Annäherungs-/Ablege-Radius je Punkt eintragen.
3. "JSON exportieren" klicken → erzeugt ein fertiges `stations.json`-Gerüst (Texte sind Platzhalter nach Schema "In Kürze legen wir in … an." bzw. "Wir legen jetzt in … ab.").
4. Per "In Zwischenablage kopieren" übernehmen und in `stations.json` einfügen, Texte final anpassen.

Benötigt Internetzugang zum Laden der Kartenkacheln (OpenStreetMap) und der Leaflet-Bibliothek (CDN).

## Funktionsweise

- **Einlaufen**: klassische Geofence-Annäherung — sobald die Distanz zum Hafen den Annäherungsradius unterschreitet, wird die Ansage einmalig abgespielt. Erst wenn das Schiff die Zone wieder deutlich verlässt, wird der Trigger erneut "scharf geschaltet" (Hysterese).
- **Ablegen**: dynamische Anker-Erkennung, unabhängig von vorgegebenen Koordinaten. Bleibt das Schiff länger als `stableDurationMinutes` innerhalb von `stableRadiusMeters` an einer Position, gilt diese Position als Ablege-Anker ("angelegt"). Entfernt sich das Schiff danach innerhalb von `departureWindowMinutes` um mehr als `departureRadiusMeters` von diesem Anker, wird die Ablege-Ansage ausgelöst. Entfernt es sich stattdessen langsam über einen längeren Zeitraum (z.B. Drift durch Tide/Wind), wird nichts ausgelöst und die Erkennung setzt sich zurück.
- **Sprachausgabe**: über die Web Speech API (geräteeigene TTS-Engine des Browsers/Betriebssystems), funktioniert offline.

## Testmodus

Im UI gibt es einen Testmodus mit manueller Eingabe von Position und Geschwindigkeit, um die Auslöselogik ohne echte Fahrt zu testen.

## Offene Punkte / nächste Schritte

- Ansagetext "Mit Seitenausstieg" für Dagebüll noch nicht definiert (aktuell nur für Wyk auf Föhr und Wittdün auf Amrum hinterlegt).
- Ansagetexte für Ablegen (Vorlage gilt bisher pauschal, keine Anleger-Typ-Unterscheidung) ggf. noch anpassen.
- Weitere "Begebenheiten" (über Einlaufen/Ablegen hinaus) als zusätzliche Einträge in `stations.json` bzw. als eigener Ereignistyp ergänzen, sobald definiert.
- Test auf echtem Android-Gerät/Schiff zur Kalibrierung von Radien und Zeitfenstern.
