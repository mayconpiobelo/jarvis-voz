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
    cab = {"Host": host or f"127.0.0.1:{porta}"}
    dados = None
    if metodo == "POST":
        dados = json.dumps(corpo if corpo is not None else {}).encode()
        cab["Content-Type"] = ctype
    for tentativa in range(3):  # loopback sob carga (maquina ocupada) as vezes derruba uma conexao: tenta de novo
        c = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
        try:
            c.request(metodo, caminho, body=dados, headers=cab)
            r = c.getresponse()
            bruto = r.read()
            break
        except (ConnectionError, http.client.RemoteDisconnected):
            if tentativa == 2:
                raise
            time.sleep(0.2)
        finally:
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


def test_painel_mostrar_e_fechar(srv, tmp_path, monkeypatch):
    monkeypatch.setattr(jarvis, "PAINEL_GEOM", tmp_path / "geom.json")        # nunca a posicao real do usuario
    estado = chamar(srv, "GET", "/api/painel")[1]
    assert (estado["show"], estado["corner"], estado["geom"]) == (False, "tr", None)
    chamar(srv, "POST", "/api/painel/alternar")
    assert chamar(srv, "GET", "/api/painel")[1]["show"] is True
    chamar(srv, "POST", "/api/painel/fechar")
    assert chamar(srv, "GET", "/api/painel")[1]["show"] is False


def test_geometria_do_painel_salva_valida_e_restaura(srv, tmp_path, monkeypatch):
    monkeypatch.setattr(jarvis, "PAINEL_GEOM", tmp_path / "geom.json")        # nunca a posicao real do usuario
    assert chamar(srv, "GET", "/api/painel")[1]["geom"] is None
    ok = {"x": -1300, "y": 40, "w": 900, "h": 640}                            # coordenada negativa = monitor a esquerda
    assert chamar(srv, "POST", "/api/painel/geometria", ok) == (200, {"ok": True})
    assert chamar(srv, "GET", "/api/painel")[1]["geom"] == ok
    antes = chamar(srv, "GET", "/api/painel")[1]["reset"]
    for ruim in ({"x": 1, "y": 2, "w": 50, "h": 600}, {"x": "a", "y": 2, "w": 800, "h": 600}, {"x": 0, "y": 0, "w": 800},
                 {"x": 10**9, "y": 0, "w": 800, "h": 600}, {"x": 0, "y": 0, "w": True, "h": 600}, {"x": 0.5, "y": 0, "w": 800, "h": 600}):
        assert chamar(srv, "POST", "/api/painel/geometria", ruim)[0] == 400, ruim
    assert chamar(srv, "GET", "/api/painel")[1]["geom"] == ok                  # entradas invalidas nao alteram nada
    assert chamar(srv, "POST", "/api/painel/geometria", ok, host="evil.example")[0] == 403
    assert chamar(srv, "POST", "/api/painel/geometria", ok, ctype="text/plain")[0] == 415
    assert chamar(srv, "POST", "/api/painel/resetar")[0] == 200
    estado = chamar(srv, "GET", "/api/painel")[1]
    assert estado["geom"] is None and estado["reset"] == antes + 1             # o app percebe a restauracao pelo contador


def test_falar_pelo_painel_nao_fecha_o_painel(srv, monkeypatch):
    chamadas = []
    monkeypatch.setattr(jarvis, "on_hotkey", lambda: chamadas.append("microfone"))
    chamar(srv, "POST", "/api/painel/alternar")
    assert chamar(srv, "GET", "/api/painel")[1]["show"] is True
    assert chamar(srv, "POST", "/api/acao", {"acao": "falar"})[0] == 200
    time.sleep(0.7)                                                                   # o microfone abre depois de 0,4 s
    assert chamadas == ["microfone"]
    assert chamar(srv, "GET", "/api/painel")[1]["show"] is True                       # o painel continua aberto
    chamar(srv, "POST", "/api/painel/fechar")


def test_esfera_do_painel_liga_mostra_um_instante_e_desliga(srv):
    jarvis.CURRENT["esfera_visivel"] = True
    st, r = chamar(srv, "POST", "/api/acao", {"acao": "esfera"})            # desliga
    assert st == 200 and "desligada" in r["mensagem"]
    assert chamar(srv, "GET", "/api/status")[1]["esfera_demo"] is False
    st, r = chamar(srv, "POST", "/api/acao", {"acao": "esfera"})            # liga: aparece alguns segundos
    assert "ligada" in r["mensagem"]
    estado = chamar(srv, "GET", "/api/status")[1]
    assert estado["esfera_visivel"] is True and estado["esfera_demo"] is True
    chamar(srv, "POST", "/api/acao", {"acao": "esfera"})                    # desliga de novo: some na hora
    assert chamar(srv, "GET", "/api/status")[1]["esfera_demo"] is False
    jarvis.CURRENT["esfera_visivel"] = True


def test_geometria_corrompida_vira_posicao_padrao(tmp_path, monkeypatch):
    f = tmp_path / "geom.json"
    monkeypatch.setattr(jarvis, "PAINEL_GEOM", f)
    f.write_text("{ nao e json", encoding="utf-8")
    assert jarvis.painel_geom_ler() is None
    f.write_text('{"x": 1, "y": 2, "w": 10, "h": 10}', encoding="utf-8")        # pequeno demais
    assert jarvis.painel_geom_ler() is None


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


