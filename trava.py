#!/usr/bin/env python3
"""Trava do Jarvis: o Claude Code roda este script ANTES de cada ferramenta (hook PreToolUse).

- Ler, buscar e consultar passam direto.
- Acoes que saem para fora ou mexem em coisas importantes (enviar e-mail/Teams, criar convites,
  alterar o SharePoint, escrever fora da pasta do usuario, comandos que mandam dados para a rede)
  so passam se o usuario confirmou por voz: o jarvis.py grava .estado/confirmado (com a hora de
  validade) durante aquele unico pedido. Sem confirmacao, sai com codigo 2 e o Claude recebe
  a orientacao de dizer o que vai fazer e perguntar "Confirma, senhor?".
- Apagar dados e comandos destrutivos NAO passam por aqui: ficam bloqueados de vez (deny_always
  no config.json) e nem chegam a ser oferecidos ao Claude.

Nao e uma caixa de areia: e uma lista de protecao. Revise antes de liberar ferramentas novas.
So usa a biblioteca padrao do Python.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ESTADO = BASE / ".estado"
CFG: dict = {}


def recarregar_config() -> None:
    """(Re)le config.json; sem config, so aplica as regras gerais. O servico do Jarvis chama isto a cada pedido."""
    global CFG
    CFG = {}
    for nome in ("config.json", "config.example.json"):
        try:
            CFG = json.loads((BASE / nome).read_text(encoding="utf-8"))
            return
        except Exception:
            continue


recarregar_config()


class Barrado(Exception):
    """A acao precisa de confirmacao por voz (ou a entrada nao pode ser verificada): `mensagem` orienta o Claude."""

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem

# Ferramentas nativas que sempre passam (somente leitura / organizacao interna)
LIVRES = {
    "Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch", "TodoWrite", "Skill", "Task", "Agent",
    "ToolSearch", "ListMcpResourcesTool", "ReadMcpResourceTool", "BashOutput", "KillShell",
    "NotebookRead", "ExitPlanMode", "EnterPlanMode",
}
# Ferramentas nativas que agem para fora ou agendam coisas
PEDEM_CONFIRMACAO_NATIVAS = {
    "RemoteTrigger", "CronCreate", "CronDelete", "SendMessage", "SendToProject", "SendToProjectContext",
    "PushNotification",
}

MCP_ARRISCADO = re.compile(
    r"(send|create|update|delete|trash|forward|reply|respond|move|copy|rename|upload|set_|add_|remove|"
    r"apply|publish|post|write|save|edit|schedule|invite|share|modify|label|filter|merge|import|"
    r"enable|disable|archive|cancel|transfer|click|type|key|drag|mouse|scroll|open_application|"
    r"hold_key|write_clipboard)",
    re.I,
)
MCP_LEITURA = re.compile(
    r"(list|get|read|search|find|query|fetch|show|view|status|info|count|describe|download|"
    r"screenshot|zoom|cursor_position|wait|who_am_i|suggest|guide|outline|timeline|corpus|"
    r"session_start|work_state_read)",
    re.I,
)

# Comandos de terminal que mandam dados para fora ou mudam o sistema (precisam de confirmacao)
SHELL_PEDE_CONFIRMACAO = [
    r"\bcurl\b.*(-X\s*(POST|PUT|PATCH|DELETE)|\s-d\b|--data|\s-F\b|--form|\s-T\b|--upload-file)",
    r"Invoke-(RestMethod|WebRequest)\b.*-Method\s+(Post|Put|Patch|Delete)",
    r"Invoke-(RestMethod|WebRequest)\b.*-Body",
    r"\b(scp|sftp|ftp|rsync)\b",
    r"Send-MailMessage",
    r"\bgh\s+\w+\s+(create|delete|merge|edit|close|comment)\b",
    r"\bnpm\s+publish\b",
    r"Set-ExecutionPolicy",
    r"\breg(\.exe)?\s+(add|delete|import)\b",
    r"Set-ItemProperty\s+.*HK(LM|CU)",
    r"New-ItemProperty\s+.*HK(LM|CU)",
    r"schtasks(\.exe)?\s+/create",
    r"Register-ScheduledTask",
    r"\bnet\s+(user|localgroup)\b",
    r"RunAs",
    r"\b(winget|choco|scoop)\s+(install|uninstall|upgrade|remove)\b",
]

CAMINHOS_SENSIVEIS = re.compile(r"[\\/](\.claude|\.ssh|\.aws|appdata|start menu)([\\/]|$)", re.I)


def log(msg: str) -> None:
    try:
        ESTADO.mkdir(exist_ok=True)
        with (ESTADO / "trava.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def confirmado() -> bool:
    """Ha confirmacao por voz valida (nao expirada) para este pedido?"""
    try:
        return float((ESTADO / "confirmado").read_text().strip()) > time.time()
    except (OSError, ValueError):
        return False


def barrar(o_que: str) -> None:
    log(f"BARRADO: {o_que}")
    raise Barrado(
        f"TRAVA DO JARVIS: {o_que} precisa da confirmacao do usuario por voz. NAO execute agora e NAO tente "
        "outro caminho para fazer a mesma coisa. Responda em UMA frase dizendo exatamente o que vai fazer "
        "(com destinatario ou destino, quando houver) e termine com 'Confirma, senhor?'."
    )


def dentro_do_usuario(caminho: str) -> bool:
    if not caminho:
        return False
    real = os.path.realpath(os.path.expanduser(caminho))
    casa = os.path.realpath(os.path.expanduser("~"))
    return os.path.normcase(real).startswith(os.path.normcase(casa) + os.sep) or os.path.normcase(real) == os.path.normcase(casa)


def avaliar(dados: dict) -> None:
    """Decide uma ferramenta: volta sem nada se pode passar; levanta Barrado se precisa de confirmacao."""
    nome = dados.get("tool_name", "")
    entrada = dados.get("tool_input") or {}

    if nome in LIVRES or confirmado():
        return

    if nome in PEDEM_CONFIRMACAO_NATIVAS:
        barrar(f"a ferramenta '{nome}'")

    if nome.startswith("mcp__"):
        acao = nome.split("__")[-1]
        if any(nome.startswith(p) for p in CFG.get("livres_prefixos", [])) or acao in CFG.get("livres_extra", []):
            return
        if nome in CFG.get("deny_outward", []):
            barrar(f"a acao '{acao}'")
        if MCP_ARRISCADO.search(acao):
            barrar(f"a acao '{acao}'")
        if not MCP_LEITURA.search(acao):  # desconhecida: por seguranca, pede confirmacao
            barrar(f"a acao '{acao}'")
        return

    if nome in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        caminho = entrada.get("file_path") or entrada.get("notebook_path") or ""
        if not dentro_do_usuario(caminho) or CAMINHOS_SENSIVEIS.search(os.path.realpath(os.path.expanduser(caminho))):
            barrar("escrever fora da sua pasta ou em uma pasta sensivel do sistema")
        return

    if nome in ("Bash", "PowerShell"):
        cmd = entrada.get("command", "") or ""
        if any(re.search(p, cmd, re.I | re.S) for p in SHELL_PEDE_CONFIRMACAO):
            barrar("esse comando (envia dados para fora ou altera o sistema)")
        return


MSG_ILEGIVEL = ("TRAVA DO JARVIS: nao consegui verificar esta acao e por seguranca ela foi barrada. "
                "Avise o usuario em uma frase e nao tente outro caminho.")


def main() -> None:
    """Modo linha de comando (hook como script): le o JSON do stdin; codigo 2 + stderr = barrado."""
    try:
        dados = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", errors="replace"))
        if not isinstance(dados, dict):
            raise ValueError("entrada nao e um objeto")
    except ValueError as e:
        # Falha FECHADA: se nao da para entender o pedido, nao deixa passar.
        log(f"ENTRADA ILEGIVEL, barrado por seguranca: {e}")
        sys.stderr.buffer.write(MSG_ILEGIVEL.encode("utf-8"))
        sys.exit(2)
    try:
        avaliar(dados)
    except Barrado as b:
        sys.stderr.buffer.write(b.mensagem.encode("utf-8"))
        sys.exit(2)


if __name__ == "__main__":
    main()
