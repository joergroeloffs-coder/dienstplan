"""
Einmaliges Diagnose-Script (kein Teil der eigentlichen Sync-Pipeline):
gibt das Verzeichnislisting von .../Schiffe/Ladeliste/ sowie den rohen
HTML-Inhalt von NORDFRIES.html im Workflow-Log aus, um den Aufbau der
Ladelisten-Seiten zu verstehen, bevor ein Parser dafuer gebaut wird.
"""

import os
import sys

import requests

BASE_URL = "https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste"


def main():
    username = os.environ.get("WDR_USER")
    password = os.environ.get("WDR_PASS")
    if not username or not password:
        sys.exit("Fehlt: WDR_USER / WDR_PASS.")

    session = requests.Session()
    session.auth = (username, password)
    session.headers["User-Agent"] = "dienstplan-sync/2.0"

    print(f"=== Verzeichnislisting {BASE_URL}/ ===")
    resp = session.get(BASE_URL + "/", timeout=30)
    print(f"HTTP {resp.status_code}")
    print(resp.text)

    print("\n=== NORDFRIES.html ===")
    resp = session.get(f"{BASE_URL}/NORDFRIES.html", timeout=30)
    print(f"HTTP {resp.status_code}")
    print(resp.text)


if __name__ == "__main__":
    main()
