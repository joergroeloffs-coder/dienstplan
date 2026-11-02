#!/usr/bin/env python3
"""
Erzeugt eine mobile Vollbild-Seite mit ALLEN heutigen Abfahrten ALLER 4
Schiffe (Live-Buchungsdaten + amtlicher Fahrplan zusammengefuehrt) -
unabhaengig davon, wer die Seite aufruft oder welches Schiff "das
eigene" waere. Chronologisch sortiert, ein Kasten je Abfahrt, jeweils
in der Farbe des fahrenden Schiffs mit Route, Ladedaten und
Sonderfahrzeugen. Beim Oeffnen springt die Seite automatisch zur
aktuellen Abfahrt; ein Jetzt-Button holt dahin zurueck, falls man sich
weggescrollt hat.

Quelle: https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste/<ABK>.html -
live-System, aktualisiert sich dort alle 30s. Diese Seite wird per Cronjob
(siehe .github/workflows/ladeliste-sync.yml) alle paar Minuten neu erzeugt
und ueber GitHub Pages veroeffentlicht; die Seite selbst laedt sich per
Meta-Refresh alle 60s neu nach.

Zugangsdaten kommen aus WDR_USER / WDR_PASS (GitHub Actions Secrets).
"""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

HERE = Path(__file__).resolve().parent
SLUG = "kal-76a4a349015c4272fe03f77806423a4b"
OUTPUT_PATH = HERE / "docs" / SLUG / "ladeliste.html"
# Der echte, amtliche Fahrplan (von fahrplan_export_gps.py aus dem
# Fahrplan-PDF erzeugt) nennt je Schiff die tatsaechlichen Etappen mit
# Zwischenhalten (z.B. Uthlande 17:25 Wittduen-Wyk, dann 18:40 Wyk-
# Dagebuell als zwei eigene Etappen). Die Live-Ladeliste dagegen fasst
# Durchgangsbuchungen zu einem Block zusammen (Ursprung-Endziel, nur die
# Abfahrzeit der ersten Etappe) - deshalb wird hier der Fahrplan fuer die
# Etappen-Struktur genommen und nur die Ladedaten (PKW/Meter/...) aus den
# Buchungsbloecken der Live-Ladeliste dazugemischt.
FAHRPLAN_PATH = HERE / "fahrplan_schedule.json"

BASE_URL = "https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste"
TZ = ZoneInfo("Europe/Berlin")

# Nur diese 4 Schiffe - Hilligenlei ausdruecklich nicht gewuenscht.
SCHIFF_ABK = {
    "NORDERAUE": "NA",
    "SCHLESWIG - HOLSTEIN": "S-H",
    "UTHLANDE": "UTHLANDE",
    "NORDFRIESLAND": "NORDFRIES",
}

# Gedaempfte (keine Volltoene) Hintergrundfarben je Schiff, nach
# Abkuerzung - je Schiff-Kasten in seiner eigenen Farbe.
SCHIFF_FARBE = {
    "S-H": "#dce7f5",
    "UTHLANDE": "#f6dcdc",
    "NA": "#e3e3e3",
    "NORDFRIES": "#f7eec9",
}

FAHRT_SPLIT_RE = re.compile(r"(?=Fahrt:\s*[^<]+-[^<]+<)")
FAHRT_RE = re.compile(r"Fahrt:\s*([^<]+?)-([^<]+?)<")
ZEIT_RE = re.compile(r"Abfahrzeit:\s*(\d{2}:\d{2})")
GEBUCHT_RE = re.compile(
    r"gebuchte PKW (\d+), Motorr.der (\d+) und Transporter (\d+)"
)
# Zwischen der Zahl und dem "<BR>" steht manchmal noch Zusatztext (z.B. eine
# Masseinheit) statt dass die Zahl direkt vom "<BR>" gefolgt wird - deshalb
# [^<]* statt eines strikten direkten Anschlusses.
NUM_IN_TD_RE = re.compile(r">([\d,]+)[^<]*<BR>")
TR_RE = re.compile(r"<TR>(.*?)</TR>", re.S)
TD_RE = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def td_text(td_html):
    text = TAG_RE.sub("", td_html)
    text = text.replace("&nbsp", "").replace("&amp;", "&")
    return text.strip()


