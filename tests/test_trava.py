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


# ------------------------------------------------------------------ sessao do celular: so o toque em Confirmar dela libera
sys.path.insert(0, str(RAIZ))
import trava  # noqa: E402


@pytest.fixture
def trava_tmp(tmp_path, monkeypatch):
    """Trava em memoria apontando para uma pasta de teste (nao mexe no estado do Jarvis que esta rodando)."""
    monkeypatch.setattr(trava, "ESTADO", tmp_path)
    monkeypatch.setattr(trava, "CELULAR_ARQ", tmp_path / "celular_trava.json")
    return tmp_path


def _estado_celular(pasta, sessoes=(), confirmado=None):
    (pasta / "celular_trava.json").write_text(json.dumps({"sessoes": list(sessoes), "confirmado": confirmado or {}}))


def _envio(sid):
    return {"tool_name": M + "outlook_send_mail", "tool_input": {}, "session_id": sid}


def _barrado(dados):
    with pytest.raises(trava.Barrado):
        trava.avaliar(dados)


def test_celular_sem_toque_em_confirmar_e_barrado(trava_tmp):
    _estado_celular(trava_tmp, ["S1"])
    _barrado(_envio("S1"))
    trava.avaliar({"tool_name": "Read", "tool_input": {}, "session_id": "S1"})  # leitura passa sempre
    trava.avaliar({"tool_name": M + "outlook_calendar_search", "tool_input": {}, "session_id": "S1"})


def test_confirmacao_por_voz_do_pc_nao_vale_no_celular(trava_tmp):
    _estado_celular(trava_tmp, ["S1"])
    (trava_tmp / "confirmado").write_text(str(time.time() + 60))  # o "confirma" falado no PC
    _barrado(_envio("S1"))
    trava.avaliar(_envio("sessao-do-pc"))  # ...mas continua valendo para o PC


def test_toque_no_celular_vale_so_para_a_propria_sessao(trava_tmp):
    _estado_celular(trava_tmp, ["S1", "S2"], {"S1": time.time() + 60})
    trava.avaliar(_envio("S1"))
    _barrado(_envio("S2"))              # outra sessao do celular
    _barrado(_envio("sessao-do-pc"))    # a sessao do PC nao usa o toque do celular


def test_toque_expirado_nao_vale(trava_tmp):
    _estado_celular(trava_tmp, ["S1"], {"S1": time.time() - 1})
    _barrado(_envio("S1"))


def test_estado_do_celular_ilegivel_nao_afrouxa_nada(trava_tmp):
    (trava_tmp / "celular_trava.json").write_text("{isto nao e json")
    _barrado(_envio("S1"))  # sem registro nem confirmacao: barrado como qualquer outra sessao
    (trava_tmp / "confirmado").write_text(str(time.time() + 60))
    trava.avaliar(_envio("S1"))  # sessao nao registrada = comportamento de sempre do PC


def test_pc_sem_session_id_continua_como_antes(trava_tmp):
    _barrado({"tool_name": M + "outlook_send_mail", "tool_input": {}})
    (trava_tmp / "confirmado").write_text(str(time.time() + 60))
    trava.avaliar({"tool_name": M + "outlook_send_mail", "tool_input": {}})
