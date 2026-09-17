#!/usr/bin/env python3
"""
Exportiert den Fahrplan (alle vier Schiffe, aktuelle + naechste Kalenderwoche)
als JSON-Datei fuer die GPS-Ansageautomatik (separates Repo
gps_ansage_wdr-automatik). Die App liest diese Datei per Cross-Origin-Fetch
von raw.githubusercontent.com, um GPS-Tracking automatisch zu den
Abfahrtszeiten des im UI gewaehlten Schiffs ein- bzw. auszuschalten.

Laeuft wie fahrplan_pdf_mail.py als taeglicher GitHub-Actions-Job (siehe
.github/workflows/fahrplan-export-gps.yml) und schreibt fahrplan_schedule.json
im Repo-Wurzelverzeichnis.

Umgebungsvariablen:
  WDR_USER / WDR_PASS      Zugang zum Fahrplan-Verzeichnis (wie bei den
                           anderen Fahrplan-/Dienstplan-Skripten)
"""

import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pdfplumber
import requests

import dienstplan_cloud_sync as ds

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "fahrplan_schedule.json"


def datum_zu_iso(datum_ddmmyyyy):
    """Wandelt 'DD.MM.YYYY' in 'YYYY-MM-DD' um, oder None bei Fehler/None."""
    if not datum_ddmmyyyy:
        return None
    try:
        tag, monat, jahr = datum_ddmmyyyy.split(".")
        return date(int(jahr), int(monat), int(tag)).isoformat()
    except (ValueError, AttributeError):
        return None


def relevante_kalenderwochen():
    """Aktuelle und naechste Kalenderwoche (deckt Wochenwechsel ab)."""
    heute = date.today()
    jahr, kw, _ = heute.isocalendar()
    naechste = date.fromisocalendar(jahr, kw, 1) + timedelta(days=7)
    jahr2, kw2, _ = naechste.isocalendar()
    wochen = [(jahr, kw)]
    if (jahr2, kw2) != (jahr, kw):
        wochen.append((jahr2, kw2))
    return wochen


def main():
    wdr_user = os.environ.get("WDR_USER")
    wdr_pass = os.environ.get("WDR_PASS")
    if not wdr_user or not wdr_pass:
        sys.exit("Fehlt: WDR_USER / WDR_PASS (GitHub Secrets).")

    session = requests.Session()
    session.auth = (wdr_user, wdr_pass)
    session.headers["User-Agent"] = "dienstplan-fahrplan-export-gps/1.0"

    fahrplan_index = ds.fetch_fahrplan_index(session)

    alle_abfahrten = []
    quellen = []
    for jahr, kw in relevante_kalenderwochen():
        gefunden = ds.find_fahrplan_eintrag(fahrplan_index, jahr, kw)
        if not gefunden:
            print(f"KW {kw}/{jahr}: kein Fahrplan-PDF gefunden, uebersprungen")
            continue
        _, mtime, href, filename = gefunden

        resp = session.get(f"{ds.FAHRPLAN_BASE_URL}/{href}", timeout=30)
        if resp.status_code != 200 or resp.content[:4] != b"%PDF":
            print(f"KW {kw}/{jahr}: Download fehlgeschlagen (HTTP {resp.status_code})")
            continue

        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            abfahrten = ds.parse_fahrplan_pdf(pdf)
        alle_abfahrten.extend(abfahrten)
        quellen.append({"kw": kw, "jahr": jahr, "datei": filename, "stand": mtime})
        print(f"KW {kw}/{jahr} ({filename}): {len(abfahrten)} Abfahrten geparst")

    if not alle_abfahrten:
        sys.exit("Keine Abfahrten gefunden - Export abgebrochen, alte Datei bleibt bestehen.")

    schiffe = {}
    for a in alle_abfahrten:
        iso_datum = datum_zu_iso(a["datum"])
        if not iso_datum:
            continue
        schiffe.setdefault(a["schiff"], []).append({
            "datum": iso_datum,
            "zeit": a["zeit"],
            "route": a["route"],
            "direkt": a["direkt"],
            "vorlaeufig": a["vorlaeufig"],
        })
    for eintraege in schiffe.values():
        eintraege.sort(key=lambda e: (e["datum"], e["zeit"]))

    ausgabe = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quellen": quellen,
        "schiffe": schiffe,
    }
    OUT_PATH.write_text(
        json.dumps(ausgabe, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    anzahl = sum(len(v) for v in schiffe.values())
    print(f"Geschrieben: {OUT_PATH} ({anzahl} Abfahrten, {len(schiffe)} Schiffe)")


if __name__ == "__main__":
    main()
