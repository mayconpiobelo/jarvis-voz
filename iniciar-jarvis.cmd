@echo off
rem Inicia o Jarvis de voz em segundo plano (icone na bandeja) e o vigia que o reabre se ele cair.
rem Para encerrar de vez, use "Sair" no menu da bandeja (o vigia respeita essa escolha).
if exist "%~dp0.estado\sair" del "%~dp0.estado\sair" >nul 2>&1
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0jarvis.py"
start "" wscript.exe "%~dp0scripts\vigia.vbs"
