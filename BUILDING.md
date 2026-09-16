# Windows-Build und Veröffentlichung

## Voraussetzungen auf dem Build-Rechner

- Windows 10 oder Windows 11 (64 Bit)
- Python 3.12
- PowerShell
- Inno Setup 6
- Tesseract 5.5 (nur auf dem Build-Rechner; wird in die Anwendung kopiert)

Chocolatey kann Inno Setup und Tesseract durch das Build-Skript automatisch bereitstellen. Für den Endbenutzer gelten diese Voraussetzungen nicht.

## Ein Befehl

```powershell
.\build\build_windows.ps1
```

Optional mit bereits vorhandenem portablem OCR-Ordner:

```powershell
.\build\build_windows.ps1 -TesseractDirectory "C:\BuildTools\Tesseract-OCR"
```

Ausgabe:

```text
release\LieferscheinSuche_Setup.exe
```

## Versionswechsel

Bei einem Release müssen dieselbe Versionsnummer in diesen Dateien gepflegt werden:

- `lieferschein_suche/__init__.py`
- `pyproject.toml`
- `build/version_info.txt`
- `installer/LieferscheinSuche.iss`

Die `AppId` im Inno-Setup-Skript bleibt unverändert. Dadurch erkennt Windows spätere Versionen als Upgrade derselben Anwendung.

## Optionale Signierung

Für SmartScreen-freundliche Firmenverteilung sollten zuerst die Anwendungsdatei und anschließend das Setup signiert werden, beispielsweise mit `signtool.exe` und einem EV- oder organisationsintern vertrauten Zertifikat. Ein privater Signaturschlüssel gehört niemals in das Repository.

