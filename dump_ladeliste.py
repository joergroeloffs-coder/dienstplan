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
            summe = pkw_meter = None
            j = i + 2
            while j < len(tokens) and not FAHRT_RE.match(tokens[j]):
                gm = GEBUCHT_RE.search(tokens[j])
                if gm:
                    pkw, motorrad, transporter = gm.groups()
                    # "...Meter ohne LKW:" steht im selben Token, der Wert
                    # folgt als naechstes Token (ohne Motorrad-/Transporter-
                    # Anteil herauszurechnen - PKW macht hier i.d.R. den
                    # weit ueberwiegenden Teil aus).
                    if tokens[j].rstrip().endswith("Meter ohne LKW:") and j + 1 < len(tokens):
                        pkw_meter = tokens[j + 1]
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
                "pkw_meter": pkw_meter,
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
                f"PKW-Meter {f['pkw_meter']} m  Summe {f['summe_meter']} m"
            )

    print("\n=== Zeitgleich-Abgleich (gleicher Hafen, +/- 5 Min) - alle Schiffe als Referenz ===")
    seen_pairs = set()
    for ref_name, ref_fahrten in alle.items():
        for rf in ref_fahrten:
            if not rf["zeit"]:
                continue
            rh, rm = map(int, rf["zeit"].split(":"))
            rmin = rh * 60 + rm
            treffer = []
            for name, fahrten in alle.items():
                if name == ref_name:
                    continue
                for f in fahrten:
                    if not f["zeit"] or f["origin"] != rf["origin"]:
                        continue
                    fh, fm = map(int, f["zeit"].split(":"))
                    fmin = fh * 60 + fm
                    if abs(fmin - rmin) <= 5:
                        treffer.append((name, f))
            if not treffer:
                continue
            pair_key = tuple(sorted([ref_name] + [t[0] for t in treffer]) + [rf["origin"], rf["zeit"]])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            print(f"\n{ref_name}: ab {rf['origin']} um {rf['zeit']} -> {rf['ziel']}")
            for name, f in treffer:
                ziel_match = "SELBES ZIEL" if f["ziel"] == rf["ziel"] else "ANDERES ZIEL"
                print(
                    f"  Treffer: {name} faehrt {f['origin']} -> {f['ziel']} "
                    f"um {f['zeit']} ({ziel_match}, PKW-Meter {f['pkw_meter']} m)"
                )


if __name__ == "__main__":
    main()
