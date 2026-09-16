# Qualitätssicherung

## Lokal erfolgreich ausgeführt

Stand: 16.09.2026, Quellversion 1.0.0

- Syntaxprüfung aller Python-Module
- UI-Starttest mit Qt im Headless-Modus
- normale Text-PDF
- mehrseitige PDF
- reine Scan-PDF mit echter lokaler Tesseract-OCR
- automatische OCR-Auswahl nur bei unbrauchbarer Textschicht
- Lieferscheinnummer mit Bindestrichen und Suche ohne Bindestriche
- Dateiname mit Leerzeichen und Sonderzeichen
- erneuter Lauf ohne Änderungen (Datei wird übersprungen)
- geänderte PDF (wird neu verarbeitet)
- gelöschte PDF (wird aus dem Index entfernt)
- 30 PDF-Dateien in einem Durchlauf
- Neustart bzw. erneutes Öffnen mit vorhandenem SQLite-Index
- OCR-Hervorhebung über mehrere erkannte Wortsegmente

Ergebnis: **8 automatisierte Tests erfolgreich**.

## Im Windows-Build automatisiert

Die Datei `.github/workflows/windows-installer.yml` führt zusätzlich auf einem nativen Windows-System aus:

1. Installation der Build-Abhängigkeiten
2. vollständigen Testlauf
3. PyInstaller-Build
4. Inno-Setup-Build
5. stille Installation des erzeugten Setups
6. Prüfung auf gebündelte `tesseract.exe`, `deu.traineddata` und `eng.traineddata`
7. Start- und Prozessprüfung der installierten Anwendung
8. Bereitstellung von `LieferscheinSuche_Setup.exe` als Build-Artefakt

## Vor Freigabe im Firmennetz manuell prüfen

- Lesen und Überwachen des konkreten produktiven UNC-Pfads
- Zugriffsverhalten mit den tatsächlichen AD-/Freigabeberechtigungen
- sehr großer Realbestand mit typischen Scanqualitäten
- Virenscanner-/Application-Control-Freigabe für den nicht signierten Installer
- Update von Version 1.0.0 auf eine spätere Testversion

Hinweis: Code Signing ist bewusst nicht vorgetäuscht. Für eine unternehmensweite Verteilung sollte der Installer mit einem vertrauenswürdigen Code-Signing-Zertifikat signiert werden.