def zwei_meterwerte_nach(slice_, marker):
    """Die 2 Zahlen (Laenge-LKW-Spalte, Laenge-PKW-Spalte) in den beiden
    TDs direkt nach `marker` - zweite Zahl ist die PKW-Spalte."""
    idx = slice_.find(marker)
    if idx == -1:
        return None, None
    treffer = NUM_IN_TD_RE.findall(slice_[idx : idx + 600])
    if len(treffer) >= 2:
        return treffer[0], treffer[1]
    return None, None

# Beschreibungs-Praefixe, die eine Buchung als "Sonderfahrzeug" statt
# normalem PKW einstufen, plus die Kategorie, unter der sie gruppiert wird.
SONDER_KATEGORIEN = [
    ("LKW", "LKW"),
    ("Transporter", "Transporter"),
    ("PKW-Anh", "PKW-Anhänger"),
    ("PKW Anh", "PKW-Anhänger"),
    ("Motorrad", "Motorrad"),
]


def kategorie_fuer(beschreibung):
    for praefix, kategorie in SONDER_KATEGORIEN:
        if praefix.lower() in beschreibung.lower():
            return kategorie
    return None


def parse_vehicle_rows(slice_):
    """Jede Fahrzeugzeile hat exakt 8 Inhalts-TDs (getrennt von
    Abstandshalter-TDs): Buchungsnr, Kurzname, Ladeart, Beschreibung,
    Boarding, Kennzeichen, Laenge(LKW), Laenge(PKW). Ueber die echte
    TR/TD-Struktur geparst statt ueber einen Text-Tokenstrom, weil leere
    Felder (z.B. Boarding, Kennzeichen) dort keine FACE="Helvetica"-
    Markierung tragen und sonst die Tokenpositionen verschieben."""
    fahrzeuge = []
    for tr_html in TR_RE.findall(slice_):
        tds = [td_text(td) for td in TD_RE.findall(tr_html)]
        inhalt = tds[0::2]
        if len(inhalt) < 8 or not inhalt[0].isdigit():
            continue
        _, kurzname, _ladeart, beschreibung, _boarding, kennzeichen, _laenge_lkw, laenge_pkw = inhalt[:8]
        kategorie = kategorie_fuer(beschreibung)
        if not kategorie:
            continue
        fahrzeuge.append({
            "kategorie": kategorie,
            "beschreibung": beschreibung,
            "kurzname": kurzname,
            "kennzeichen": kennzeichen or None,
            "laenge": laenge_pkw or None,
        })
    return fahrzeuge


def parse_fahrten(html):
    """Liefert Fahrt-Bloecke mit Zeiten, Buchungszahlen, PKW-Spalten-Metern
    und den einzelnen Sonderfahrzeugen."""
    bloecke = FAHRT_SPLIT_RE.split(html)
    fahrten = []
    for block in bloecke:
        fm = FAHRT_RE.search(block)
        if not fm:
            continue
        origin, ziel = fm.group(1).strip(), fm.group(2).strip()
        zm = ZEIT_RE.search(block)
        zeit = zm.group(1) if zm else None

        gm = GEBUCHT_RE.search(block)
        pkw = motorrad = transporter = None
        if gm:
            pkw, motorrad, transporter = gm.groups()

        # Beide Summenzeilen im Report haben je 2 Werte: eine Spalte
        # "Laenge(LKW)" und eine Spalte "Laenge(PKW)" - nur Letztere wird
        # hier verwendet (vom Nutzer bestaetigt: erste Spalte ist falsch).
        _, summe_pkw_spalte = zwei_meterwerte_nach(block, "Summe gebuchter Meter:")

        fahrten.append({
            "origin": origin,
            "ziel": ziel,
            "zeit": zeit,
            "pkw": pkw,
            "motorrad": motorrad,
            "transporter": transporter,
            "summe_pkw_spalte": summe_pkw_spalte,
            "fahrzeuge": parse_vehicle_rows(block),
        })
    return fahrten


