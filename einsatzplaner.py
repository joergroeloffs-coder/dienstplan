#!/usr/bin/env python3
"""
Einsatzplaner "Klarschiff" (mit fiktiven Mitarbeitern, ohne echte Namen).

Erzeugt fuer die 4 grossen Schiffe einen woechentlichen Einsatzplan ueber
einen Planungshorizont (Standard: 26 Wochen = 6 Monate), auf Basis der mit
dem Nutzer erarbeiteten Kennzahlen:

  - 7 Positionen je Schiff, je Position 2 Stammkraefte im woechentlichen
    Wechsel (Ablösetag Freitag -> hier vereinfacht als "Woche" gezaehlt)
  - 6 Wochen Urlaub je Stammkraft im Referenzzeitraum
  - 7,5% Krankheitsquote auf die Bordwochen
  - Ueberstunden-Zeitkonto (Jahresmittel, 40h/Woche automatisch durch die
    Freiwoche kompensiert, Rest zu einem einstellbaren Anteil abgefeiert)
  - Ein Springerteam je Schiff (Groesse aus der Kapazitaetsformel, siehe
    personalbedarf_rechner.py) faengt Urlaub/Krankheit/Zeitkonto-Ausgleich auf

Alle Mitarbeiter sind fiktiv (z.B. "UTH.KAP-A", "UTH.SP1") - keine
Personendaten. Ausfaelle (Urlaub/Krankheit/Ausgleich) werden mit einem
festen Zufalls-Seed simuliert, damit die Ausgabe reproduzierbar ist.

Zweck: pruefen, ob eine gegebene Springerteam-Groesse in der Praxis
(Wochenraster statt Durchschnittsrechnung) tatsaechlich ausreicht, und einen
konkreten, lesbaren Dienstplan liefern statt nur eine Kopfzahl.
"""

import argparse
import math
import random
from dataclasses import dataclass, field

SHIFFE = [
    ("Uthlande", "UTH"),
    ("Schleswig-Holstein", "SH"),
    ("Norderaue", "NOR"),
    ("Nordfriesland", "NF"),
]

POSITIONEN = [
    ("Kapitän", "KAP"),
    ("Steuermann", "STM"),
    ("Maschinenassistent", "MA"),
    ("Maschinist", "MSCH"),
    ("Decksmann 1", "DM1"),
    ("Decksmann 2", "DM2"),
    ("Decksmann-Koch", "DMK"),
]

GRUND_TEXT = {"U": "Urlaub", "K": "Krankheit", "A": "Zeitkonto-Ausgleich"}


@dataclass
class Konfiguration:
    referenzzeitraum_wochen: int = 26
    personen_je_position: int = 2
    urlaub_wochen: int = 6
    krankheit_quote: float = 0.075
    jahres_ueberstunden: float = 1100.0
    freiwoche_absorption_h: float = 40.0
    abfeieranteil: float = 0.8
    tagesstunden: float = 8.0
    springer_je_schiff: int = None  # None -> aus Formel berechnet
    seed: int = 42


@dataclass
class Mitarbeiter:
    id: str
    rolle: str  # "stamm" oder "springer"
    schiff: str
    position: str = None       # nur bei Stammkraft gesetzt
    variante: str = None       # "A"/"B" nur bei Stammkraft
    eingesetzte_wochen: int = field(default=0)


def springerbedarf(cfg: Konfiguration) -> int:
    """Springerteam-Groesse je Schiff nach der Kapazitaetsformel
    (siehe personalbedarf_rechner.py) - Durchschnittswert, hier als
    Startgroesse fuer die Simulation."""
    n = cfg.personen_je_position
    bordwochen_je_person = cfg.referenzzeitraum_wochen / n
    u = cfg.urlaub_wochen / bordwochen_je_person
    k = cfg.krankheit_quote

    bordwochen_je_jahr = 52.0 / n
    ueberstunden_je_bordwoche = cfg.jahres_ueberstunden / bordwochen_je_jahr
    rest = max(0.0, ueberstunden_je_bordwoche - cfg.freiwoche_absorption_h)
    ausgleichstage_je_woche = rest * cfg.abfeieranteil / cfg.tagesstunden
    z = ausgleichstage_je_woche / 7.0

    v = u + k + z
    return max(1, math.ceil(len(POSITIONEN) * n * v))


