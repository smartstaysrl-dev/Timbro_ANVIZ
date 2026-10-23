@echo off
rem TIMBRA - installazione su un computer nuovo.
rem Doppio clic su questo file: scarica l'ultima versione pubblicata su
rem GitHub, la mette in C:\TIMBRA, crea l'icona sul desktop e in avvio
rem automatico, e apre il programma. Non serve installare Python.
rem Il resto del file e' PowerShell, dopo la riga col segnaposto.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = Get-Content -Raw -LiteralPath '%~f0'; Invoke-Expression ($t -split ('#' + 'POWERSHELL' + '#'), 2)[1]"
echo.
pause
exit /b
#POWERSHELL#
$ErrorActionPreference = 'Stop'
$destinazione = 'C:\TIMBRA'
$repo = 'smartstaysrl-dev/Timbro_ANVIZ'
Write-Host ''
Write-Host '  TIMBRA - installazione'
Write-Host '  ======================'
Write-Host ''

function Collegamento($cartella) {
    $l = (New-Object -ComObject WScript.Shell).CreateShortcut("$cartella\TIMBRA.lnk")
    $l.TargetPath = "$destinazione\python\pythonw.exe"
    $l.Arguments = 'gestione.py'
    $l.WorkingDirectory = "$destinazione\app"
    $l.IconLocation = "$destinazione\app\logo\timbra.ico"
    $l.Description = 'TIMBRA - presenze'
    $l.Save()
}

try {
    # Gia' installata: non si tocca niente. Gli aggiornamenti passano dal
    # bottone verde dentro il programma, che fa prima la copia dei dati.
    if (Test-Path "$destinazione\app") {
        Write-Host "  TIMBRA e' gia' installata in $destinazione."
        Write-Host "  Per aggiornarla usa il bottone verde Aggiorna dentro il programma."
        Write-Host "  Non tocco niente: archivio e impostazioni restano come sono."
        Start-Process "$destinazione\python\pythonw.exe" 'gestione.py' -WorkingDirectory "$destinazione\app"
        return
    }

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host '  Cerco l''ultima versione...'
    $versione = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'TIMBRA-installazione' }
    $pacchetto = $versione.assets | Where-Object { $_.name -like '*.zip' } | Select-Object -First 1
    if (-not $pacchetto) { throw "la versione $($versione.tag_name) non ha il pacchetto da scaricare" }

    $zip = Join-Path $env:TEMP $pacchetto.name
    $estratto = Join-Path $env:TEMP 'timbra-installazione'
    Write-Host "  Scarico la $($versione.tag_name) ($([math]::Round($pacchetto.size / 1MB)) MB)..."
    Invoke-WebRequest $pacchetto.browser_download_url -OutFile $zip -UseBasicParsing
    Write-Host '  Estraggo...'
    if (Test-Path $estratto) { Remove-Item $estratto -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $estratto
    if (-not (Test-Path "$estratto\TIMBRA\app\gestione.py")) { throw 'il pacchetto scaricato non ha la forma attesa' }

    New-Item -ItemType Directory -Path $destinazione -Force | Out-Null
    Copy-Item "$estratto\TIMBRA\*" $destinazione -Recurse -Force
    Remove-Item $zip, $estratto -Recurse -Force -ErrorAction SilentlyContinue

    Collegamento $destinazione
    Collegamento ([Environment]::GetFolderPath('Desktop'))
    Collegamento ([Environment]::GetFolderPath('Startup'))

    Write-Host ''
    Write-Host "  Fatto. TIMBRA $($versione.tag_name) e' in $destinazione."
    Write-Host '  - icona TIMBRA sul desktop'
    Write-Host '  - parte da sola quando si accende il computer'
    Write-Host '  Primo passo nel programma: Impostazioni, Cerca il terminale in rete.'
    Write-Host '  Codice di sblocco di fabbrica: 12345 (da cambiare subito).'
    Start-Process "$destinazione\python\pythonw.exe" 'gestione.py' -WorkingDirectory "$destinazione\app"
}
catch {
    Write-Host ''
    Write-Host "  INSTALLAZIONE NON RIUSCITA: $($_.Exception.Message)"
    Write-Host '  Serve la connessione a internet. Il computer non e'' stato modificato'
    Write-Host '  oltre alla cartella C:\TIMBRA, se era gia'' stata creata.'
}
