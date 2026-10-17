"""
Diagnose-Script (kein Teil der Sync-Pipeline): ruft die aktuellen
Ladeliste-Seiten der 4 relevanten Schiffe ab, parst grob die Fahrt-
Bloecke (Route, Abfahrzeit, Buchungszahlen, Lademeter) und prueft die
"zeitgleich ab gleichem Hafen"-Logik gegen die echten Daten.
"""

import os
import re
import sys

import requests

BASE_URL = "https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste"

SCHIFFE = {
    "NA": "NORDERAUE",
    "S-H": "SCHLESWIG-HOLSTEIN",
    "UTHLANDE": "UTHLANDE",
    "NORDFRIES": "NORDFRIESLAND",
}

TOKEN_RE = re.compile(r'FACE="Helvetica">([^<]*)<')
FAHRT_RE = re.compile(r"^Fahrt:\s*(.+)-(.+)$")
ZEIT_RE = re.compile(r"^Abfahrzeit:\s*(\d{2}:\d{2})$")
GEBUCHT_RE = re.compile(
    r"gebuchte PKW (\d+), Motorr.der (\d+) und Transporter (\d+)"
)


def parse_fahrten(html):
    tokens = [t.strip() for t in TOKEN_RE.findall(html)]
    fahrten = []
    i = 0
    while i < len(tokens):
        m = FAHRT_RE.match(tokens[i])
        if m:
            origin, ziel = m.group(1).strip(), m.group(2).strip()
            zeit = None
            if i + 1 < len(tokens):
                zm = ZEIT_RE.match(tokens[i + 1])
                if zm:
                    zeit = zm.group(1)
            pkw = motorrad = transporter = None
            summe = None
            j = i + 2
            while j < len(tokens) and not FAHRT_RE.match(tokens[j]):
                gm = GEBUCHT_RE.search(tokens[j])
                if gm:
                    pkw, motorrad, transporter = gm.groups()
                if tokens[j].startswith("Summe gebuchter Meter"):
                    if j + 1 < len(tokens):
                        summe = tokens[j + 1]
                j += 1
            fahrten.append({
                "origin": origin,
                "ziel": ziel,
                "zeit": zeit,
                "pkw": pkw,
                "motorrad": motorrad,
                "transporter": transporter,
                "summe_meter": summe,
            })
            i = j
        else:
            i += 1
    return fahrten


def main():
    username = os.environ.get("WDR_USER")
    password = os.environ.get("WDR_PASS")
    if not username or not password:
        sys.exit("Fehlt: WDR_USER / WDR_PASS.")

    session = requests.Session()
    session.auth = (username, password)
    session.headers["User-Agent"] = "dienstplan-sync/2.0"

    alle = {}
    for abk, name in SCHIFFE.items():
        resp = session.get(f"{BASE_URL}/{abk}.html", timeout=30)
        print(f"=== {name} ({abk}.html) HTTP {resp.status_code} ===")
        if resp.status_code != 200:
            continue
        fahrten = parse_fahrten(resp.text)
        alle[name] = fahrten
        for f in fahrten:
            print(
                f"  {f['zeit']}  {f['origin']} -> {f['ziel']}  "
                f"PKW {f['pkw']} Motorrad {f['motorrad']} "
                f"Transporter {f['transporter']}  "
                f"Summe {f['summe_meter']} m"
            )

    print("\n=== Zeitgleich-Abgleich (gleicher Hafen, +/- 5 Min, gleiches Ziel) ===")
    REF = "NORDFRIESLAND"
    ref_fahrten = alle.get(REF, [])
    for rf in ref_fahrten:
        if not rf["zeit"]:
            continue
        rh, rm = map(int, rf["zeit"].split(":"))
        rmin = rh * 60 + rm
        print(f"\n{REF}: {rf['origin']} -> {rf['ziel']} um {rf['zeit']}")
        for name, fahrten in alle.items():
            if name == REF:
                continue
            for f in fahrten:
                if not f["zeit"] or f["origin"] != rf["origin"]:
                    continue
                fh, fm = map(int, f["zeit"].split(":"))
                fmin = fh * 60 + fm
                if abs(fmin - rmin) <= 5:
                    ziel_match = "SELBES ZIEL" if f["ziel"] == rf["ziel"] else "ANDERES ZIEL"
                    print(
                        f"  Treffer: {name} faehrt {f['origin']} -> {f['ziel']} "
                        f"um {f['zeit']} ({ziel_match}, Summe {f['summe_meter']} m)"
                    )


if __name__ == "__main__":
    main()
