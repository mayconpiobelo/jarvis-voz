<#
.SYNOPSIS
  Instala o Jarvis (ambiente Python, dependencias, configuracao e modelos de voz).
.DESCRIPTION
  Requisitos: Windows 10/11, Python 3.11 a 3.13 no PATH e o Claude Code CLI instalado e logado
  (rode `claude auth login` uma vez). O overlay (esfera flutuante) e opcional e exige Rust + MSVC.
.EXAMPLE
  .\scripts\instalar.ps1                 # instala tudo, inclusive os modelos de voz (~340 MB)
  .\scripts\instalar.ps1 -SemModelos     # pula o download dos modelos
  .\scripts\instalar.ps1 -ComOverlay     # tambem compila o overlay
#>
param([switch]$SemModelos, [switch]$ComOverlay)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Passo($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }

Passo 'Verificando Python'
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw 'Python nao encontrado. Instale o Python 3.11 a 3.13 (https://www.python.org) e marque "Add to PATH".' }
$v = [version](& python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ($v -lt [version]'3.11' -or $v -gt [version]'3.13') { throw "Python $v nao suportado. Use 3.11 a 3.13." }
Write-Host "Python $v"

Passo 'Criando o ambiente virtual (.venv) e instalando dependencias'
if (-not (Test-Path .venv\Scripts\python.exe)) { & python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependencias.' }

Passo 'Configuracao'
if (-not (Test-Path config.json)) {
  Copy-Item config.example.json config.json
  Write-Host 'config.json criado a partir do exemplo. EDITE: owner_name, hotkey, voz (kokoro_*) e permissoes.' -ForegroundColor Yellow
} else { Write-Host 'config.json ja existe (mantido).' }

if (-not $SemModelos) { Passo 'Baixando modelos de voz'; & "$PSScriptRoot\baixar-modelos.ps1" }
if ($ComOverlay)      { Passo 'Compilando o overlay';    & "$PSScriptRoot\compilar-overlay.ps1" }

Passo 'Claude Code CLI'
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) { Write-Warning 'O comando "claude" nao foi encontrado. Instale o Claude Code e ajuste "claude_exe" no config.json.' }
else { & claude auth status 2>$null; Write-Host 'Se "loggedIn" for false, rode: claude auth login' }

Write-Host "`nPronto. Para iniciar: .\iniciar-jarvis.cmd   (atalho padrao: Ctrl+Alt+J)" -ForegroundColor Green
