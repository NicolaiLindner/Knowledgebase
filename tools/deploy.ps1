# deploy.ps1 - bringt eine Datenbank auf den Sollzustand aus sql/config und
# sql/objects (Modul Datenbank). Wird vom NUTZER in einer PowerShell mit
# Schreibrechten ausgefuehrt. Der KI-Agent ruft es nie auf - er hat ueber
# tools/sql.py nur Leserechte (kb_reader) und prueft danach mit
# python tools/kb_drift.py, ob Datei und Datenbank uebereinstimmen.
#
# Die Reihenfolge steht in sql/deploy-reihenfolge.txt (eine Zeile je Datei,
# Abhaengigkeiten zuerst). Zeilen, die mit EXEC beginnen, sind Prozeduraufrufe
# und laufen nur mit -MitExec. Leerzeilen und # Kommentare werden ignoriert.
#
# Aufruf (Repo-Wurzel):
#   .\tools\deploy.ps1 -Server "host\instanz" -Database "MeineDB"           # Windows-Anmeldung
#   .\tools\deploy.ps1 -Server "host\instanz" -Database "MeineDB" -WhatIf   # nur Reihenfolge zeigen
#   .\tools\deploy.ps1 -Server "host\instanz" -Database "MeineDB" -MitExec  # auch EXEC-Zeilen
#
# sqlcmd laeuft mit -I (QUOTED_IDENTIFIER ON wie in SSMS) und -f 65001 (UTF-8);
# ohne -I scheitert CREATE INDEX (Fehler 1934). Die Dateien tragen kein USE -
# die Zieldatenbank kommt allein aus -Database.
#
# Nicht enthalten: sql/migrations/ (einmalige Uebergaenge, nie als Sollstand).

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$Database,
    [switch]$MitExec
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$listFile = Join-Path $root "sql/deploy-reihenfolge.txt"
if (-not (Test-Path $listFile)) { throw "sql/deploy-reihenfolge.txt fehlt." }

$order = @(Get-Content -Encoding UTF8 $listFile |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") })
if ($order.Count -eq 0) { Write-Host "sql/deploy-reihenfolge.txt ist leer - nichts zu tun."; return }

$sqlcmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
if (-not $sqlcmd) { throw "sqlcmd nicht gefunden - Dateien in der Reihenfolge aus sql/deploy-reihenfolge.txt in SSMS ausfuehren." }

function Invoke-Step([string]$Label, [scriptblock]$Action) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $Action | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Abbruch bei $Label (Exit $LASTEXITCODE)." }
    Write-Host ("  {0}  [{1:n0} s]" -f $Label, $sw.Elapsed.TotalSeconds)
}

Write-Host "Ziel: $Server / $Database"
$i = 0
foreach ($line in $order) {
    $i++
    $label = "{0,2}/{1}  {2}" -f $i, $order.Count, $line
    if ($line -match '^EXEC\s') {
        if (-not $MitExec) { Write-Host "  $label  (uebersprungen, -MitExec fehlt)"; continue }
        if ($PSCmdlet.ShouldProcess($line, "sqlcmd -Q")) {
            Invoke-Step $label { & sqlcmd -S $Server -d $Database -E -I -b -Q "$line;" }
        } else { Write-Host "  $label" }
        continue
    }
    $path = Join-Path $root $line
    if (-not (Test-Path $path)) { throw "Datei fehlt: $line" }
    if ($PSCmdlet.ShouldProcess($line, "sqlcmd -i")) {
        Invoke-Step $label { & sqlcmd -S $Server -d $Database -E -I -b -f 65001 -i $path }
    } else { Write-Host "  $label" }
}

Write-Host "Fertig. Pruefung: python tools/kb_drift.py"
