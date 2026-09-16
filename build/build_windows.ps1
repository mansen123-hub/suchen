[CmdletBinding()]
param(
    [string]$Python = "py",
    [string]$TesseractDirectory = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($env:OS -ne "Windows_NT") {
    throw "Der Installer muss nativ auf Windows gebaut werden."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if ((Split-Path -Leaf $Python) -in @("py", "py.exe")) {
        & $Python -3.12 -m venv .venv
    } else {
        & $Python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Die virtuelle Python-Umgebung konnte nicht erstellt werden." }
}
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements-dev.txt

if (-not $SkipTests) {
    & $VenvPython -m pytest
}

& $VenvPython build\generate_icon.py

if (-not $TesseractDirectory) {
    $DefaultTesseract = Join-Path $env:ProgramFiles "Tesseract-OCR"
    if (-not (Test-Path (Join-Path $DefaultTesseract "tesseract.exe"))) {
        if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
            throw "Tesseract wurde auf dem Build-Rechner nicht gefunden. Übergib -TesseractDirectory oder installiere Chocolatey."
        }
        choco install tesseract --version 5.5.0.20241111 -y --no-progress
    }
    $TesseractDirectory = $DefaultTesseract
}

$OcrTarget = Join-Path $ProjectRoot "build\vendor\ocr"
if (Test-Path $OcrTarget) { Remove-Item $OcrTarget -Recurse -Force }
New-Item -ItemType Directory -Path $OcrTarget | Out-Null

$RequiredRuntime = @("tesseract.exe", "*.dll")
foreach ($Pattern in $RequiredRuntime) {
    Copy-Item (Join-Path $TesseractDirectory $Pattern) $OcrTarget -Force
}
New-Item -ItemType Directory -Path (Join-Path $OcrTarget "tessdata") | Out-Null
foreach ($Language in @("deu.traineddata", "eng.traineddata", "osd.traineddata")) {
    $Source = Join-Path $TesseractDirectory "tessdata\$Language"
    if (-not (Test-Path $Source)) {
        $Url = "https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/$Language"
        Invoke-WebRequest -Uri $Url -OutFile (Join-Path $OcrTarget "tessdata\$Language")
    } else {
        Copy-Item $Source (Join-Path $OcrTarget "tessdata\$Language") -Force
    }
}

foreach ($ConfigName in @("configs", "tessconfigs")) {
    $ConfigSource = Join-Path $TesseractDirectory "tessdata\$ConfigName"
    if (Test-Path $ConfigSource) { Copy-Item $ConfigSource (Join-Path $OcrTarget "tessdata\$ConfigName") -Recurse -Force }
}

if (Test-Path dist) { Remove-Item dist -Recurse -Force }
if (Test-Path release) { Remove-Item release -Recurse -Force }
& $VenvPython -m PyInstaller --noconfirm --clean LieferscheinSuche.spec

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install innosetup -y --no-progress
        $Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
}
if (-not $Iscc) { throw "Inno Setup 6 wurde nicht gefunden." }

& $Iscc "installer\LieferscheinSuche.iss"
$SetupPath = Join-Path $ProjectRoot "release\LieferscheinSuche_Setup.exe"
if (-not (Test-Path $SetupPath)) { throw "Der Installer wurde nicht erzeugt." }
Get-FileHash $SetupPath -Algorithm SHA256 | Format-List
Write-Host "Fertig: $SetupPath"
