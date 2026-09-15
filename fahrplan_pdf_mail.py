#!/usr/bin/env python3
"""
Markiert das Fahrplan-PDF der aktuellen bzw. naechsten Dienstwoche mit dem
eigenen Schiff und verschickt es per E-Mail.

Laeuft taeglich (siehe .github/workflows/fahrplan-pdf-mail.yml) und prueft,
ob sich das massgebliche Fahrplan-PDF gegenueber dem letzten Versand
geaendert hat (Dateiname/Aenderungsdatum, siehe fahrplan_mail_state.json).
Nur bei Aenderung (oder beim allerersten Lauf) wird eine neu markierte
Fassung verschickt - kein taeglicher Mail-Spam bei unveraendertem Plan.

"Massgebliche Woche" ist die Dienstwoche (Kategorie = Schiff), deren
Zeitraum das heutige Datum enthaelt, sonst die naechste bevorstehende.

Umgebungsvariablen:
  WDR_USER / WDR_PASS               Zugang zum Fahrplan-Verzeichnis
  GMAIL_USER / GMAIL_APP_PASSWORD   Absender (App-Passwort, kein normales Passwort)
  MAIL_TO                           Empfaengeradresse
"""

import io
import json
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import pdfplumber
import requests
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

import dienstplan_cloud_sync as ds

HERE = Path(__file__).resolve().parent
STATE_PATH = HERE / "state.json"
MAIL_STATE_PATH = HERE / "fahrplan_mail_state.json"

MARKIERUNG_FUELLUNG = Color(1, 0.85, 0.2, alpha=0.45)
MARKIERUNG_RAHMEN = Color(0.85, 0.55, 0, alpha=0.9)
VERMERK_FARBE = Color(0.55, 0.25, 0, alpha=1)


def aktuelle_dienstwoche(state):
    """Die Dienstwoche (Kategorie ist ein Schiff), deren Zeitraum das
    heutige Datum enthaelt, sonst die naechste bevorstehende. (None, None)
    wenn keine gefunden wird."""
    heute = date.today()
    dienstwochen = [
        (key, entry) for key, entry in state.items()
        if ds.ist_schiff(entry.get("category", "") or "")
        and entry.get("date_from") and entry.get("date_to")
    ]
    for key, entry in sorted(dienstwochen, key=lambda kv: kv[1]["date_from"]):
        von = date.fromisoformat(entry["date_from"])
        bis = date.fromisoformat(entry["date_to"])
        if von <= heute <= bis:
            return key, entry
    kommende = [
        (key, entry) for key, entry in dienstwochen
        if date.fromisoformat(entry["date_from"]) > heute
    ]
    if not kommende:
        return None, None
    return min(kommende, key=lambda kv: kv[1]["date_from"])


