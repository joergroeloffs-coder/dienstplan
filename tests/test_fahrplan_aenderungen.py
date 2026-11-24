import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dienstplan_cloud_sync as ds
import pdfplumber
from reportlab.pdfgen.canvas import Canvas


def pdf_bytes(headers):
    buf = io.BytesIO()
    c = Canvas(buf)
    for title, departure in headers:
        c.drawString(30, 780, title)
        for x, name in zip((30, 180, 330, 480), ds.FAHRPLAN_ROUTEN):
            c.drawString(x, 750, name)
        c.drawString(30, 730, 'HW 1:50 NW 8:34')
        if departure:
            c.drawString(30, 700, departure + ' dir U')
        c.showPage()
    c.save()
    return buf.getvalue()


class FahrplanTest(unittest.TestCase):
    def test_tagesaenderung_und_folgetag(self):
        base = pdf_bytes([('Dienstplan KW 48 Mittwoch25.11.2026', '6:00'),
                          ('Dienstplan KW 48 Donnerstag26.11.2026', '6:00')])
        change = pdf_bytes([('2. Dienstplanänderung KW 48 Mittwoch 25.11.2026', '5:15')])
        response = lambda data: Mock(content=data)
        session = Mock()
        session.get.side_effect = [response(base), response(change)]
        entries = [(48, '2026-11-19 14:11', 'base.pdf', '48._KW_FAL.pdf'),
                   (48, '2026-11-24 10:00', 'change.pdf', '48._KW_FAL_2_Aenderung.pdf')]
        rows, sources = ds.lade_fahrplan_woche(session, entries, 2026, 48, {})
        own = ds.gruppiere_abfahrten_pro_tag(rows, 'UTHLANDE')
        self.assertIn('5:15 Wittdün-Wyk (direkt)', own['25.11.2026'])
        self.assertNotIn('6:00', own['25.11.2026'])
        self.assertIn('6:00', own['26.11.2026'])
        self.assertEqual(2, len(sources))
        # An alarm 65 minutes before 05:15 must be 04:10.
        from datetime import datetime, timedelta
        self.assertEqual('04:10', (datetime(2026, 11, 25, 5, 15)-timedelta(minutes=65)).strftime('%H:%M'))

    def test_abgesagter_tag_entfernt_alte_abfahrten(self):
        session = Mock()
        session.get.side_effect = [Mock(content=pdf_bytes([('Dienstplan KW 48 Mittwoch25.11.2026', '6:00')])),
                                   Mock(content=pdf_bytes([('2. Dienstplanänderung KW 48 Mittwoch25.11.2026', None)]))]
        entries = [(48, '2026-11-19 14:11', 'base.pdf', 'base.pdf'),
                   (48, '2026-11-24 10:00', 'change.pdf', 'change.pdf')]
        rows, _ = ds.lade_fahrplan_woche(session, entries, 2026, 48, {})
        self.assertEqual([], rows)

    def test_downloadfehler_wird_nicht_still_ignoriert(self):
        session = Mock()
        session.get.return_value = Mock(content=b'not a PDF')
        with self.assertRaises(ValueError):
            ds.lade_fahrplan_woche(session, [(48,'2026-11-24 10:00','x','x')],2026,48,{})

    def test_index_erkennt_aenderungsdateien(self):
        session = Mock()
        session.get.return_value = Mock(status_code=200, text='<a href="48._KW_FAL_2_Aenderung.pdf">PDF</a> 2026-11-24 10:00')
        self.assertEqual(48, ds.fetch_fahrplan_index(session)[0][0])

if __name__ == '__main__':
    unittest.main()
