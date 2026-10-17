#!/usr/bin/env python3
"""
Erzeugt eine mobile Vollbild-Seite mit der aktuellen Ladeliste des
eigenen Schiffs (automatisch aus state.json ermittelt): letzte, aktuelle
und naechste Abfahrt, inkl. Hinweis auf zeitgleich ab demselben Hafen
abfahrende andere Schiffe (gleicher Hafen, +/- 5 Minuten).

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
STATE_PATH = HERE / "state.json"

BASE_URL = "https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste"
TZ = ZoneInfo("Europe/Berlin")

# Nur diese 4 Schiffe - Hilligenlei ausdruecklich nicht gewuenscht.
SCHIFF_ABK = {
    "NORDERAUE": "NA",
    "SCHLESWIG - HOLSTEIN": "S-H",
    "UTHLANDE": "UTHLANDE",
    "NORDFRIESLAND": "NORDFRIES",
}

FAHRT_SPLIT_RE = re.compile(r"(?=Fahrt:\s*[^<]+-[^<]+<)")
FAHRT_RE = re.compile(r"Fahrt:\s*([^<]+?)-([^<]+?)<")
ZEIT_RE = re.compile(r"Abfahrzeit:\s*(\d{2}:\d{2})")
GEBUCHT_RE = re.compile(
    r"gebuchte PKW (\d+), Motorr.der (\d+) und Transporter (\d+)"
)
NUM_IN_TD_RE = re.compile(r">([\d,]+)<BR>")
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


def aktuelles_schiff(state):
    heute = date.today()
    for entry in state.values():
        d_from, d_to = entry.get("date_from"), entry.get("date_to")
        category = entry.get("category")
        if not (d_from and d_to and category):
            continue
        if category not in SCHIFF_ABK:
            continue
        if date.fromisoformat(d_from) <= heute <= date.fromisoformat(d_to):
            return category
    return None


def minuten(zeit_str):
    h, m = map(int, zeit_str.split(":"))
    return h * 60 + m


def klassifiziere(fahrten, jetzt_min):
    """Letzte (juengste vergangene), Jetzt (naechste kommende), Nächste
    (die danach) - sortiert nach Zeit."""
    mit_zeit = [f for f in fahrten if f["zeit"]]
    mit_zeit.sort(key=lambda f: minuten(f["zeit"]))
    vergangen = [f for f in mit_zeit if minuten(f["zeit"]) <= jetzt_min]
    kommend = [f for f in mit_zeit if minuten(f["zeit"]) > jetzt_min]
    letzte = vergangen[-1] if vergangen else None
    jetzt = kommend[0] if kommend else None
    naechste = kommend[1] if len(kommend) > 1 else None
    return letzte, jetzt, naechste


def zeitgleich_treffer(ref, alle_fahrten, ref_abk):
    """Andere Schiffe, die +/- 5 Min. ab demselben Hafen abfahren -
    alle ihre Fahrt-Bloecke mit diesem Hafen/dieser Zeit (auch mehrere,
    z.B. Weiterfahrt zu einem zweiten Ziel)."""
    if not ref or not ref["zeit"]:
        return []
    ref_min = minuten(ref["zeit"])
    treffer = []
    for abk, fahrten in alle_fahrten.items():
        if abk == ref_abk:
            continue
        legs = [
            f for f in fahrten
            if f["zeit"] and f["origin"] == ref["origin"]
            and abs(minuten(f["zeit"]) - ref_min) <= 5
        ]
        if legs:
            treffer.append((abk, legs))
    return treffer


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
                f'<div class="kind">{esc(fz["beschreibung"])} — {esc(fz["kurzname"])}</div>'
                f'<div class="plate">{kennz}</div>'
                f'<div class="len">{laenge}</div>'
                "</div>"
            )
    html.append("</div>")
    return "\n".join(html)


def karte_html(fahrt, status_label, status_class, mit_details, extra_html=""):
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
    sonder = sonderfahrzeuge_html(fahrt["fahrzeuge"]) if mit_details else ""
    if not stats:
        sonder = '<div class="special-head">Noch keine Ladedaten — wird vor Buchungsschluss aktualisiert</div>'
    return f"""
  <section class="card{' is-past' if status_class == 'past' else ''}">
    <div class="route-row">
      <div class="time">{esc(fahrt['zeit'])}</div>
      <div class="route">{esc(fahrt['origin'])} <span class="arrow">→</span> {esc(fahrt['ziel'])}</div>
      <span class="status {status_class}">{status_label}</span>
    </div>{stats}{total}
    {sonder}{extra_html}
  </section>"""


def overlap_html(ref, treffer):
    if not treffer:
        return ""
    bloecke = []
    for abk, legs in treffer:
        kopf_zeit = legs[0]["zeit"]
        ziele = " + ".join(f"{esc(l['ziel'])}" for l in legs)
        legs_html = "".join(
            f'<div class="leg"><span class="dest">{esc(l["origin"])} → {esc(l["ziel"])}</span>'
            f'<span class="m">{esc(l["summe_pkw_spalte"]) + " m" if l["summe_pkw_spalte"] else "—"}</span></div>'
            for l in legs
        )
        bloecke.append(f"""
    <div class="overlap">
      <div class="head"><span class="dot"></span>
        <div><b>Zeitgleich {esc(abk)}</b> — ab {esc(ref['origin'])} um {esc(kopf_zeit)} → {esc(ziele)}. PKW-Meter je Teilstrecke:</div>
      </div>
      <div class="legs">{legs_html}</div>
    </div>""")
    return "".join(bloecke)


PAGE_TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="refresh" content="60">
<title>Ladeliste Schiff</title>
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
  --warn:#8a5600; --past:#555555;
  color-scheme: light;
  --font-display:'IBM Plex Sans',system-ui,sans-serif;
  --font-mono:'IBM Plex Mono',ui-monospace,monospace;
}}
*{{box-sizing:border-box}}
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
  position:sticky; top:env(safe-area-inset-top,0px); z-index:5;
  background:var(--panel-2); margin:0 -16px; padding:8px 16px 9px;
  border-bottom:1px solid var(--rule);
  display:flex; align-items:baseline; justify-content:space-between; gap:8px;
}}
header.ship h1{{margin:0; font-size:21px; font-weight:800; letter-spacing:.01em; color:var(--fg)}}
header.ship .sub{{font-size:13px; color:var(--fg-dim)}}
main{{padding:10px 0 20px; display:flex; flex-direction:column; gap:10px}}
.card{{
  background:var(--panel); border:1px solid var(--rule); border-radius:10px;
  padding:12px 14px; overflow:hidden;
}}
.card.is-past{{opacity:.78}}
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
.status{{
  font-family:var(--font-mono); font-size:11px; letter-spacing:.06em;
  text-transform:uppercase; padding:3px 8px; border-radius:99px;
  border:1.5px solid currentColor; white-space:nowrap; flex:none; font-weight:700;
}}
.status.now{{color:var(--accent-fg); background:var(--accent); border-color:var(--accent)}}
.status.next{{color:var(--accent); border-color:var(--accent)}}
.status.past{{color:var(--past)}}
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
.total-bar .label{{font-size:13px; color:var(--fg-dim); letter-spacing:.02em; font-weight:600}}
.total-bar .val{{font-family:var(--font-mono); font-variant-numeric:tabular-nums; font-size:23px; font-weight:800; color:var(--accent)}}
.special-head{{margin-top:10px; font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:var(--fg-dim); font-weight:700}}
.special{{margin-top:3px; display:flex; flex-direction:column}}
.group-label{{font-size:12px; font-weight:700; letter-spacing:.03em; color:var(--accent); padding-top:7px; margin-top:4px; border-top:1px solid var(--rule)}}
.special-row{{
  display:grid; grid-template-columns:1fr auto; column-gap:8px;
  padding:5px 0 5px 10px; border-left:3px solid var(--rule);
  min-width:0; align-items:center;
}}
.special-row .plate{{font-family:var(--font-mono); font-weight:800; font-size:14px; color:var(--fg)}}
.special-row .kind{{font-size:13px; color:var(--fg-dim); min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}}
.special-row .len{{font-family:var(--font-mono); font-variant-numeric:tabular-nums; font-size:14px; font-weight:700; color:var(--fg)}}
.overlap{{margin-top:8px; background:var(--panel-2); border-radius:8px; padding:8px 10px; font-size:13px; border:1.5px dashed var(--rule)}}
.overlap .head{{display:flex; align-items:center; gap:7px}}
.overlap .dot{{width:8px; height:8px; border-radius:99px; background:var(--warn); flex:none}}
.overlap b{{font-weight:800; color:var(--fg)}}
.overlap{{color:var(--fg)}}
.overlap .legs{{display:flex; gap:14px; margin-top:6px; padding-top:6px; border-top:1px solid var(--rule)}}
.overlap .leg{{display:flex; flex-direction:column; gap:0}}
.overlap .leg .dest{{color:var(--fg-dim); font-size:12px}}
.overlap .leg .m{{font-family:var(--font-mono); font-variant-numeric:tabular-nums; font-weight:800; font-size:17px; color:var(--fg)}}
footer{{padding:4px 0 12px; font-size:11px; color:var(--fg-dim); text-align:center}}
</style>
</head>
<body>

<header class="ship">
  <h1>{schiff}</h1>
  <div class="sub">{uhrzeit} · aus Dienstplan</div>
</header>

<main>{karten}
</main>

<footer>Quelle: faehre2.de · Ladeliste · Seite aktualisiert sich alle 60s</footer>
</body>
</html>
"""


