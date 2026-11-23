"""A trava (hook PreToolUse) e o que ela deixa passar ou barra. Roda trava.py de verdade, como o Claude Code faz."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
M = "mcp__claude_ai_Microsoft_365__"
TOKEN = RAIZ / ".estado" / "confirmado"


def rodar(ferramenta: str, entrada: dict | None = None, bruto: bytes | None = None) -> subprocess.CompletedProcess:
    dados = bruto if bruto is not None else json.dumps({"tool_name": ferramenta, "tool_input": entrada or {}}).encode()
    return subprocess.run([sys.executable, str(RAIZ / "trava.py")], input=dados, capture_output=True, cwd=RAIZ)


@pytest.fixture(autouse=True)
def sem_token():
    TOKEN.unlink(missing_ok=True)
    yield
    TOKEN.unlink(missing_ok=True)


@pytest.mark.parametrize("ferramenta,entrada", [
    ("Read", {"file_path": "x"}),
    (M + "outlook_email_search", {}),
    (M + "outlook_calendar_search", {}),
    (M + "teams_list_chats", {}),
    (M + "outlook_create_draft", {}),                       # rascunho nao envia nada
    ("Bash", {"command": "ls"}),
    ("PowerShell", {"command": "Get-ChildItem ."}),
    ("Write", {"file_path": str(Path.home() / "Documents" / "x.md")}),
])
def test_passa_direto(ferramenta, entrada):
    assert rodar(ferramenta, entrada).returncode == 0


@pytest.mark.parametrize("ferramenta,entrada", [
    (M + "outlook_send_mail", {}),
    (M + "outlook_forward_mail", {}),
    (M + "teams_send_chat_message", {}),
    (M + "teams_send_channel_message", {}),
    (M + "outlook_create_event", {}),
    (M + "sharepoint_upload_file", {}),
    ("mcp__novo__fazer_algo", {}),                          # desconhecida: por seguranca, pede
    ("CronCreate", {}),
    ("Write", {"file_path": "C:\\Windows\\System32\\x.txt"}),
    ("Write", {"file_path": str(Path.home() / "AppData" / "Local" / "Temp" / "x.txt")}),
    ("Write", {"file_path": str(Path.home() / ".claude" / "settings.json")}),
    ("Bash", {"command": "curl -X POST https://exemplo.test -d a=1"}),
    ("PowerShell", {"command": "Invoke-RestMethod https://exemplo.test -Method Post -Body a"}),
])
def test_barra_e_orienta_a_pedir_confirmacao(ferramenta, entrada):
    r = rodar(ferramenta, entrada)
    assert r.returncode == 2
    assert "Confirma, senhor?" in r.stderr.decode("utf-8")


def test_confirmacao_valida_libera_so_enquanto_vale():
    TOKEN.parent.mkdir(exist_ok=True)
    TOKEN.write_text(str(time.time() + 60))
    assert rodar(M + "outlook_send_mail").returncode == 0
    TOKEN.write_text(str(time.time() - 5))                  # vencida
    assert rodar(M + "outlook_send_mail").returncode == 2
    TOKEN.write_text("lixo")                                # ilegivel: nao libera
    assert rodar(M + "outlook_send_mail").returncode == 2


@pytest.mark.parametrize("bruto", [b"isto nao e json", b"", b"[1, 2, 3]"])
def test_falha_fechada_com_entrada_ilegivel(bruto):
    assert rodar("", bruto=bruto).returncode == 2


def test_aceita_json_com_bom_do_powershell():
    bruto = b"\xef\xbb\xbf" + json.dumps({"tool_name": M + "outlook_send_mail", "tool_input": {}}).encode()
    assert rodar("", bruto=bruto).returncode == 2           # entendeu o pedido e barrou (nao "deixou passar")
