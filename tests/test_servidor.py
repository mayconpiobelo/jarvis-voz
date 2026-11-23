"""Servidor local (127.0.0.1): rotas do painel, seguranca (Host, JSON), tarefas e acoes. Sem GUI, sem microfone, sem rede."""
import http.client
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import jarvis  # noqa: E402
import tarefas  # noqa: E402


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("srv")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    mp = pytest.MonkeyPatch()
    mp.setattr(jarvis, "HISTORY_PORT", porta)
    mp.setattr(jarvis, "HISTORY", tmp / "historico.jsonl")                     # nunca o historico real
    mp.setattr(jarvis, "_lista_tarefas", tarefas.Tarefas(tmp / "t.json", tmp / "T.md", agora=lambda: datetime(2026, 11, 23, 9, 0)))
    mp.setattr(jarvis, "save_state", lambda estado: None)                      # nunca a sessao real
    mp.setitem(jarvis.CFG, "painel", {"enabled": True, "hotkey": "ctrl+alt+k", "corner": "tr",
                                      "atalhos": [{"id": "ruim", "nome": "Ruim", "tipo": "url", "alvo": "ftp://nao.vale"},
                                                  {"id": "seg", "nome": "Seguro", "tipo": "url", "alvo": "https://exemplo.test/segredo-do-alvo"}]})
    jarvis.start_history_server()
    for _ in range(50):
        try:
            c = http.client.HTTPConnection("127.0.0.1", porta, timeout=1)
            c.request("GET", "/api/status")
            c.getresponse().read()  # le tudo antes de fechar: sem "conexao anulada" no servidor
            c.close()
            break
        except OSError:
            time.sleep(0.1)
    yield porta
    mp.undo()


def chamar(porta, metodo, caminho, corpo=None, host=None, ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
    cab = {"Host": host or f"127.0.0.1:{porta}"}
    dados = None
    if metodo == "POST":
        dados = json.dumps(corpo if corpo is not None else {}).encode()
        cab["Content-Type"] = ctype
    c.request(metodo, caminho, body=dados, headers=cab)
    r = c.getresponse()
    bruto = r.read()
    c.close()
    try:
        return r.status, json.loads(bruto)
    except ValueError:
        return r.status, bruto.decode("utf-8", "replace")


def test_paginas_existem(srv):
    for caminho in ("/", "/overlay", "/painel"):
        status, corpo = chamar(srv, "GET", caminho)
        assert status == 200 and "<html" in corpo.lower(), caminho


def test_recusa_host_estranho_e_post_sem_json(srv):
    assert chamar(srv, "GET", "/api/status", host="evil.example")[0] == 403
    assert chamar(srv, "POST", "/api/painel/alternar", host="evil.example")[0] == 403
    assert chamar(srv, "POST", "/api/acao", {"acao": "esfera"}, ctype="text/plain")[0] == 415
    assert chamar(srv, "GET", "/nao-existe")[0] == 404


def test_painel_mostrar_e_fechar(srv):
    assert chamar(srv, "GET", "/api/painel")[1] == {"show": False, "corner": "tr"}
    chamar(srv, "POST", "/api/painel/alternar")
    assert chamar(srv, "GET", "/api/painel")[1]["show"] is True
    chamar(srv, "POST", "/api/painel/fechar")
    assert chamar(srv, "GET", "/api/painel")[1]["show"] is False


def test_fluxo_de_tarefas_pelo_painel(srv):
    st, r = chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "revisar contrato para sexta urgente"})
    assert st == 200 and r["ok"] and r["mensagem"].startswith("Anotado")
    lista = chamar(srv, "GET", "/api/tarefas")[1]
    assert [t["texto"] for t in lista["abertas"]] == ["revisar contrato"]
    t = lista["abertas"][0]
    assert t["prazo"] == "2026-11-27" and t["prioridade"] == "alta"

    chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "ligar para o fornecedor"})
    assert chamar(srv, "POST", "/api/tarefas/concluir", {"id": t["id"]})[0] == 200
    lista = chamar(srv, "GET", "/api/tarefas")[1]
    assert [x["texto"] for x in lista["abertas"]] == ["ligar para o fornecedor"]
    assert [x["texto"] for x in lista["concluidas"]] == ["revisar contrato"]

    outro = lista["abertas"][0]["id"]
    assert chamar(srv, "POST", "/api/tarefas/remover", {"id": outro})[0] == 200
    assert chamar(srv, "GET", "/api/tarefas")[1]["abertas"] == []
    assert chamar(srv, "POST", "/api/tarefas/desfazer")[1]["ok"] is True
    assert len(chamar(srv, "GET", "/api/tarefas")[1]["abertas"]) == 1

    # entradas invalidas nao quebram nem alteram nada
    assert chamar(srv, "POST", "/api/tarefas/concluir", {"id": "abc"})[0] == 404
    assert chamar(srv, "POST", "/api/tarefas/remover", {"id": 99999})[0] == 404
    assert chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "   "})[1]["mensagem"] is None


def test_comandos_digitados_funcionam_no_campo_do_painel(srv):
    chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "tarefa alfa"})
    r = chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "conclua a tarefa alfa"})[1]
    assert r["mensagem"].startswith("Concluída, senhor:")


def test_atalhos_nunca_expoem_o_alvo(srv):
    lista = chamar(srv, "GET", "/api/atalhos")[1]
    ids = [a["id"] for a in lista]
    assert ids[:4] == ["falar", "nova_conversa", "janela", "esfera"] and "seg" in ids
    assert all(set(a) <= {"id", "nome", "icone"} for a in lista)
    assert "exemplo.test" not in json.dumps(lista)


def test_acoes_aceitam_so_ids_conhecidos(srv):
    assert chamar(srv, "POST", "/api/acao", {"acao": "../../etc"})[0] == 404
    assert chamar(srv, "POST", "/api/acao", {"acao": "C:\\Windows\\System32\\calc.exe"})[0] == 404
    assert chamar(srv, "POST", "/api/acao", {"acao": "ruim"})[0] == 404          # tipo/URL invalido: recusado
    visivel = jarvis.CURRENT["esfera_visivel"]
    assert chamar(srv, "POST", "/api/acao", {"acao": "esfera"})[0] == 200
    assert jarvis.CURRENT["esfera_visivel"] is (not visivel)
    chamar(srv, "POST", "/api/acao", {"acao": "esfera"})


def test_nova_conversa_marca_no_historico(srv):
    assert chamar(srv, "POST", "/api/acao", {"acao": "nova_conversa"})[0] == 200
    assert any(e.get("marker") == "Nova conversa" for e in jarvis.read_history())


def test_sistema_devolve_percentuais(srv):
    chamar(srv, "GET", "/api/sistema")
    time.sleep(0.2)
    s = chamar(srv, "GET", "/api/sistema")[1]
    assert 0 <= s["cpu"] <= 100 and 0 <= s["mem"] <= 100 and s["uptime_s"] > 0


def test_atalho_interno_do_painel_valida():
    assert jarvis.parse_hotkey("ctrl+alt+k") == (0x4000 | 0x2 | 0x1, 0x4B)
    assert jarvis.abrir_atalho({"tipo": "url", "alvo": "javascript:alert(1)"})["ok"] is False
    assert jarvis.abrir_atalho({"tipo": "desconhecido", "alvo": "x"})["ok"] is False