def main():
    username = os.environ.get("WDR_USER")
    password = os.environ.get("WDR_PASS")
    if not username or not password:
        sys.exit("Fehlt: WDR_USER / WDR_PASS.")

    if not STATE_PATH.exists():
        sys.exit("state.json fehlt - erst dienstplan_cloud_sync.py laufen lassen.")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    schiff = aktuelles_schiff(state)
    if not schiff:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            PAGE_TEMPLATE.format(
                schiff="Kein Schiff diese Woche",
                uhrzeit=datetime.now(TZ).strftime("%H:%M"),
                karten="",
            ),
            encoding="utf-8",
        )
        print("Kein Schiff fuer heute in state.json gefunden.")
        return

    session = requests.Session()
    session.auth = (username, password)
    session.headers["User-Agent"] = "dienstplan-sync/2.0"

    alle_fahrten = {}
    for kategorie, abk in SCHIFF_ABK.items():
        alle_fahrten[abk] = fetch_fahrten(session, abk)

    eigene_abk = SCHIFF_ABK[schiff]
    eigene_fahrten = alle_fahrten[eigene_abk]

    jetzt_min = minuten(datetime.now(TZ).strftime("%H:%M"))
    letzte, jetzt, naechste = klassifiziere(eigene_fahrten, jetzt_min)

    overlap = ""
    if jetzt:
        treffer = zeitgleich_treffer(jetzt, alle_fahrten, eigene_abk)
        overlap = overlap_html(jetzt, treffer)

    karten = []
    karten.append(karte_html(letzte, "Letzte", "past", mit_details=True))
    karten.append(karte_html(jetzt, "Jetzt", "now", mit_details=True, extra_html=overlap))
    karten.append(karte_html(naechste, "Nächste", "next", mit_details=False))

    html = PAGE_TEMPLATE.format(
        schiff=esc(schiff.title()),
        uhrzeit=datetime.now(TZ).strftime("%H:%M"),
        karten="".join(k for k in karten if k),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Ladeliste-Seite geschrieben fuer {schiff} ({eigene_abk}).")


if __name__ == "__main__":
    main()