def test_painel_pergunta_para_quando_e_aceita_a_resposta(srv):
    lista = jarvis.tarefas_lista()
    lista.perguntar_prazo = True
    try:
        def abertas():
            return {t["texto"]: t for t in chamar(srv, "GET", "/api/tarefas")[1]["abertas"]}

        st, r = chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "comprar pão"})
        assert st == 200 and r["pergunta"] is True and r["mensagem"] is None
        assert "comprar pão" not in abertas()                                           # nada criado ate escolher
        r = chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "comprar pão", "quando": "amanhã"})[1]
        assert r["pergunta"] is False and r["mensagem"].startswith("Anotado")
        assert abertas()["comprar pão"]["prazo"] == "2026-11-24"

        r = chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "ligar fornecedor", "quando": ""})[1]   # sem data
        assert r["pergunta"] is False and abertas()["ligar fornecedor"]["prazo"] is None

        r = chamar(srv, "POST", "/api/tarefas/adicionar", {"texto": "pagar boleto", "quando": "blablabla xyz"})[1]
        assert r["pergunta"] is True and r["erro"] is True and "Não entendi" in r["mensagem"]   # volta a perguntar
        assert "pagar boleto" not in abertas()
    finally:
        lista.perguntar_prazo = False


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


def test_rotas_de_musica_com_player_falso(srv):
    import musica

    class Falso:
        def __init__(self):
            self.acoes = []

        def snapshot(self, preferir):
            return {"app": "Spotify", "titulo": "Faixa", "artista": "Banda", "album": "Disco", "estado": "tocando", "posicao_s": 10.0,
                    "duracao_s": 100.0, "tem_capa": True, "pode": {"anterior": True, "proxima": True, "play_pause": True}}

        def capa(self, preferir):
            import io

            from PIL import Image

            b = io.BytesIO()
            Image.new("RGB", (4, 4), (10, 200, 10)).save(b, "PNG")
            return b.getvalue()

        def acao(self, acao, preferir):
            self.acoes.append(acao)
            return True

    f = Falso()
    musica.definir_backend(f)
    try:
        st, m = chamar(srv, "GET", "/api/musica")
        assert st == 200 and m["ativo"] and m["titulo"] == "Faixa" and m["estado"] == "tocando" and m["capa"]
        conn = http.client.HTTPConnection("127.0.0.1", srv, timeout=5)
        conn.request("GET", "/api/musica/capa", headers={"Host": f"127.0.0.1:{srv}"})
        r = conn.getresponse()
        assert r.status == 200 and r.getheader("Content-Type") == "image/png" and r.read()[:4] == b"\x89PNG"
        conn.close()
        assert chamar(srv, "POST", "/api/musica/acao", {"acao": "proxima"})[0] == 200
        assert chamar(srv, "POST", "/api/musica/acao", {"acao": "formatar_disco"})[0] == 404     # so acoes conhecidas
        assert chamar(srv, "POST", "/api/musica/acao", {"acao": "play_pause"}, host="evil.example")[0] == 403
        assert chamar(srv, "POST", "/api/musica/acao", {"acao": "anterior"}, ctype="text/plain")[0] == 415
        assert f.acoes == ["proxima"]
        # desligado no config: nada e lido nem controlado
        jarvis.CFG["painel"]["musica"] = {"enabled": False}
        assert chamar(srv, "GET", "/api/musica")[1]["disponivel"] is False
        assert chamar(srv, "POST", "/api/musica/acao", {"acao": "proxima"})[0] == 404
        assert jarvis.responder_musica("próxima música") is None
        assert f.acoes == ["proxima"]
    finally:
        jarvis.CFG["painel"].pop("musica", None)
        musica.definir_backend(None)


def test_voz_de_musica_passa_pelo_jarvis(srv):
    import musica

    class P:
        def __init__(self):
            self.acoes = []

        def snapshot(self, preferir):
            return {"app": "Spotify", "titulo": "Faixa", "artista": "Banda", "album": "", "estado": "tocando", "posicao_s": 0.0,
                    "duracao_s": 90.0, "tem_capa": False, "pode": {"anterior": True, "proxima": True, "play_pause": True}}

        def capa(self, preferir):
            return None

        def acao(self, acao, preferir):
            self.acoes.append(acao)
            return True

    p = P()
    musica.definir_backend(p)
    try:
        assert jarvis.responder_musica("Jarvis, pausa a música") == "Pausado, senhor." and p.acoes == ["play_pause"]
        assert jarvis.responder_musica("toca uma música do Queen") is None
    finally:
        musica.definir_backend(None)


def test_atalho_interno_do_painel_valida():
    assert jarvis.parse_hotkey("ctrl+alt+k") == (0x4000 | 0x2 | 0x1, 0x4B)
    assert jarvis.abrir_atalho({"tipo": "url", "alvo": "javascript:alert(1)"})["ok"] is False
    assert jarvis.abrir_atalho({"tipo": "desconhecido", "alvo": "x"})["ok"] is False
