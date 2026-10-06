# accdb_import.ps1 — Hilfsskript fuer tools/sql.py --accdb. Nicht direkt aufrufen.
#
# Importiert eine CSV (mit schema.ini daneben) in eine Access-Tabelle, indem
# MSACCESS.EXE per COM gesteuert wird. Warum so umstaendlich: Der Text-ISAM
# von ACE liegt bei Click-to-Run-Office im virtualisierten Dateisystem und ist
# nur INNERHALB eines Office-Prozesses ladbar; aus Python/DAO heraus liefert
# er "Operation wird fuer diesen Objekttyp nicht unterstuetzt". Der
# ODBC-Weg (Zeile fuer Zeile) schafft ~700 Zeilen/s, dieser ~200.000 Zeilen/s.
#
# Auftrag kommt als JSON-Datei:
#   { accdb, table, csvDir, csvName, columns: [{name, ddl}], indexes: [[col,..],..] }
param([Parameter(Mandatory = $true)][string]$Job)

$ErrorActionPreference = "Stop"
$j = Get-Content -Raw -Encoding UTF8 $Job | ConvertFrom-Json

$app = New-Object -ComObject Access.Application
$app.Visible = $false
# msoAutomationSecurityLow, nur fuer diese COM-Instanz: Eine vorhandene Datei
# wuerde sonst im "deaktivierten Modus" geoeffnet, in dem Access externe
# Datenquellen (den Text-Import) mit demselben ISAM-Fehler ablehnt.
$app.AutomationSecurity = 1
try {
    if (Test-Path $j.accdb) { $app.OpenCurrentDatabase($j.accdb) }
    else                    { $app.NewCurrentDatabase($j.accdb) }
    $db = $app.CurrentDb()

    foreach ($t in $db.TableDefs) {
        if ($t.Name -ieq $j.table) { throw "Tabelle [$($j.table)] existiert schon in $($j.accdb) - nichts ueberschrieben." }
    }

    $colDdl  = ($j.columns | ForEach-Object { "[" + $_.name + "] " + $_.ddl }) -join ", "
    $colList = ($j.columns | ForEach-Object { "[" + $_.name + "]" }) -join ", "
    $db.Execute("CREATE TABLE [$($j.table)] ($colDdl)")

    $src = "[Text;HDR=Yes;FMT=Delimited;DATABASE=$($j.csvDir)].[" + ($j.csvName -replace '\.', '#') + "]"
    $db.Execute("INSERT INTO [$($j.table)] ($colList) SELECT $colList FROM $src")
    $rows = $db.RecordsAffected

    foreach ($ix in $j.indexes) {
        $cols = @($ix)
        $name = ("ix_" + $j.table + "_" + ($cols -join "_"))
        if ($name.Length -gt 64) { $name = $name.Substring(0, 64) }
        $list = ($cols | ForEach-Object { "[" + $_ + "]" }) -join ", "
        $db.Execute("CREATE INDEX [$name] ON [$($j.table)] ($list)")
    }
    Write-Output "ROWS=$rows"
}
finally {
    try { $app.CloseCurrentDatabase() } catch {}
    $app.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
