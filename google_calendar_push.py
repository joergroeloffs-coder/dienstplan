#!/usr/bin/env python3
"""
Schreibt die Dienstplan-Termine aus state.json direkt in einen Google Kalender.

Laeuft nach dienstplan_cloud_sync.py und ersetzt fuer den eigenen Gebrauch das
ICS-Abonnement: Termine erscheinen sofort statt erst beim naechsten Abruf durch
Google.

Anmeldung ueber ein Dienstkonto (Service Account). Der Zielkalender muss in
Google Kalender fuer die E-Mail-Adresse des Dienstkontos freigegeben sein,
Berechtigung "Aenderungen an Terminen vornehmen".

Umgebungsvariablen:
  GOOGLE_SA_KEY_B64   JSON-Schluessel des Dienstkontos, base64-kodiert
  GOOGLE_CALENDAR_ID  z. B. abc123@group.calendar.google.com
  DRY_RUN             optional, "1" = nur anzeigen, nichts schreiben

Das Skript fasst ausschliesslich Termine an, die es selbst angelegt hat.
Sie sind an der privaten Eigenschaft app=dienstplan-sync erkennbar.
"""

import base64
import binascii
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

HERE = Path(__file__).resolve().parent
STATE_PATH = HERE / "state.json"

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
MARKER_KEY = "app"
MARKER_VALUE = "dienstplan-sync"

# Farben laut Google-Kalender-Palette: 11 = Tomate (rot), 10 = Basilikum (gruen)
COLOR_DIENST = "11"
COLOR_FREI = "10"

DRY_RUN = os.environ.get("DRY_RUN") == "1"


def event_id_for(key):
