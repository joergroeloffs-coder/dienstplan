#!/usr/bin/env python3
"""
Desktop-App: Fahrplan der aktuellen (bzw. naechsten) Kalenderwoche fuer ein
gewaehltes Schiff markieren, als Vorschau anzeigen und erst nach Bestaetigung
per E-Mail verschicken.

Start: python3 fahrplan_gui.py

Zugangsdaten (WDR-Verzeichnis, SMTP) und die Empfaenger-Adressen je Schiff
werden beim ersten Start abgefragt und lokal in config.json gespeichert
(nicht Teil des Git-Repos, siehe .gitignore).
"""

import io
import json
import smtplib
import sys
import tkinter as tk
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from tkinter import messagebox, simpledialog

import pdfplumber
import pymupdf
import requests

import dienstplan_cloud_sync as ds
from fahrplan_pdf_mail import markiere_pdf

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
ICON_PATH = HERE / "assets" / "icon.png"

# Kuerzel-Buttons in der gewuenschten Reihenfolge -> voller Schiffsname
SCHIFF_BUTTONS = [
    ("S", ds.FAHRPLAN_SCHIFF_KUERZEL["S"]),
    ("N", ds.FAHRPLAN_SCHIFF_KUERZEL["N"]),
    ("NA", ds.FAHRPLAN_SCHIFF_KUERZEL["NA"]),
    ("U", ds.FAHRPLAN_SCHIFF_KUERZEL["U"]),
]

PREVIEW_ZOOM = 1.6  # Rendering-Aufloesung der Vorschauseiten


def lade_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def speichere_config(config):
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def frage_pflichtfeld(parent, titel, text, show=None):
    while True:
        wert = simpledialog.askstring(titel, text, show=show, parent=parent)
        if wert is None:
            return None
        wert = wert.strip()
        if wert:
            return wert


class FahrplanApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fahrplan Versand")
        self.geometry("720x640")
        self.minsize(560, 480)

        if ICON_PATH.exists():
            self._icon_img = tk.PhotoImage(file=str(ICON_PATH))
            self.iconphoto(True, self._icon_img)

        self.config_data = lade_config()

        self.aktuelles_schiff = None
        self.aktuelles_pdf = None
        self.aktueller_dateiname = None
        self.aktuelle_kw_info = None
        self._preview_images = []  # Referenzen halten, sonst Garbage Collection

        self._baue_kopfbereich()
        self._baue_vorschaubereich()
        self._baue_statuszeile()

    # ---------- UI-Aufbau ----------

    def _baue_kopfbereich(self):
        rahmen = tk.Frame(self, padx=16, pady=16)
        rahmen.pack(fill="x")

        tk.Label(
            rahmen, text="Fahrplan markieren und versenden",
            font=("Helvetica", 15, "bold"),
        ).pack(anchor="w")
        tk.Label(
            rahmen, text="Schiff waehlen, Vorschau pruefen, dann senden.",
            fg="#555",
        ).pack(anchor="w", pady=(0, 10))

        knopf_rahmen = tk.Frame(rahmen)
        knopf_rahmen.pack(anchor="w")

        farben = {"S": "#115e99", "N": "#0f7a5c", "NA": "#8a5b1f", "U": "#7a2c8a"}
        for kuerzel, schiff in SCHIFF_BUTTONS:
            box = tk.Frame(knopf_rahmen)
            box.pack(side="left", padx=8)
            btn = tk.Button(
                box, text=kuerzel, width=4, height=2,
                font=("Helvetica", 14, "bold"),
                fg="white", bg=farben.get(kuerzel, "#333"),
                activeforeground="white", activebackground=farben.get(kuerzel, "#333"),
                relief="raised", bd=2,
                command=lambda s=schiff, k=kuerzel: self.schiff_gewaehlt(s, k),
            )
            btn.pack()
            tk.Label(box, text=schiff.title(), font=("Helvetica", 8), fg="#666").pack()

    def _baue_vorschaubereich(self):
        aussen = tk.Frame(self, bd=1, relief="sunken")
        aussen.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self.canvas = tk.Canvas(aussen, bg="#e8e8e8")
        scrollbar = tk.Scrollbar(aussen, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.preview_frame = tk.Frame(self.canvas, bg="#e8e8e8")
        self.preview_window = self.canvas.create_window(
            (0, 0), window=self.preview_frame, anchor="nw"
        )
        self.preview_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self.preview_window, width=e.width),
        )

        self.platzhalter_label = tk.Label(
            self.preview_frame, text="Noch keine Vorschau - Schiff oben waehlen.",
            bg="#e8e8e8", fg="#777", pady=40,
        )
        self.platzhalter_label.pack(fill="x")

        aktion_rahmen = tk.Frame(self, padx=16)
        aktion_rahmen.pack(fill="x", pady=(0, 8))
        self.senden_button = tk.Button(
            aktion_rahmen, text="Senden", state="disabled",
            font=("Helvetica", 11, "bold"), bg="#1a8a3d", fg="white",
            activebackground="#1a8a3d", activeforeground="white",
            padx=14, pady=6, command=self.senden,
        )
        self.senden_button.pack(side="right")
        self.abbrechen_button = tk.Button(
            aktion_rahmen, text="Abbrechen", state="disabled",
            padx=14, pady=6, command=self.zuruecksetzen,
        )
        self.abbrechen_button.pack(side="right", padx=(0, 8))

    def _baue_statuszeile(self):
        self.status_var = tk.StringVar(value="Bereit.")
        tk.Label(
            self, textvariable=self.status_var, anchor="w",
            bd=1, relief="sunken", padx=8,
        ).pack(fill="x", side="bottom")

    # ---------- Config-Handling ----------

    def hole_wdr_zugang(self):
        user = self.config_data.get("wdr_user")
        pw = self.config_data.get("wdr_pass")
        if user and pw:
            return user, pw
        user = frage_pflichtfeld(self, "WDR-Zugang", "Benutzername Fahrplan-Verzeichnis:")
        if not user:
            return None, None
        pw = frage_pflichtfeld(self, "WDR-Zugang", "Passwort Fahrplan-Verzeichnis:", show="*")
        if not pw:
            return None, None
        self.config_data["wdr_user"] = user
        self.config_data["wdr_pass"] = pw
        speichere_config(self.config_data)
        return user, pw

    def hole_smtp_zugang(self):
        felder = ("smtp_host", "smtp_port", "smtp_user", "smtp_pass")
        if all(self.config_data.get(f) for f in felder):
            return (
                self.config_data["smtp_host"],
                int(self.config_data["smtp_port"]),
                self.config_data["smtp_user"],
                self.config_data["smtp_pass"],
            )
        host = frage_pflichtfeld(self, "SMTP-Zugang", "SMTP-Server (z.B. smtp.web.de):")
        if not host:
            return None
        port = frage_pflichtfeld(self, "SMTP-Zugang", "SMTP-Port (587 oder 465):") or "587"
        smtp_user = frage_pflichtfeld(self, "SMTP-Zugang", "Absender-E-Mail-Adresse:")
        if not smtp_user:
            return None
        smtp_pass = frage_pflichtfeld(self, "SMTP-Zugang", "Passwort / App-Passwort:", show="*")
        if not smtp_pass:
            return None
        self.config_data["smtp_host"] = host
        self.config_data["smtp_port"] = int(port)
        self.config_data["smtp_user"] = smtp_user
        self.config_data["smtp_pass"] = smtp_pass
        speichere_config(self.config_data)
        return host, int(port), smtp_user, smtp_pass

    def hole_empfaenger(self, kuerzel, schiff):
        empfaenger = self.config_data.setdefault("empfaenger", {})
        adresse = empfaenger.get(kuerzel)
        if adresse:
            return adresse
        adresse = frage_pflichtfeld(
            self, f"E-Mail-Adresse fuer {schiff}",
            f"An welche Adresse soll der Fahrplan fuer {schiff} ({kuerzel}) gehen?",
        )
        if not adresse:
            return None
        empfaenger[kuerzel] = adresse
        speichere_config(self.config_data)
        return adresse

    # ---------- Ablauf ----------

    def schiff_gewaehlt(self, schiff, kuerzel):
        self.zuruecksetzen(nur_anzeige=True)
        self.status_var.set(f"Lade Fahrplan fuer {schiff} ...")
        self.update_idletasks()

        wdr_user, wdr_pass = self.hole_wdr_zugang()
        if not wdr_user:
            self.status_var.set("Abgebrochen (WDR-Zugang fehlt).")
            return

        try:
            session = requests.Session()
            session.auth = (wdr_user, wdr_pass)
            session.headers["User-Agent"] = "dienstplan-fahrplan-gui/1.0"

            heute = date.today()
            jahr, kw, _ = heute.isocalendar()

            index = ds.fetch_fahrplan_index(session)
            gefunden = ds.find_fahrplan_eintrag(index, jahr, kw)
            benutzte_kw = kw
            if not gefunden:
                # Aktuelle KW nicht gefunden -> naechste Woche versuchen.
                naechste = heute.fromordinal(heute.toordinal() + 7)
                jahr2, kw2, _ = naechste.isocalendar()
                gefunden = ds.find_fahrplan_eintrag(index, jahr2, kw2)
                if gefunden:
                    jahr, benutzte_kw = jahr2, kw2

            if not gefunden:
                messagebox.showerror(
                    "Kein Fahrplan gefunden",
                    f"Kein Fahrplan fuer KW {kw}/{jahr} (oder Folgewoche) gefunden.",
                )
                self.status_var.set("Kein Fahrplan gefunden.")
                return

            _, mtime, href, filename = gefunden
            resp = session.get(f"{ds.FAHRPLAN_BASE_URL}/{href}", timeout=30)
            if resp.status_code != 200 or resp.content[:4] != b"%PDF":
                raise RuntimeError(f"Download fehlgeschlagen: HTTP {resp.status_code}")

            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                abfahrten = ds.parse_fahrplan_pdf(pdf)

            markiert = markiere_pdf(resp.content, abfahrten, schiff)

            self.aktuelles_schiff = schiff
            self.aktuelles_kuerzel = kuerzel
            self.aktuelles_pdf = markiert
            self.aktueller_dateiname = f"Fahrplan_KW{benutzte_kw}_{kuerzel}_markiert.pdf"
            self.aktuelle_kw_info = (benutzte_kw, jahr, filename, mtime)

            self.zeige_vorschau(markiert)
            self.senden_button.config(state="normal")
            self.abbrechen_button.config(state="normal")
            self.status_var.set(
                f"Vorschau: {schiff}, KW {benutzte_kw}/{jahr} "
                f"(Quelle {filename}, Stand {mtime}). Pruefen und senden."
            )
        except SystemExit as exc:
            meldung = str(exc.code) if exc.code else "Unbekannter Fehler beim Laden."
            if "401" in meldung or "403" in meldung:
                # Vermutlich falsche/abgelaufene WDR-Zugangsdaten - erneut abfragen lassen.
                self.config_data.pop("wdr_user", None)
                self.config_data.pop("wdr_pass", None)
                speichere_config(self.config_data)
            messagebox.showerror("Fehler", meldung)
            self.status_var.set(f"Fehler: {meldung}")
        except Exception as exc:
            messagebox.showerror("Fehler", str(exc))
            self.status_var.set(f"Fehler: {exc}")

    def zeige_vorschau(self, pdf_bytes):
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
        self._preview_images.clear()

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        matrix = pymupdf.Matrix(PREVIEW_ZOOM, PREVIEW_ZOOM)
        for seite in doc:
            pix = seite.get_pixmap(matrix=matrix)
            photo = tk.PhotoImage(data=pix.tobytes("ppm"))
            self._preview_images.append(photo)
            label = tk.Label(self.preview_frame, image=photo, bd=1, relief="solid")
            label.pack(pady=8)
        doc.close()
        self.canvas.yview_moveto(0)

    def zuruecksetzen(self, nur_anzeige=False):
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
        self._preview_images.clear()
        self.platzhalter_label = tk.Label(
            self.preview_frame, text="Noch keine Vorschau - Schiff oben waehlen.",
            bg="#e8e8e8", fg="#777", pady=40,
        )
        self.platzhalter_label.pack(fill="x")
        self.senden_button.config(state="disabled")
        self.abbrechen_button.config(state="disabled")
        self.aktuelles_pdf = None
        if not nur_anzeige:
            self.status_var.set("Bereit.")

    def senden(self):
        if not self.aktuelles_pdf:
            return
        schiff = self.aktuelles_schiff
        kuerzel = self.aktuelles_kuerzel
        empfaenger = self.hole_empfaenger(kuerzel, schiff)
        if not empfaenger:
            self.status_var.set("Abgebrochen (keine Empfaenger-Adresse).")
            return

        smtp_zugang = self.hole_smtp_zugang()
        if not smtp_zugang:
            self.status_var.set("Abgebrochen (SMTP-Zugang fehlt).")
            return
        smtp_host, smtp_port, smtp_user, smtp_pass = smtp_zugang

        if not messagebox.askyesno(
            "Senden bestaetigen",
            f"Fahrplan fuer {schiff} an {empfaenger} senden?",
        ):
            return

        kw, jahr, quelle_datei, mtime = self.aktuelle_kw_info
        betreff = f"Fahrplan KW {kw}/{jahr} - {schiff} markiert"
        text = (
            f"Fahrplan fuer KW {kw}/{jahr}, Schiff {schiff} markiert.\n"
            f"Quelle: {quelle_datei}, Stand {mtime}.\n"
        )

        try:
            self._sende_mail(
                smtp_host, smtp_port, empfaenger, smtp_user, smtp_pass,
                betreff, text, self.aktuelles_pdf, self.aktueller_dateiname,
            )
            messagebox.showinfo("Versendet", f"Fahrplan an {empfaenger} gesendet.")
            self.status_var.set(f"Gesendet an {empfaenger}.")
            self.zuruecksetzen(nur_anzeige=True)
        except Exception as exc:
            messagebox.showerror("Fehler beim Versand", str(exc))
            self.status_var.set(f"Fehler beim Versand: {exc}")

    @staticmethod
    def _sende_mail(host, port, empfaenger, absender, passwort, betreff, text, pdf_bytes, dateiname):
        msg = EmailMessage()
        msg["Subject"] = betreff
        msg["From"] = absender
        msg["To"] = empfaenger
        msg.set_content(text)
        msg.add_attachment(
            pdf_bytes, maintype="application", subtype="pdf", filename=dateiname
        )
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as smtp:
                smtp.login(absender, passwort)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as smtp:
                smtp.starttls()
                smtp.login(absender, passwort)
                smtp.send_message(msg)


def main():
    try:
        app = FahrplanApp()
    except tk.TclError as exc:
        sys.exit(f"Konnte kein Fenster oeffnen (kein Display?): {exc}")
    app.mainloop()


if __name__ == "__main__":
    main()