def baue_mitarbeiter(cfg: Konfiguration, schiff: str) -> list:
    leute = []
    for _pos_name, pos_abbr in POSITIONEN:
        for i in range(cfg.personen_je_position):
            variante = chr(ord("A") + i)
            leute.append(Mitarbeiter(
                id=f"{schiff}.{pos_abbr}-{variante}",
                rolle="stamm",
                schiff=schiff,
                position=pos_abbr,
                variante=variante,
            ))
    anzahl_springer = cfg.springer_je_schiff or springerbedarf(cfg)
    for i in range(1, anzahl_springer + 1):
        leute.append(Mitarbeiter(
            id=f"{schiff}.SP{i}",
            rolle="springer",
            schiff=schiff,
        ))
    return leute


def ist_bordwoche(mitarbeiter: Mitarbeiter, woche: int, n: int) -> bool:
    """Stammkraefte wechseln sich turnusweise ab: bei n=2 jede zweite Woche,
    Variante A in geraden, B in ungeraden Zyklen (allgemein: Variante mit
    Index i ist an Bord, wenn woche % n == i)."""
    i = ord(mitarbeiter.variante) - ord("A")
    return woche % n == i


def plane_schiff(cfg: Konfiguration, schiff: str, rng: random.Random) -> dict:
    leute = baue_mitarbeiter(cfg, schiff)
    stamm = [m for m in leute if m.rolle == "stamm"]
    springer_pool = [m for m in leute if m.rolle == "springer"]

    n = cfg.personen_je_position
    horizont = range(1, cfg.referenzzeitraum_wochen + 1)

    # Ausfaelle je Stammkraft vorab wuerfeln: Urlaub, Krankheit, Ausgleich -
    # jeweils nur auf ihren eigenen Bordwochen, ohne Ueberschneidung.
    ausfall = {m.id: {} for m in stamm}  # id -> {woche: grund}
    n_urlaub = cfg.urlaub_wochen  # in Wochen, direkt als ganze Wochen verplant

    bordwochen_je_jahr = 52.0 / n
    ueberstunden_je_bordwoche = cfg.jahres_ueberstunden / bordwochen_je_jahr
    rest = max(0.0, ueberstunden_je_bordwoche - cfg.freiwoche_absorption_h)
    ausgleichstage_je_woche = rest * cfg.abfeieranteil / cfg.tagesstunden
    z_anteil = ausgleichstage_je_woche / 7.0

    for m in stamm:
        eigene_bordwochen = [w for w in horizont if ist_bordwoche(m, w, n)]
        rng.shuffle(eigene_bordwochen)
        rest_wochen = list(eigene_bordwochen)

        urlaub = rest_wochen[:n_urlaub]
        rest_wochen = rest_wochen[n_urlaub:]
        for w in urlaub:
            ausfall[m.id][w] = "U"

        for w in list(rest_wochen):
            if rng.random() < cfg.krankheit_quote:
                ausfall[m.id][w] = "K"
                rest_wochen.remove(w)

        erwartete_ausgleichswochen = z_anteil * len(eigene_bordwochen)
        ganze = int(erwartete_ausgleichswochen)
        bruchteil = erwartete_ausgleichswochen - ganze
        anzahl_ausgleich = ganze + (1 if rng.random() < bruchteil else 0)
        for w in rest_wochen[:anzahl_ausgleich]:
            ausfall[m.id][w] = "A"

    # Wochenweise Plan aufbauen, Springer bei Bedarf zuteilen.
    plan = {w: {} for w in horizont}
    springer_einsaetze = 0
    luecken = []

    for w in horizont:
        belegte_springer_diese_woche = set()
        for _pos_name, pos_abbr in POSITIONEN:
            besetzung = [m for m in stamm if m.position == pos_abbr and ist_bordwoche(m, w, n)]
            for m in besetzung:
                grund = ausfall[m.id].get(w)
                if not grund:
                    plan[w][pos_abbr] = m.id
                    m.eingesetzte_wochen += 1
                    continue
                ersatz = next(
                    (s for s in springer_pool if s.id not in belegte_springer_diese_woche),
                    None,
                )
                if ersatz:
                    belegte_springer_diese_woche.add(ersatz.id)
                    ersatz.eingesetzte_wochen += 1
                    springer_einsaetze += 1
                    plan[w][pos_abbr] = f"{ersatz.id}({grund})"
                else:
                    luecken.append((w, pos_abbr, m.id, grund))
                    plan[w][pos_abbr] = f"LUECKE({grund})"

    return {
        "schiff": schiff,
        "stamm": stamm,
        "springer_pool": springer_pool,
        "plan": plan,
        "springer_einsaetze": springer_einsaetze,
        "luecken": luecken,
        "ausfall": ausfall,
    }