def fetch_fahrten(session, abk):
    resp = session.get(f"{BASE_URL}/{abk}.html", timeout=30)
    if resp.status_code != 200:
        return []
    return parse_fahrten(resp.text)


def minuten(zeit_str):
    h, m = map(int, zeit_str.split(":"))
    return h * 60 + m


def finde_aktuellen_index(abfahrten, jetzt_min):
    """Index der Abfahrt, die gerade "aktuell" ist: die juengste
    vergangene, wenn sie nicht mehr als 5 Min. zurueckliegt, sonst die
    naechste kommende, sonst (nach Betriebsschluss) die letzte des Tages.
    `abfahrten` muss bereits chronologisch sortiert sein."""
    mit_zeit = [(i, minuten(e[0])) for i, e in enumerate(abfahrten) if e[0]]
    if not mit_zeit:
        return None
    vergangen = [t for t in mit_zeit if t[1] <= jetzt_min]
    kommend = [t for t in mit_zeit if t[1] > jetzt_min]
    if vergangen and jetzt_min - vergangen[-1][1] <= 5:
        return vergangen[-1][0]
    if kommend:
        return kommend[0][0]
    return vergangen[-1][0]


def esc(text):
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def sonderfahrzeuge_html(fahrzeuge):
    gruppen = {}
    for fz in fahrzeuge:
        gruppen.setdefault(fz["kategorie"], []).append(fz)
    for liste in gruppen.values():
        liste.sort(
            key=lambda f: float((f["laenge"] or "0").replace(",", ".")),
            reverse=True,
        )
    reihenfolge = ["LKW", "Transporter", "PKW-Anhänger", "Motorrad"]
    teile = []
    for kategorie in reihenfolge:
        for fz in gruppen.get(kategorie, []):
            if not teile or teile[-1][0] != kategorie:
                teile.append((kategorie, []))
            teile[-1][1].append(fz)
    if not teile:
        return ""
    html = ['<div class="special-head">Sonderfahrzeuge — nach Art, je Länge absteigend</div>', '<div class="special">']
    for kategorie, liste in teile:
        html.append(f'<div class="group-label">{esc(kategorie)}</div>')
        for fz in liste:
            laenge = f"{fz['laenge']} m" if fz["laenge"] else "—"
            kennz = esc(fz["kennzeichen"]) if fz["kennzeichen"] else "—"
            html.append(
                '<div class="special-row">'
                f'<div class="kind">{esc(fz["kurzname"])}</div>'
                f'<div class="plate">{kennz}</div>'
                f'<div class="len">{laenge}</div>'
                "</div>"
            )
    html.append("</div>")
    return "\n".join(html)


def route_html(origin, ziel):
    return f'{esc(origin)} <span class="arrow">→</span> {esc(ziel)}'


