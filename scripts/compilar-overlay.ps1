<#
.SYNOPSIS
  Compila o overlay (esfera flutuante, Tauri/Rust). Requer Rust (https://rustup.rs) e as
  "Build Tools do Visual Studio" com a carga de trabalho "Desenvolvimento para desktop com C++".
  O WebView2 ja vem com o Windows 11.
#>
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'overlay\src-tauri')
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw 'Rust (cargo) nao encontrado. Instale via https://rustup.rs' }
cargo build --release --locked
if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o overlay.' }
$exe = Resolve-Path 'target\release\jarvis-overlay.exe'
Write-Host "Overlay compilado: $exe" -ForegroundColor Green
Write-Host 'O Jarvis o abre sozinho (config.json -> overlay). Para testar isolado: execute o .exe.'