def drucke_plan(ergebnis: dict, cfg: Konfiguration):
    schiff = ergebnis["schiff"]
    print("=" * 100)
    print(f"{schiff}  -  {len(ergebnis['stamm'])} Stammkraefte, "
          f"{len(ergebnis['springer_pool'])} Springer im Pool")
    print("=" * 100)

    kopf = "KW  " + "".join(f"{abbr:>10}" for _n, abbr in POSITIONEN)
    print(kopf)
    for w in range(1, cfg.referenzzeitraum_wochen + 1):
        zeile = f"{w:>3} "
        for _pos_name, pos_abbr in POSITIONEN:
            zeile += f"{ergebnis['plan'][w].get(pos_abbr, '?'):>10}"
        print(zeile)

    print("-" * 100)
    urlaub_gesamt = sum(1 for a in ergebnis["ausfall"].values() for g in a.values() if g == "U")
    krank_gesamt = sum(1 for a in ergebnis["ausfall"].values() for g in a.values() if g == "K")
    ausgleich_gesamt = sum(1 for a in ergebnis["ausfall"].values() for g in a.values() if g == "A")
    kapazitaet = len(ergebnis["springer_pool"]) * cfg.referenzzeitraum_wochen
    auslastung = (ergebnis["springer_einsaetze"] / kapazitaet * 100) if kapazitaet else 0.0
    print(f"Urlaubswochen gesamt: {urlaub_gesamt}  |  Krankheitswochen: {krank_gesamt}  |  "
          f"Ausgleichswochen: {ausgleich_gesamt}")
    print(f"Springereinsaetze: {ergebnis['springer_einsaetze']}  |  "
          f"Springerauslastung: {auslastung:.1f}% der Poolkapazitaet")
    if ergebnis["luecken"]:
        print(f"ACHTUNG: {len(ergebnis['luecken'])} unbesetzte Slots (Springerpool zu klein):")
        for w, pos, wer, grund in ergebnis["luecken"]:
            print(f"  KW {w}: {pos} - {wer} fehlt ({GRUND_TEXT[grund]}), kein Springer frei")
    else:
        print("Keine Luecken - Springerpool hat in dieser Simulation ausgereicht.")
    print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Einsatzplaner mit fiktiven Mitarbeitern.")
    p.add_argument("--wochen", type=int, default=Konfiguration().referenzzeitraum_wochen,
                   help="Planungshorizont in Wochen (26 = 6 Monate).")
    p.add_argument("--personen-je-position", type=int,
                   default=Konfiguration().personen_je_position)
    p.add_argument("--urlaub-wochen", type=int, default=Konfiguration().urlaub_wochen)
    p.add_argument("--krankheit-quote", type=float, default=Konfiguration().krankheit_quote)
    p.add_argument("--jahres-ueberstunden", type=float,
                   default=Konfiguration().jahres_ueberstunden)
    p.add_argument("--abfeieranteil", type=float, default=Konfiguration().abfeieranteil)
    p.add_argument("--springer-je-schiff", type=int, default=None,
                   help="Feste Springerteam-Groesse statt Berechnung aus der Formel.")
    p.add_argument("--seed", type=int, default=Konfiguration().seed)
    return p


def main():
    args = build_parser().parse_args()
    cfg = Konfiguration(
        referenzzeitraum_wochen=args.wochen,
        personen_je_position=args.personen_je_position,
        urlaub_wochen=args.urlaub_wochen,
        krankheit_quote=args.krankheit_quote,
        jahres_ueberstunden=args.jahres_ueberstunden,
        abfeieranteil=args.abfeieranteil,
        springer_je_schiff=args.springer_je_schiff,
        seed=args.seed,
    )
    rng = random.Random(cfg.seed)

    gesamt_luecken = 0
    for schiff, abbr in SHIFFE:
        ergebnis = plane_schiff(cfg, abbr, rng)
        drucke_plan(ergebnis, cfg)
        gesamt_luecken += len(ergebnis["luecken"])

    print("=" * 100)
    print(f"Fleet-Fazit: {gesamt_luecken} unbesetzte Slots ueber alle Schiffe "
          f"und {cfg.referenzzeitraum_wochen} Wochen.")


if __name__ == "__main__":
    main()