def karte_html(fahrt, label, farbe, aktuell=False):
    """Ein Abfahrts-Kasten: Schiffsname, Route/Zeit, Ladedaten,
    Sonderfahrzeuge - komplett in der Schiffsfarbe gehalten. `aktuell`
    markiert den Kasten als Sprungziel fuer Auto-Scroll und Jetzt-Button."""
    if fahrt is None:
        return ""
    stats = ""
    if fahrt["pkw"] is not None:
        stats = f"""
    <div class="stats">
      <div class="stat"><b>{fahrt['pkw']}</b><span>PKW</span></div>
      <div class="stat"><b>{fahrt['motorrad']}</b><span>Motorrad</span></div>
      <div class="stat"><b>{fahrt['transporter']}</b><span>Transporter</span></div>
      <div class="stat"><b>{len(fahrt['fahrzeuge'])}</b><span>Sonder</span></div>
    </div>"""
    total = ""
    if fahrt["summe_pkw_spalte"]:
        total = f"""
    <div class="total-bar">
      <span class="label">Gesamt gebuchte Meter</span>
      <span class="val">{fahrt['summe_pkw_spalte']} m</span>
    </div>"""
    sonder = sonderfahrzeuge_html(fahrt["fahrzeuge"])
    if not stats:
        hinweis = fahrt.get("leer_hinweis") or "Noch keine Ladedaten — wird vor Buchungsschluss aktualisiert"
        sonder = f'<div class="special-head">{esc(hinweis)}</div>'
    durchgang = ""
    if fahrt.get("durchgangs_hinweis"):
        durchgang = f'<div class="legs-label">{esc(fahrt["durchgangs_hinweis"])}</div>'
    style = f' style="background:{farbe}"' if farbe else ""
    jetzt_attr = " data-jetzt" if aktuell else ""
    return f"""
  <section class="card"{style}{jetzt_attr}>
    <div class="ship-label">{esc(label)}</div>
    <div class="route-row">
      <div class="time">{esc(fahrt['zeit'])}</div>
      <div class="route">{route_html(fahrt['origin'], fahrt['ziel'])}</div>
    </div>
    {durchgang}{stats}{total}
    {sonder}
  </section>"""


# Der Fahrplan nennt Haefen mit ihrem Ortsnamen (Pier), die Live-Ladeliste
# mit dem Inselnamen - Uebersetzung fuer den Abgleich der beiden Quellen.
FAHRPLAN_HAFEN_NAME = {"Wittdün": "AMRUM", "Wyk": "FÖHR", "Dagebüll": "DAGEBÜLL"}


