@echo off
rem Inicia o Jarvis de voz em segundo plano (icone na bandeja). Atalho: ver config.json
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0jarvis.py"