def markiere_pdf(pdf_bytes, abfahrten, schiff):
    """Halbtransparente Markierung + Vermerk ueber den Abfahrten des
    eigenen Schiffs, seitenweise per reportlab-Overlay auf das
    Original-PDF gelegt (pypdf)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    schreiber = PdfWriter()

    eigene_nach_seite = {}
    for a in abfahrten:
        if ds.norm(a["schiff"]) != ds.norm(schiff):
            continue
        eigene_nach_seite.setdefault(a["seite"], []).append(a)

    for seiten_nr, seite in enumerate(reader.pages):
        eintraege = eigene_nach_seite.get(seiten_nr)
        if eintraege:
            breite = float(seite.mediabox.width)
            hoehe = float(seite.mediabox.height)
            puffer = io.BytesIO()
            c = canvas.Canvas(puffer, pagesize=(breite, hoehe))
            c.setFillColor(MARKIERUNG_FUELLUNG)
            c.setStrokeColor(MARKIERUNG_RAHMEN)
            for a in eintraege:
                x0, top, x1, bottom = a["bbox"]
                # pdfplumber zaehlt y von oben, reportlab von unten.
                y0 = hoehe - bottom - 1
                y1 = hoehe - top + 1
                c.roundRect(
                    x0 - 2, y0, (x1 - x0) + 4, (y1 - y0), 2,
                    stroke=1, fill=1,
                )
            c.setFillColor(VERMERK_FARBE)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(20, hoehe - 14, f"Markiert: eigenes Schiff {schiff}")
            c.save()
            puffer.seek(0)
            overlay = PdfReader(puffer).pages[0]
            seite.merge_page(overlay)
        schreiber.add_page(seite)

    ausgabe = io.BytesIO()
    schreiber.write(ausgabe)
    return ausgabe.getvalue()


def sende_mail(empfaenger, absender, app_passwort, betreff, text, pdf_bytes, dateiname):
    msg = EmailMessage()
    msg["Subject"] = betreff
    msg["From"] = absender
    msg["To"] = empfaenger
    msg.set_content(text)
    msg.add_attachment(
        pdf_bytes, maintype="application", subtype="pdf", filename=dateiname
    )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(absender, app_passwort)
        smtp.send_message(msg)


def main():
    wdr_user = os.environ.get("WDR_USER")
    wdr_pass = os.environ.get("WDR_PASS")
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
    mail_to = os.environ.get("MAIL_TO")
    if not all([wdr_user, wdr_pass, gmail_user, gmail_pass, mail_to]):
        sys.exit(
            "Fehlt: WDR_USER / WDR_PASS / GMAIL_USER / GMAIL_APP_PASSWORD / MAIL_TO."
        )

    if not STATE_PATH.exists():
        sys.exit(
            "state.json nicht gefunden - zuerst dienstplan_cloud_sync.py laufen lassen."
        )
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    key, entry = aktuelle_dienstwoche(state)
    if not entry:
        print("Keine aktuelle oder bevorstehende Dienstwoche gefunden.")
        return

    jahr, kw = key.split("-W")
    schiff = entry["category"]
    print(f"Massgebliche Woche: KW {kw}/{jahr}, Schiff: {schiff}")

    session = requests.Session()
    session.auth = (wdr_user, wdr_pass)
    session.headers["User-Agent"] = "dienstplan-fahrplan-mail/1.0"

    fahrplan_index = ds.fetch_fahrplan_index(session)
    gefunden = ds.find_fahrplan_eintrag(fahrplan_index, int(jahr), int(kw))
    if not gefunden:
        print(f"Kein Fahrplan fuer KW {kw}/{jahr} gefunden.")
        return
    _, mtime, href, filename = gefunden

    mail_state = {}
    if MAIL_STATE_PATH.exists():
        mail_state = json.loads(MAIL_STATE_PATH.read_text(encoding="utf-8"))
    bisher = mail_state.get(key)
    if bisher and bisher.get("file") == filename and bisher.get("mtime") == mtime:
        print(f"KW {kw}/{jahr}: unveraendert ({filename}, {mtime}) - keine Mail.")
        return

    resp = session.get(f"{ds.FAHRPLAN_BASE_URL}/{href}", timeout=30)
    if resp.status_code != 200 or resp.content[:4] != b"%PDF":
        sys.exit(f"Fahrplan-Download fehlgeschlagen: HTTP {resp.status_code}")

    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        abfahrten = ds.parse_fahrplan_pdf(pdf)

    markiertes_pdf = markiere_pdf(resp.content, abfahrten, schiff)

    betreff = f"Fahrplan KW {kw}/{jahr} - {schiff} markiert"
    text = (
        f"Fahrplan fuer KW {kw}/{jahr}, eigenes Schiff {schiff} markiert.\n"
        f"Quelle: {filename}, Stand {mtime}.\n"
    )
    sende_mail(
        mail_to, gmail_user, gmail_pass, betreff, text,
        markiertes_pdf, f"Fahrplan_KW{kw}_{schiff}_markiert.pdf",
    )
    print(f"Mail verschickt an {mail_to} ({filename}, Stand {mtime}).")

    mail_state[key] = {"file": filename, "mtime": mtime}
    MAIL_STATE_PATH.write_text(
        json.dumps(mail_state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