def lade_fahrplan():
    if not FAHRPLAN_PATH.exists():
        return {}
    try:
        return json.loads(FAHRPLAN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# Die Fahrplan-Spalten sind feste Streckenabschnitte (Wittdün-Wyk /
# Wyk-Dagebüll / Dagebüll-Wyk / Wyk-Wittdün). Ein "dir"-Vermerk im PDF
# (Feld "direkt") bedeutet: diese Abfahrt laeuft Wyk NICHT an, sondern
# faehrt direkt zum jeweils naechsten Hafen durch - das eigentliche Ziel
# ist dann das der anschliessenden Spalte, nicht Wyk.
FAHRPLAN_DIREKT_ZIEL = {
    "Wittdün-Wyk": "Dagebüll",
    "Dagebüll-Wyk": "Wittdün",
}


def offizielle_etappen(fahrplan, schiff_kategorie, datum_iso):
    """Die laut amtlichem Fahrplan heute tatsaechlich gefahrenen Etappen
    (inkl. Zwischenhalten mit eigener Abfahrzeit) fuer ein Schiff."""
    etappen = []
    for eintrag in fahrplan.get("schiffe", {}).get(schiff_kategorie, []):
        if eintrag.get("datum") != datum_iso:
            continue
        route = eintrag.get("route", "")
        try:
            von, nach = (teil.strip() for teil in route.split("-", 1))
        except (KeyError, ValueError):
            continue
        if eintrag.get("direkt") and route in FAHRPLAN_DIREKT_ZIEL:
            nach = FAHRPLAN_DIREKT_ZIEL[route]
        etappen.append({
            "origin": FAHRPLAN_HAFEN_NAME.get(von, von.upper()),
            "ziel": FAHRPLAN_HAFEN_NAME.get(nach, nach.upper()),
            "zeit": eintrag.get("zeit"),
        })
    return etappen


def _bloecke_bei(etappe, bloecke):
    """Alle Buchungsbloecke, die zu dieser Etappe gehoeren: gleicher
    Abfahrtshafen, Zeit +/- 5 Min. - unabhaengig vom Ziel, denn eine
    Durchgangsbuchung (z.B. Dagebuell-Amrum bei einer offiziellen Etappe
    Dagebuell-Wyk) wird an GENAU DIESEM Hafen und GENAU DIESER Zeit
    verladen, auch wenn ihr Ziel weiter als die Etappe reicht."""
    return [
        b for b in bloecke
        if b["origin"] == etappe["origin"] and b["zeit"]
        and abs(minuten(b["zeit"]) - minuten(etappe["zeit"])) <= 5
    ]


def fahrten_nach_fahrplan(schiff_kategorie, bloecke, fahrplan, datum_iso):
    """Baut die Abfahrtsliste eines Schiffs aus dem amtlichen Fahrplan auf
    - je Etappe (inkl. Zwischenhalten) eine eigene Kachel mit Hafenpaar +
    Abfahrzeit. Jede zu dieser Etappe passende Buchung (gleicher
    Abfahrtshafen, Zeit +/- 5 Min.) wird mit ihrem EIGENEN Ziel gezeigt -
    eine Durchgangsbuchung, die ueber die Etappe hinaus bis zu einem
    weiteren Hafen durchfaehrt, bekommt also ihre eigene Kachel bei der
    Zeit, zu der sie tatsaechlich verladen wird, statt erst bei der
    Anschluss-Etappe aufzutauchen."""
    etappen = offizielle_etappen(fahrplan, schiff_kategorie, datum_iso)
    if not etappen:
        return bloecke

    fahrten = []
    verbrauchte_bloecke = set()  # id() der Bloecke, die einer Etappe zugeordnet wurden
    for etappe in etappen:
        treffer = _bloecke_bei(etappe, bloecke)
        if not treffer:
            fahrten.append({
                **etappe,
                "pkw": None, "motorrad": None, "transporter": None,
                "summe_pkw_spalte": None, "fahrzeuge": [],
                "leer_hinweis": "Noch keine eigene Buchung zu dieser Etappe",
            })
            continue
        for block in treffer:
            verbrauchte_bloecke.add(id(block))
            fahrten.append({**block, "zeit": etappe["zeit"]})

    # Buchung hat Vorrang: eine Buchung, die zu keiner Fahrplan-Etappe passt
    # (z.B. weil sich kurzfristig etwas geaendert hat und der Fahrplan noch
    # nicht aktualisiert wurde), wird trotzdem angezeigt statt verworfen.
    for block in bloecke:
        if id(block) in verbrauchte_bloecke:
            continue
        fahrten.append({
            **block,
            "durchgangs_hinweis": "Nicht im Fahrplan enthalten — laut aktueller Buchung",
        })

    fahrten.sort(key=lambda f: minuten(f["zeit"]) if f.get("zeit") else 9999)
    return fahrten


PAGE_TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Ladeliste</title>
<link rel="manifest" href="ladeliste.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" href="icon-192.png">
<meta name="theme-color" content="#0a7a68">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Ladeliste">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;700;800&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#f4f6f6; --panel:#ffffff; --panel-2:#eef2f2;
  --fg:#000000; --fg-dim:#333333; --rule:#c7d0d0;
  --accent:#0a7a68; --accent-fg:#ffffff;
  color-scheme: light;
  --font-display:'IBM Plex Sans',system-ui,sans-serif;
  --font-mono:'IBM Plex Mono',ui-monospace,monospace;
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:auto}}
body{{
  background:var(--bg); color:var(--fg);
  font-family:var(--font-display); font-size:17px; line-height:1.45;
  padding-left:max(16px, env(safe-area-inset-left,0px));
  padding-right:max(16px, env(safe-area-inset-right,0px));
}}
body::before{{
  content:""; position:fixed; inset:0 0 auto; height:env(safe-area-inset-top,0px);
  z-index:10; background:var(--panel-2);
}}
header.ship{{
  background:var(--panel-2);
  position:sticky; top:env(safe-area-inset-top,0px); z-index:5;
  margin:0 -16px; padding:8px 16px 9px;
  border-bottom:1px solid var(--rule);
}}
header.ship h1{{margin:0; font-size:21px; font-weight:800; letter-spacing:.01em; color:var(--fg)}}
header.ship .sub{{font-size:13px; color:var(--fg-dim)}}
main{{padding:10px 0 20px; display:flex; flex-direction:column; gap:10px}}
.card{{
  background:var(--panel); border:1px solid var(--rule); border-radius:10px;
  padding:12px 14px; overflow:hidden;
  scroll-margin-top:calc(54px + env(safe-area-inset-top,0px));
}}
.card[data-jetzt]{{border:2px solid var(--accent)}}
.card .ship-label{{font-size:13px; font-weight:800; letter-spacing:.03em; text-transform:uppercase; color:var(--fg-dim); margin-bottom:6px}}
.route-row{{display:flex; align-items:center; gap:10px; flex-wrap:nowrap}}
.time{{
  font-family:var(--font-mono); font-variant-numeric:tabular-nums;
  font-size:25px; font-weight:800; flex:none; color:var(--fg);
}}
.route{{
  display:flex; align-items:baseline; gap:5px; min-width:0; flex:1 1 auto;
  font-size:17px; font-weight:700; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; color:var(--fg);
}}
.route .arrow{{color:var(--accent); font-weight:400}}
.stats{{display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:10px}}
.stat{{
  background:var(--panel-2); border-radius:8px; padding:7px 2px;
  text-align:center; min-width:0;
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:1px;
}}
.stat b{{font-family:var(--font-mono); font-variant-numeric:tabular-nums; font-size:20px; line-height:1.1; color:var(--fg)}}
.stat span{{font-size:10px; color:var(--fg-dim); font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%}}
.total-bar{{
  margin-top:8px; background:var(--panel-2); border-radius:8px;
  padding:8px 10px; display:flex; align-items:baseline; justify-content:space-between; gap:8px;
}}
.total-bar .label{{font-size:13px; color:var(--fg-dim); letter-spacing:.02em; font-weight:600; min-width:0}}
.total-bar .val{{font-family:var(--font-mono); font-variant-numeric:tabular-nums; font-size:19px; font-weight:800; color:var(--accent); white-space:nowrap; flex:none}}
.special-head{{margin-top:10px; font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:var(--fg-dim); font-weight:700}}
.special{{margin-top:3px; display:flex; flex-direction:column}}
.group-label{{font-size:12px; font-weight:700; letter-spacing:.03em; color:var(--accent); padding-top:7px; margin-top:4px; border-top:1px solid var(--rule)}}
.special-row{{
  display:grid; grid-template-columns:1fr auto; column-gap:8px; row-gap:1px;
  grid-template-areas:"kind kind" "plate len";
  padding:5px 0 5px 10px; border-left:3px solid var(--rule);
  min-width:0; align-items:center;
}}
.special-row .kind{{grid-area:kind; font-size:13px; color:var(--fg-dim); min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}}
.special-row .plate{{grid-area:plate; font-family:var(--font-mono); font-weight:800; font-size:13px; color:var(--fg-dim)}}
.special-row .len{{grid-area:len; font-family:var(--font-mono); font-variant-numeric:tabular-nums; font-size:14px; font-weight:700; color:var(--fg)}}
.legs-label{{margin-top:8px; font-size:11px; color:var(--fg-dim); font-weight:600}}
footer{{padding:4px 0 12px; font-size:11px; color:var(--fg-dim); text-align:center}}
#no-ship{{padding:20px 4px; color:var(--fg-dim); text-align:center}}
#jump-now{{
  position:fixed; right:16px; bottom:max(16px, env(safe-area-inset-bottom,0px));
  z-index:6; background:var(--accent); color:var(--accent-fg); border:none;
  border-radius:999px; padding:12px 20px; font-weight:800; font-size:14px;
  font-family:var(--font-display); box-shadow:0 2px 10px rgba(0,0,0,.3);
}}
</style>
</head>
<body>

