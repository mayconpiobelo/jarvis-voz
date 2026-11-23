<#
.SYNOPSIS
  Baixa os modelos do Kokoro (voz) para a pasta models\ e confere o tamanho de cada arquivo.
  O modelo do Whisper (fala -> texto) e baixado sozinho na primeira execucao (~460 MB, "small").
#>
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force models | Out-Null

$base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'
$arquivos = @(
  @{ nome = 'kokoro-v1.0.onnx'; bytes = 325532387 },
  @{ nome = 'voices-v1.0.bin';  bytes = 28214398 }
)
$ProgressPreference = 'SilentlyContinue'   # o progresso do PowerShell 5.1 deixa o download muito lento
foreach ($a in $arquivos) {
  $dest = Join-Path models $a.nome
  if ((Test-Path $dest) -and ((Get-Item $dest).Length -eq $a.bytes)) { Write-Host "$($a.nome): ja baixado." ; continue }
  Write-Host "Baixando $($a.nome) (~$([math]::Round($a.bytes/1MB)) MB)..."
  Invoke-WebRequest "$base/$($a.nome)" -OutFile $dest -UseBasicParsing
  $tam = (Get-Item $dest).Length
  if ($tam -ne $a.bytes) { Remove-Item $dest -Force; throw "$($a.nome): tamanho inesperado ($tam bytes, esperado $($a.bytes)). Download removido; tente de novo." }
  Write-Host "$($a.nome): ok."
}
Write-Host 'Modelos de voz prontos em models\.' -ForegroundColor Green
