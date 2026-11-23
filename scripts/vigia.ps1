# Vigia do Jarvis: reabre o servico (jarvis.py) se ele cair. Nao reabre se voce escolheu "Sair" na bandeja
# (o Jarvis cria .estado\sair nesse caso) e desiste depois de 5 quedas em 10 minutos (evita laco se estiver quebrado).
# Texto so em ASCII de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.
$ErrorActionPreference = 'SilentlyContinue'
$repo = Split-Path $PSScriptRoot -Parent
$criado = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\JarvisVigia', [ref]$criado)
if (-not $criado) { exit }
$sair = Join-Path $repo '.estado\sair'
$pyw = Join-Path $repo '.venv\Scripts\pythonw.exe'
$script = Join-Path $repo 'jarvis.py'
$log = Join-Path $repo 'jarvis.log'
$quedas = New-Object System.Collections.ArrayList
while ($true) {
  Start-Sleep -Seconds 10
  if (Test-Path $sair) { continue }
  $rodando = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*jarvis.py*' }
  if ($rodando) { continue }
  $agora = Get-Date
  for ($i = $quedas.Count - 1; $i -ge 0; $i--) { if (($agora - $quedas[$i]).TotalMinutes -ge 10) { $quedas.RemoveAt($i) } }
  if ($quedas.Count -ge 5) {
    Add-Content -Path $log -Encoding UTF8 -Value ('{0:yyyy-MM-dd HH:mm:ss},000 ERROR vigia: 5 quedas em 10 minutos; parei de reabrir (veja .estado\jarvis_crash.log)' -f $agora)
    Start-Sleep -Seconds 600
    $quedas.Clear()
    continue
  }
  [void]$quedas.Add($agora)
  Add-Content -Path $log -Encoding UTF8 -Value ('{0:yyyy-MM-dd HH:mm:ss},000 WARNING vigia: o Jarvis nao estava rodando; reabrindo' -f $agora)
  Start-Process -FilePath $pyw -ArgumentList ('"' + $script + '"') -WorkingDirectory $repo -WindowStyle Hidden
}
