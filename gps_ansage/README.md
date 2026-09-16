# GPS-Ansageautomatik

Web-App für automatische Bordansagen auf Basis der GPS-Position (Einlaufen/Ablegen im Hafen).

## Nutzung

1. `gps_ansage/index.html` auf dem Handy im Browser öffnen (z.B. per lokalem Webserver, da `stations.json` per `fetch` geladen wird — direktes Öffnen als `file://` funktioniert in den meisten Browsern nicht wegen CORS).
   - Schnelltest: im Verzeichnis `gps_ansage` z.B. `python3 -m http.server 8000` ausführen und `http://<handy-ip>:8000` öffnen.
2. Standortzugriff erlauben.
3. "GPS-Tracking starten" drücken.

## Konfiguration (`stations.json`)

- `stations`: Liste der Häfen/Stationen mit `lat`/`lon`, Ansagetexten und Radien.
- `arrival.radiusMeters`: Ab dieser Entfernung zum Hafen wird die Einlaufen-Ansage ausgelöst.
- `departure.radiusMeters`: Umkreis, in dem "Anliegen" erkannt wird (Voraussetzung für Ablege-Erkennung).
- `departureSpeedThresholdKmh`: Geschwindigkeit, ab der (nach Stillstand im Hafen) das Ablegen erkannt wird.
- `hysteresisFactor`: Verhindert Mehrfachauslösung durch GPS-Schwankungen am Radius-Rand.

**Wichtig:** Die Koordinaten in `stations.json` sind Platzhalter und müssen durch die echten Hafenpositionen der Wikingerdampfschiffsreederei ersetzt werden. Ebenso sind die Ansagetexte nur Beispiele.

## Funktionsweise

- **Einlaufen**: klassische Geofence-Annäherung — sobald die Distanz zum Hafen den Annäherungsradius unterschreitet, wird die Ansage einmalig abgespielt. Erst wenn das Schiff die Zone wieder deutlich verlässt, wird der Trigger erneut "scharf geschaltet" (Hysterese).
- **Ablegen**: Bewegungserkennung. Das Schiff muss zunächst nahe der Hafenposition und (nahezu) im Stillstand erkannt werden ("liegt an"). Erst wenn danach die Geschwindigkeit über den definierten Schwellwert steigt, wird die Ablege-Ansage ausgelöst — unabhängig von der Uhrzeit.
- **Sprachausgabe**: über die Web Speech API (geräteeigene TTS-Engine des Browsers/Betriebssystems), funktioniert offline.

## Testmodus

Im UI gibt es einen Testmodus mit manueller Eingabe von Position und Geschwindigkeit, um die Auslöselogik ohne echte Fahrt zu testen.

## Offene Punkte / nächste Schritte

- Echte Hafenkoordinaten und Ansagetexte eintragen.
- Weitere "Begebenheiten" (über Einlaufen/Ablegen hinaus) als zusätzliche Einträge in `stations.json` bzw. als eigener Ereignistyp ergänzen, sobald definiert.
- Test auf echtem Android-Gerät/Schiff zur Kalibrierung von Radien und Geschwindigkeitsschwelle.
