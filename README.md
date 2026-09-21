# Lieferschein-Suche 1.2

Lokale Windows-Desktop-Anwendung zum Indexieren und Durchsuchen von PDF-Lieferscheinen. Text-PDFs werden direkt ausgelesen; reine Scan-PDFs werden automatisch und ausschließlich lokal mit dem mitgelieferten Tesseract-OCR verarbeitet.

## Funktionen

- lokale Ordner, Netzlaufwerke und UNC-Pfade
- optionale Unterordner-Suche
- inkrementeller SQLite-Suchindex (nur neue/geänderte Dateien)
- automatische Ordnerüberwachung
- OCR Deutsch/Englisch nur bei fehlender Textschicht
- Trefferliste, integrierte Vorschau und Hervorhebung
- Öffnen der PDF bzw. des Speicherorts im Explorer
- Fortschritt, Abbruch, Fehlerprotokoll und kompletter Neuaufbau
- keine Cloud-Übertragung

## Für sehr große PDF-Bestände optimiert

Version 1.2 ist für Bestände mit mehr als 100.000 PDFs ausgelegt und bietet zusätzlich eine präzise Carl-Eichhorn-Suche:

- Standardmäßig zählen nur exakte Übereinstimmungen zwischen Palettenkonto-Belegnummer und dem Feld `Lieferschein-Nr.`.
- Das Dokument muss als Carl-Eichhorn-Lieferschein erkannt werden.
- Andere Zahlen wie Datum, Kunden-Nr. oder `Unsere Lief.-Nr. 70124` werden nicht als Treffer ausgegeben.
- Die präzise Einschränkung kann für eine erweiterte Suche abgeschaltet werden.

- parallele PDF-Verarbeitung mit automatisch 2–8 Prozessen
- Tesseract je Prozess auf einen CPU-Thread begrenzt, damit der Rechner ansprechbar bleibt
- schnelle Dateierfassung über `scandir` ohne doppelten Metadatenzugriff
- gebündelte SQLite-Transaktionen statt eines Schreibvorgangs pro PDF
- eigener indexierter Nummernspeicher für sofortige Lieferscheinsuchen
- Anzeige von Durchsatz und geschätzter Restzeit
- Fortsetzen nach Abbruch oder Neustart durch den dauerhaften Zwischenstand
- Dateiüberwachung verarbeitet ausschließlich betroffene PDFs statt den Gesamtordner erneut zu scannen

Für die erste Indexierung eines sehr großen Bestands sollte der PDF-Ordner möglichst auf einer lokalen SSD liegen. Danach werden nur neue oder geänderte Dateien verarbeitet.

## Entwicklung

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m lieferschein_suche
```

Für OCR im Entwicklungsmodus kann `TESSERACT_CMD` auf eine lokale `tesseract.exe` zeigen. Im fertigen Build wird Tesseract unter `ocr\` gebündelt.

## Windows-Installer bauen

Auf Windows 10/11 in einer PowerShell mit Administratorrechten:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build\build_windows.ps1
```

Das Skript installiert ausschließlich Build-Werkzeuge auf dem Build-Rechner, bündelt Tesseract einschließlich `deu` und `eng`, erstellt die eigenständige Anwendung und baut anschließend mit Inno Setup:

`release\LieferscheinSuche_Setup.exe`

Ein normaler Endbenutzer benötigt weder Python noch Tesseract noch weitere Laufzeitumgebungen.

## Datenschutz

Die Anwendung enthält keine Netzwerk- oder Telemetrie-Funktion. PDFs, extrahierter Text, OCR-Daten, Einstellungen und Protokolle bleiben unter `%LOCALAPPDATA%\LieferscheinSuche` auf dem jeweiligen Rechner.