<header class="ship">
  <div>
    <h1>Ladeliste</h1>
    <div class="sub">{uhrzeit} Uhr</div>
  </div>
</header>

<main>
{karten}
</main>

<footer>Quelle: faehre2.de · Ladeliste · Seite aktualisiert sich alle 60s</footer>
<button id="jump-now" type="button">⏱ Jetzt</button>

<script>
if ("serviceWorker" in navigator) {{
  navigator.serviceWorker.register("ladeliste-sw.js");
}}

function zurAktuellenAbfahrt(verhalten) {{
  const jetzt = document.querySelector("[data-jetzt]");
  if (jetzt) {{
    jetzt.scrollIntoView({{block: "start", behavior: verhalten}});
  }}
}}

zurAktuellenAbfahrt("instant");
document.getElementById("jump-now").addEventListener("click", () => {{
  zurAktuellenAbfahrt("smooth");
}});

// Meta-Refresh laed dieselbe URL erneut und wird vom Browser-/CDN-Cache
// bedient statt neu vom Server geholt zu werden - deshalb per JS mit
// Cache-Busting-Query und explizit "no-store" neu laden.
setTimeout(() => {{
  location.href = location.pathname + "?t=" + Date.now();
}}, 60000);
</script>
</body>
</html>
"""


def main():
    username = os.environ.get("WDR_USER")
    password = os.environ.get("WDR_PASS")
    if not username or not password:
        sys.exit("Fehlt: WDR_USER / WDR_PASS.")

    session = requests.Session()
    session.auth = (username, password)
    session.headers["User-Agent"] = "dienstplan-sync/2.0"

    alle_fahrten = {}
    for kategorie, abk in SCHIFF_ABK.items():
        alle_fahrten[abk] = fetch_fahrten(session, abk)

    jetzt_min = minuten(datetime.now(TZ).strftime("%H:%M"))
    uhrzeit = datetime.now(TZ).strftime("%H:%M")
    heute_iso = date.today().isoformat()
    fahrplan = lade_fahrplan()

    # Die Etappen (inkl. Zwischenhalten) kommen aus dem amtlichen Fahrplan,
    # die Ladedaten je Etappe aus den Live-Buchungsbloecken - die Live-Seite
    # fasst Durchgangsbuchungen sonst zu einem Block zusammen und
    # verschluckt dabei Zwischenhalte (z.B. Wyk). Alle Abfahrten aller
    # Schiffe werden gesammelt und am Ende gemeinsam chronologisch
    # sortiert - unabhaengig davon, welches Schiff "das eigene" waere.
    alle_abfahrten = []
    for kategorie, abk in SCHIFF_ABK.items():
        fahrten = fahrten_nach_fahrplan(kategorie, alle_fahrten[abk], fahrplan, heute_iso)
        for fahrt in fahrten:
            alle_abfahrten.append((fahrt.get("zeit"), kategorie.title(), SCHIFF_FARBE.get(abk), fahrt))

    alle_abfahrten.sort(key=lambda e: minuten(e[0]) if e[0] else 9999)
    aktueller_index = finde_aktuellen_index(alle_abfahrten, jetzt_min)

    karten = [
        karte_html(fahrt, label, farbe, aktuell=(i == aktueller_index))
        for i, (_zeit, label, farbe, fahrt) in enumerate(alle_abfahrten)
    ]
    karten_html = "".join(karten) if karten else '<div id="no-ship">Keine Abfahrten gefunden.</div>'

    html = PAGE_TEMPLATE.format(uhrzeit=uhrzeit, karten=karten_html)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Ladeliste-Seite geschrieben mit {len(karten)} Abfahrten.")


if __name__ == "__main__":
    main()
