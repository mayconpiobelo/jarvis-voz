"""Jarvis no celular (PWA): rede permitida, token, trava de IP, API, tarefas, voz e isolamento do Jarvis local.
Nenhum teste usa a rede externa nem o Claude de verdade (servidor em 127.0.0.1, porta escolhida pelo sistema)."""
import io
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import celular  # noqa: E402
import jarvis  # noqa: E402
import tarefas  # noqa: E402

TOKEN = "t" * 40
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "


# ------------------------------------------------------------------ rede e token
@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "100.64.0.1", "100.101.102.103", "100.127.255.254",
                                  "fd7a:115c:a1e0::1"])
def test_hosts_permitidos(host):
    assert celular.host_permitido(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.0.10", "10.0.0.5", "172.16.0.1", "8.8.8.8",
                                  "100.63.255.255", "100.128.0.1", "localhost", "meu-pc.tailnet.ts.net"])
def test_hosts_recusados(host):
    assert not celular.host_permitido(host)


def test_token_confere():
    assert celular.token_confere(f"Bearer {TOKEN}", TOKEN)
    assert celular.token_confere(f"bearer   {TOKEN} ", TOKEN)
    for ruim in ("", "Bearer", f"Basic {TOKEN}", TOKEN, f"Bearer {TOKEN}x", "Bearer " + "t" * 39):
        assert not celular.token_confere(ruim, TOKEN)


def test_sem_token_configurado_nada_passa():
    assert not celular.token_confere("Bearer ", "")
    assert not celular.token_confere("Bearer curto", "curto")


def test_garantir_token_gera_grava_e_reaproveita(tmp_path):
    f = tmp_path / "config.json"
    f.write_text(json.dumps({"owner_name": "Ana", "cidade": "Jundiaí"}), encoding="utf-8")
    t1 = celular.garantir_token(f)
    assert len(t1) >= celular.TOKEN_MIN
    dados = json.loads(f.read_text(encoding="utf-8"))
    assert dados["celular"]["token"] == t1 and dados["celular"]["enabled"] is False
    assert dados["celular"]["host"] == "127.0.0.1" and dados["owner_name"] == "Ana" and dados["cidade"] == "Jundiaí"
    assert celular.garantir_token(f) == t1  # nao troca um token existente


def test_limite_de_erros():
    t = [0.0]
    lim = celular.LimiteDeErros(maximo=3, segundos=100, relogio=lambda: t[0])
    for _ in range(2):
        lim.errou("1.1.1.1")
    assert not lim.travado("1.1.1.1")
    lim.errou("1.1.1.1")
    assert lim.travado("1.1.1.1") and not lim.travado("2.2.2.2")
    t[0] = 101.0
    assert not lim.travado("1.1.1.1")  # passou o tempo
    lim.errou("1.1.1.1")
    lim.acertou("1.1.1.1")
    assert not lim.travado("1.1.1.1")


# ------------------------------------------------------------------ servidor de ponta a ponta
class _Falso:
    """Ganchos de mentira que registram o que receberam."""

    def __init__(self):
        self.vistos: list = []
        self.tarefas_abertas = [{"id": 1, "texto": "Pagar boleto", "prazo": None, "prioridade": "media"}]
        self.voz: bytes | None = WAV

    def ganchos(self) -> celular.Ganchos:
        return celular.Ganchos(
            transcrever=lambda b: (self.vistos.append(("audio", len(b))), "que horas sao")[1],
            perguntar=lambda t: (self.vistos.append(("perguntar", t)), "Perfeitamente, senhor.")[1],
            falar=lambda t: (self.vistos.append(("falar", t)), self.voz)[1],
            tarefas=lambda: {"abertas": self.tarefas_abertas, "concluidas": []},
            tarefa_adicionar=lambda t, q: (self.vistos.append(("add", t, q)), {"mensagem": "Anotado", "pergunta": False})[1],
            tarefa_concluir=lambda i: (self.vistos.append(("concluir", i)), i == 1)[1],
        )


def _subir(g):
    srv = celular.criar_servidor("127.0.0.1", 0, TOKEN, g)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture
def servidor():
    falso = _Falso()
    srv, base = _subir(falso.ganchos())
    yield base, falso, srv
    srv.shutdown()
    srv.server_close()


def _chamar(base, caminho, corpo=None, token=TOKEN, ctype="application/json", metodo=None, bruto=False):
    dados = json.dumps(corpo).encode() if isinstance(corpo, (dict, list)) else corpo
    req = urllib.request.Request(base + caminho, data=dados, method=metodo or ("POST" if dados is not None else "GET"))
    if ctype and dados is not None:
        req.add_header("Content-Type", ctype)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            corpo_r = r.read()
            return r.status, (corpo_r if bruto else json.loads(corpo_r)), dict(r.headers)
    except urllib.error.HTTPError as e:
        corpo_r = e.read()
        return e.code, (corpo_r if bruto else json.loads(corpo_r)), dict(e.headers)


def test_pagina_e_icones_sem_token(servidor):
    base, _, _ = servidor
    code, html, h = _chamar(base, "/", token=None, bruto=True)
    assert code == 200 and b"<title>Jarvis</title>" in html and h["Content-Type"].startswith("text/html")
    csp = h["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    assert h["X-Frame-Options"] == "DENY" and h["Referrer-Policy"] == "no-referrer"
    code, man, h = _chamar(base, "/manifest.webmanifest", token=None)
    assert code == 200 and man["display"] == "standalone" and man["icons"]
    for n in (180, 192, 512):
        code, png, h = _chamar(base, f"/icon-{n}.png", token=None, bruto=True)
        assert code == 200 and png[:8] == b"\x89PNG\r\n\x1a\n" and h["Content-Type"] == "image/png"


def test_pagina_nao_carrega_nada_de_fora():
    html = (Path(__file__).resolve().parent.parent / "celular.html").read_text(encoding="utf-8")
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html
    assert "innerHTML" not in html  # texto do Claude/tarefas so entra por textContent


def test_ping_e_pergunta(servidor):
    base, falso, _ = servidor
    assert _chamar(base, "/api/ping")[0] == 200
    code, r, _ = _chamar(base, "/api/perguntar", {"texto": "  que horas sao?  "})
    assert code == 200 and r == {"ok": True, "texto": "Perfeitamente, senhor."}
    assert ("perguntar", "que horas sao?") in falso.vistos


def test_api_exige_token(monkeypatch):
    original = celular.LimiteDeErros
    monkeypatch.setattr(celular, "LimiteDeErros", lambda: original(maximo=1000))  # aqui o foco nao e a trava de IP
    falso = _Falso()
    srv, base = _subir(falso.ganchos())
    try:
        _verificar_api_exige_token(base, falso)
    finally:
        srv.shutdown()
        srv.server_close()


def _verificar_api_exige_token(base, falso):
    for caminho, corpo in (("/api/ping", None), ("/api/tarefas", None), ("/api/perguntar", {"texto": "oi"}),
                           ("/api/falar", {"texto": "oi"}), ("/api/tarefas/adicionar", {"texto": "x"}),
                           ("/api/tarefas/concluir", {"id": 1})):
        assert _chamar(base, caminho, corpo, token=None)[0] == 401, caminho
        assert _chamar(base, caminho, corpo, token="x" * 40)[0] == 401, caminho
    code, _, _ = _chamar(base, "/api/transcrever", b"abc", ctype="audio/mp4", token=None)
    assert code == 401
    assert falso.vistos == []  # nenhum gancho foi chamado


def test_cinco_erros_travam_ate_o_token_certo(servidor):
    base, falso, _ = servidor
    for _ in range(celular.ERROS_ANTES_DE_TRAVAR):
        assert _chamar(base, "/api/ping", token="x" * 40)[0] == 401
    assert _chamar(base, "/api/ping", token="x" * 40)[0] == 429
    assert _chamar(base, "/api/perguntar", {"texto": "oi"})[0] == 429  # nem o token certo passa durante a trava
    assert falso.vistos == []


def test_rotas_desconhecidas(servidor):
    base, _, _ = servidor
    for caminho in ("/api/trava", "/api/acao", "/api/hotkey", "/api/status", "/historico", "/painel", "/etc/passwd"):
        assert _chamar(base, caminho)[0] in (401, 404)
        assert _chamar(base, caminho, {"a": 1})[0] in (401, 404)
    assert _chamar(base, "/api/xyz")[0] == 404
    assert _chamar(base, "/api/xyz", {"a": 1})[0] == 404


def test_transcrever(servidor):
    base, falso, _ = servidor
    code, r, _ = _chamar(base, "/api/transcrever", b"\x00" * 1000, ctype="audio/mp4")
    assert code == 200 and r == {"ok": True, "texto": "que horas sao"} and ("audio", 1000) in falso.vistos
    assert _chamar(base, "/api/transcrever", b"x", ctype="application/json")[0] == 415
    assert _chamar(base, "/api/transcrever", b"", ctype="audio/mp4")[0] == 413
    try:  # o servidor recusa pelo Content-Length sem ler o corpo; o cliente ve 413 ou a conexao encerrada
        assert _chamar(base, "/api/transcrever", b"x" * (celular.MAX_AUDIO + 1), ctype="audio/mp4")[0] == 413
    except ConnectionError:
        pass


def test_falar_devolve_wav_ou_avisa_que_nao_ha_voz(servidor):
    base, falso, _ = servidor
    code, corpo, h = _chamar(base, "/api/falar", {"texto": "Pois nao, senhor."}, bruto=True)
    assert code == 200 and corpo == WAV and h["Content-Type"] == "audio/wav"
    falso.voz = None
    code, r, _ = _chamar(base, "/api/falar", {"texto": "oi"})
    assert code == 200 and r["ok"] is False and r["sem_voz"] is True


def test_tarefas(servidor):
    base, falso, _ = servidor
    code, r, _ = _chamar(base, "/api/tarefas")
    assert code == 200 and r["abertas"][0]["texto"] == "Pagar boleto"
    code, r, _ = _chamar(base, "/api/tarefas/adicionar", {"texto": "Ligar para o contador", "quando": "amanhã"})
    assert code == 200 and r["mensagem"] == "Anotado" and ("add", "Ligar para o contador", "amanhã") in falso.vistos
    assert _chamar(base, "/api/tarefas/adicionar", {"texto": "  "})[0] == 400
    assert _chamar(base, "/api/tarefas/concluir", {"id": 1})[0] == 200
    assert _chamar(base, "/api/tarefas/concluir", {"id": 99})[0] == 404
    assert _chamar(base, "/api/tarefas/concluir", {"id": "abc"})[0] == 404
    # nao existe rota para remover ou desfazer: so no PC
    assert _chamar(base, "/api/tarefas/remover", {"id": 1})[0] == 404
    assert _chamar(base, "/api/tarefas/desfazer", {})[0] == 404


def test_pedido_ruim(servidor):
    base, falso, _ = servidor
    assert _chamar(base, "/api/perguntar", {"texto": "oi"}, ctype="text/plain")[0] == 415
    assert _chamar(base, "/api/perguntar", {"texto": ""})[0] == 400
    assert _chamar(base, "/api/perguntar", {"outro": "x"})[0] == 400
    assert _chamar(base, "/api/perguntar", b"nao e json")[0] == 400
    assert _chamar(base, "/api/perguntar", [1, 2])[0] == 400
    assert _chamar(base, "/api/perguntar", {"texto": "a" * (celular.MAX_JSON + 10)})[0] == 413
    assert falso.vistos == []


def test_texto_longo_e_cortado(servidor):
    base, falso, _ = servidor
    assert _chamar(base, "/api/perguntar", {"texto": "a" * 1000})[0] == 200
    assert len(falso.vistos[-1][1]) == celular.MAX_TEXTO


def test_erro_do_gancho_nao_vaza_detalhes():
    falso = _Falso()
    g = falso.ganchos()

    def quebra(_t):
        raise RuntimeError("segredo interno /dados/privados")

    g.perguntar = quebra
    srv, base = _subir(g)
    try:
        code, r, _ = _chamar(base, "/api/perguntar", {"texto": "oi"})
    finally:
        srv.shutdown()
        srv.server_close()
    assert code == 500 and r["ok"] is False and "segredo" not in json.dumps(r)


def test_ocupado_do_pc_vira_429_com_a_mensagem():
    falso = _Falso()
    g = falso.ganchos()

    def ocupado(_x):
        raise celular.Ocupado("O Jarvis esta atendendo o senhor no computador agora.")

    g.perguntar = ocupado
    g.transcrever = ocupado
    srv, base = _subir(g)
    try:
        c1, r1, _ = _chamar(base, "/api/perguntar", {"texto": "oi"})
        c2, r2, _ = _chamar(base, "/api/transcrever", b"abc", ctype="audio/mp4")
    finally:
        srv.shutdown()
        srv.server_close()
    assert c1 == c2 == 429 and "computador" in r1["texto"] and "computador" in r2["texto"]


def test_muitos_pedidos_ao_mesmo_tempo_devolvem_429():
    entrou, soltar = threading.Event(), threading.Event()
    falso = _Falso()
    g = falso.ganchos()

    def lento(_t):
        entrou.set()
        soltar.wait(10)
        return "ok"

    g.perguntar = lento
    srv, base = _subir(g)
    try:
        ths = [threading.Thread(target=_chamar, args=(base, "/api/perguntar", {"texto": "a"})) for _ in range(2)]
        for t in ths:
            t.start()
        assert entrou.wait(5)
        time.sleep(0.5)  # a segunda vaga tambem precisa estar ocupada
        assert _chamar(base, "/api/perguntar", {"texto": "b"})[0] == 429
    finally:
        soltar.set()
        for t in ths:
            t.join(5)
        srv.shutdown()
        srv.server_close()


def test_criar_servidor_recusa_host_e_token_ruins():
    g = _Falso().ganchos()
    with pytest.raises(ValueError):
        celular.criar_servidor("0.0.0.0", 0, TOKEN, g)
    with pytest.raises(ValueError):
        celular.criar_servidor("127.0.0.1", 0, "curto", g)


def test_iniciar_desligado_ou_invalido_nao_sobe():
    g = _Falso().ganchos()
    assert celular.iniciar({}, g) is None
    assert celular.iniciar({"celular": {"enabled": False, "host": "127.0.0.1", "token": TOKEN}}, g) is None
    assert celular.iniciar({"celular": {"enabled": True, "host": "0.0.0.0", "token": TOKEN}}, g) is None
    assert celular.iniciar({"celular": {"enabled": True, "host": "127.0.0.1", "token": "curto"}}, g) is None


def test_porta_ocupada_nao_derruba_a_partida():
    ocupada = socket.socket()
    ocupada.bind(("127.0.0.1", 0))
    ocupada.listen(1)
    try:
        cfg = {"celular": {"enabled": True, "host": "127.0.0.1", "port": ocupada.getsockname()[1], "token": TOKEN}}
        assert celular.iniciar(cfg, _Falso().ganchos()) is None  # OSError vira aviso no log
    finally:
        ocupada.close()


def test_celular_iniciar_com_config_ruim_nao_derruba(monkeypatch):
    for cfg in ({"enabled": True, "host": "0.0.0.0", "token": TOKEN}, {"enabled": True, "token": ""}):
        monkeypatch.setitem(jarvis.CFG, "celular", cfg)
        jarvis.celular_iniciar()  # so avisa no log


# ------------------------------------------------------------------ Claude somente-consulta (jarvis.py)
def _valor(args, flag):
    return args[args.index(flag) + 1]


def test_claude_do_celular_so_consulta(monkeypatch):
    monkeypatch.setitem(jarvis.CFG, "celular", {})
    args = jarvis._celular_args()
    assert _valor(args, "--permission-mode") == "dontAsk"  # nega tudo o que nao esta na lista
    nativas = _valor(args, "--tools").split(",")
    assert set(nativas) <= {"WebSearch", "WebFetch", "Read", "Glob", "Grep"}
    for proibida in ("Bash", "PowerShell", "Write", "Edit", "NotebookEdit", "Agent"):
        assert proibida not in nativas
    permitidas = _valor(args, "--allowedTools").split(",")
    assert not [p for p in permitidas if any(x in p for x in ("send", "create", "delete", "upload", "update"))]
    assert "--add-dir" not in args and "--resume" not in args and "bypassPermissions" not in args
    assert "Bash(rm *)" in _valor(args, "--disallowedTools")


def test_claude_do_celular_respeita_a_lista_do_config(monkeypatch):
    monkeypatch.setitem(jarvis.CFG, "celular", {"ferramentas": ["WebSearch", "mcp__x__agenda"]})
    args = jarvis._celular_args()
    assert _valor(args, "--tools") == "WebSearch" and _valor(args, "--allowedTools") == "WebSearch,mcp__x__agenda"


def test_cada_abertura_do_celular_e_conversa_nova(monkeypatch):
    monkeypatch.setitem(jarvis.CFG, "celular", {})
    assert _valor(jarvis._celular_args(), "--session-id") != _valor(jarvis._celular_args(), "--session-id")


# ------------------------------------------------------------------ o celular nao atrapalha o Jarvis local
class _ProcFalso:
    """Claude de mentira: ao receber o pedido (stdin) devolve os eventos combinados."""

    def __init__(self, ao_receber):
        self.stdin = type("S", (), {"write": lambda s, b: ao_receber(), "flush": lambda s: None})()

    def poll(self):
        return None

    def kill(self):
        pass


def _sessao_com_eventos(eventos, **kw):
    s = jarvis.SessaoClaude(**kw)

    def abrir(args, env):
        s.proc = _ProcFalso(lambda: [s.fila.put(ev) for ev in eventos])

    s.abrir = abrir
    return s


def _eventos_com_ferramenta():
    return [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "WebSearch"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}},
        {"type": "result", "result": "ok", "session_id": "s"},
    ]


def test_ferramentas_do_celular_nao_aparecem_no_jarvis_local(monkeypatch):
    local = [{"id": "x", "label": "Lendo arquivo", "done": False}]
    monkeypatch.setitem(jarvis.CURRENT, "tools", local)
    s = _sessao_com_eventos(_eventos_com_ferramenta(), ferramentas=[])
    r, erro = s.perguntar([], {}, "oi", 5)
    assert r["result"] == "ok" and erro == ""
    assert [t["label"] for t in s.ferramentas] == ["Pesquisando na web"] and s.ferramentas[0]["done"]
    assert jarvis.CURRENT["tools"] is local and local == [{"id": "x", "label": "Lendo arquivo", "done": False}]


def test_sessao_local_continua_usando_a_lista_do_painel(monkeypatch):
    monkeypatch.setitem(jarvis.CURRENT, "tools", [])
    s = _sessao_com_eventos(_eventos_com_ferramenta())
    s.perguntar([], {}, "oi", 5)
    assert [t["label"] for t in jarvis.CURRENT["tools"]] == ["Pesquisando na web"]


def test_celular_tem_sessao_propria_e_fecha_rapido(monkeypatch):
    assert jarvis._sessao_celular is not jarvis._sessao
    assert jarvis._sessao_celular.ferramentas is not None and jarvis._sessao.ferramentas is None
    monkeypatch.setitem(jarvis.CFG, "celular", {})
    assert jarvis._sessao_celular.minutos_ociosos() == 3.0
    monkeypatch.setitem(jarvis.CFG, "celular", {"idle_minutes": 1})
    assert jarvis._sessao_celular.minutos_ociosos() == 1.0
    monkeypatch.setitem(jarvis.CFG, "claude_idle_minutes", 20)
    assert jarvis._sessao.minutos_ociosos() == 20.0  # o do PC continua com o tempo dele


@pytest.fixture
def lista(tmp_path, monkeypatch):
    lst = tarefas.Tarefas(tmp_path / "t.json", tmp_path / "T.md", agora=lambda: datetime(2026, 11, 27, 10, 0),
                          perguntar_prazo=True)
    monkeypatch.setattr(jarvis, "tarefas_lista", lambda: lst)
    return lst


def test_responder_celular_espera_se_o_jarvis_do_pc_esta_ocupado(monkeypatch, lista):
    monkeypatch.setattr(jarvis._sessao_celular, "perguntar", lambda *a: pytest.fail("nao devia chamar o Claude"))
    assert jarvis._busy.acquire(blocking=False)
    try:
        with pytest.raises(celular.Ocupado, match="computador"):
            jarvis.responder_celular("qual a previsao do tempo?")
    finally:
        jarvis._busy.release()


def _celular_com_memoria(monkeypatch, info, cfg=None):
    monkeypatch.setattr(jarvis._sessao_celular, "vivo", lambda: False)
    monkeypatch.setattr(jarvis, "sistema_info", lambda: info)
    monkeypatch.setitem(jarvis.CFG, "celular", cfg or {})
    chamadas = []
    monkeypatch.setattr(jarvis._sessao_celular, "perguntar", lambda *a: (chamadas.append(1), ({"result": "Pronto."}, ""))[1])
    return chamadas


def test_responder_celular_espera_se_falta_memoria_disponivel(monkeypatch, lista):
    chamadas = _celular_com_memoria(monkeypatch, {"mem": 96, "livre_mb": 200})
    with pytest.raises(celular.Ocupado, match="memoria"):
        jarvis.responder_celular("qual a previsao do tempo?")
    assert chamadas == []


def test_memoria_percentual_alta_mas_com_mb_de_sobra_nao_recusa(monkeypatch, lista):
    # o que importa e a memoria DISPONIVEL: 97% em uso com 900 MB sobrando (cache) deixa o celular responder
    chamadas = _celular_com_memoria(monkeypatch, {"mem": 97, "livre_mb": 900})
    assert jarvis.responder_celular("qual a previsao do tempo?") == "Pronto." and chamadas == [1]


def test_limite_de_memoria_do_celular_e_ajustavel(monkeypatch, lista):
    chamadas = _celular_com_memoria(monkeypatch, {"mem": 96, "livre_mb": 200}, {"mem_min_livre_mb": 0})  # 0 = sem limite
    assert jarvis.responder_celular("oi") == "Pronto." and chamadas == [1]
    _celular_com_memoria(monkeypatch, {"mem": 96, "livre_mb": 900}, {"mem_min_livre_mb": 1000})
    with pytest.raises(celular.Ocupado):
        jarvis.responder_celular("oi")
    _celular_com_memoria(monkeypatch, {"mem": 96, "livre_mb": 900}, {"mem_max_pct": 95})  # limite percentual opcional
    with pytest.raises(celular.Ocupado):
        jarvis.responder_celular("oi")


def test_sistema_info_informa_a_memoria_disponivel():
    info = jarvis.sistema_info()
    assert info["livre_mb"] > 0 and 0 <= info["mem"] <= 100


def test_responder_celular_com_claude_aberto_nao_checa_memoria_e_limpa_a_fala(monkeypatch, lista):
    monkeypatch.setattr(jarvis._sessao_celular, "vivo", lambda: True)
    monkeypatch.setattr(jarvis, "sistema_info", lambda: pytest.fail("nao devia checar"))
    visto = {}

    def perguntar(args, env, prompt, timeout):
        visto["prompt"], visto["timeout"] = prompt, timeout
        return {"result": "**Sao tres horas**, senhor. https://exemplo.com"}, ""

    monkeypatch.setattr(jarvis._sessao_celular, "perguntar", perguntar)
    monkeypatch.setitem(jarvis.CFG, "celular", {"timeout_seconds": 33})
    r = jarvis.responder_celular("que horas sao")
    assert "**" not in r and "https" not in r and "tres horas" in r
    assert visto["timeout"] == 33 and visto["prompt"].endswith("que horas sao")
    monkeypatch.setattr(jarvis._sessao_celular, "perguntar", lambda *a: (None, "erro interno"))
    assert "Nao consegui" in jarvis.responder_celular("oi")


# ------------------------------------------------------------------ tarefas pelo celular
def test_celular_anota_e_lista_tarefas_sem_chamar_o_claude(monkeypatch, lista):
    monkeypatch.setattr(jarvis, "_busy", threading.Lock())
    monkeypatch.setattr(jarvis._sessao_celular, "perguntar", lambda *a: pytest.fail("tarefa nao vai ao Claude"))
    r = jarvis.responder_celular("anote tarefa ligar para o contador para amanhã")
    assert "Anotado" in r and "Para quando" not in r
    assert [t["texto"] for t in lista.abertas()] == ["ligar para o contador"]
    assert "contador" in jarvis.responder_celular("quais são as minhas tarefas")


def test_celular_nao_mexe_na_pergunta_de_prazo_do_pc(lista):
    lista.pendente_prazo = (7, datetime(2026, 11, 27, 10, 5))
    jarvis.responder_celular("anote tarefa comprar pão")  # sem data: o PC perguntaria "Para quando?"
    assert lista.pendente_prazo == (7, datetime(2026, 11, 27, 10, 5))  # intacta
    lista.pendente_prazo = None
    jarvis.responder_celular("anote tarefa comprar leite")
    assert lista.pendente_prazo is None  # o celular nao deixa pergunta pendente no PC


def test_celular_conclui_mas_nao_remove_nem_desfaz(lista):
    t, _ = lista.adicionar("pagar o boleto")
    assert "Concluída" in jarvis.responder_celular("conclua a tarefa 1")
    assert lista.abertas() == []
    t2, _ = lista.adicionar("regar as plantas")
    for frase in ("remova a tarefa 1", "apague a tarefa regar as plantas", "exclua a tarefa 1", "desfazer", "desfaz a ultima alteracao"):
        assert jarvis.responder_celular(frase) == jarvis.MSG_SO_NO_PC, frase
    assert [x["texto"] for x in lista.abertas()] == ["regar as plantas"]  # nada foi removido
    r = jarvis.celular_tarefa_adicionar("remova a tarefa 1", None)
    assert r["erro"] and r["mensagem"] == jarvis.MSG_SO_NO_PC and len(lista.abertas()) == 1


def test_tarefa_adicionar_pelo_campo_da_tela(lista):
    # sem data no texto: entra sem data, sem perguntar "para quando?" (mesmo com perguntar_prazo ligado no PC)
    r = jarvis.celular_tarefa_adicionar("revisar contrato", None)
    assert r["mudou"] and r["pergunta"] is False and [t["prazo"] for t in lista.abertas()] == [None]
    r = jarvis.celular_tarefa_adicionar("ligar para a Ana para sexta", None)  # data dita no texto vale
    assert r["mudou"] and sorted(t["prazo"] or "" for t in lista.abertas()) == ["", "2026-12-04"]
    r = jarvis.celular_tarefa_adicionar("pagar boleto", "amanhã")  # escolha explicita continua valendo
    assert r["mudou"] and "2026-11-28" in [t["prazo"] for t in lista.abertas()]
    r = jarvis.celular_tarefa_adicionar("comprar pão", "")  # "sem data"
    assert r["mudou"] and len(lista.abertas()) == 4
    r = jarvis.celular_tarefa_adicionar("outra coisa", "quando der na telha")
    assert r["erro"] and r["pergunta"] and len(lista.abertas()) == 4
    assert lista.pendente_prazo is None  # nada pendente no PC


def test_tarefas_e_concluir_pelo_celular(lista):
    a, _ = lista.adicionar("um", prazo="2026-11-30")
    b, _ = lista.adicionar("dois")
    rev = jarvis.CURRENT["rev"]
    d = jarvis.celular_tarefas()
    assert {t["texto"] for t in d["abertas"]} == {"um", "dois"} and d["concluidas"] == []
    assert jarvis.celular_tarefa_concluir(a["id"]) and jarvis.CURRENT["rev"] == rev + 1  # o painel do PC atualiza
    assert not jarvis.celular_tarefa_concluir(a["id"]) and not jarvis.celular_tarefa_concluir(999)
    assert [t["texto"] for t in jarvis.celular_tarefas()["abertas"]] == ["dois"]
    assert [t["texto"] for t in jarvis.celular_tarefas()["concluidas"]] == ["um"]


# ------------------------------------------------------------------ voz e transcricao
def test_celular_falar_devolve_wav_na_mesma_voz(monkeypatch):
    import soundfile as sf

    pedidos = []

    def gerar(frase):
        pedidos.append(frase)
        return np.full(2400, 0.2, dtype="float32"), 24000

    monkeypatch.setitem(jarvis.CFG, "tts_engine", "fish")
    monkeypatch.setattr(jarvis, "_gerador_fish", lambda: gerar)
    longa = "Esta e a primeira frase de teste, bem comprida para nao ser juntada. "
    wav = jarvis.celular_falar(longa + "Esta e a segunda frase de teste, tambem comprida o bastante.")
    assert len(pedidos) >= 2
    audio, sr = sf.read(io.BytesIO(wav), dtype="float32")
    assert sr == 24000 and len(audio) == 2400 * len(pedidos) and abs(float(audio.max()) - 0.2) < 0.01


def test_celular_falar_reamostra_se_a_reserva_tiver_outra_taxa(monkeypatch):
    import soundfile as sf

    taxas = iter([(np.zeros(2400, "float32"), 24000), (np.zeros(1600, "float32"), 16000)])
    monkeypatch.setitem(jarvis.CFG, "tts_engine", "edge")
    monkeypatch.setattr(jarvis, "_gerador_edge_com_reserva", lambda: (lambda frase: next(taxas)))
    frase = "Esta e a primeira frase de teste, bem comprida para nao ser juntada. "
    audio, sr = sf.read(io.BytesIO(jarvis.celular_falar(frase + "Esta e a segunda frase de teste, tambem comprida o bastante.")), dtype="float32")
    assert sr == 24000 and len(audio) == 2400 + 2400  # 1600 amostras a 16 kHz = 2400 a 24 kHz


def test_celular_falar_sem_voz_neural_devolve_none(monkeypatch):
    monkeypatch.setitem(jarvis.CFG, "tts_engine", "sapi")
    assert jarvis._gerador_de_voz() is None and jarvis.celular_falar("oi") is None


def test_gerador_de_voz_segue_o_motor_do_config(monkeypatch):
    monkeypatch.setattr(jarvis, "_gerador_fish", lambda: "fish")
    monkeypatch.setattr(jarvis, "_gerador_edge_com_reserva", lambda: "edge")
    monkeypatch.setattr(jarvis, "_kokoro_gerador", lambda: "kokoro")
    for motor in ("fish", "edge", "kokoro"):
        monkeypatch.setitem(jarvis.CFG, "tts_engine", motor)
        assert jarvis._gerador_de_voz() == motor


def _gravar(formato, codec, taxa_arquivo, segundos=1.5):
    av = pytest.importorskip("av")
    sr = 16000
    x = (0.3 * np.sin(2 * np.pi * 440 * np.arange(int(sr * segundos)) / sr)).astype("float32")
    buf = io.BytesIO()
    with av.open(buf, "w", format=formato) as c:
        s = c.add_stream(codec, rate=taxa_arquivo)
        fr = av.AudioFrame.from_ndarray(x[None, :], format="flt", layout="mono")
        fr.sample_rate = sr
        frames = [fr] if taxa_arquivo == sr else av.AudioResampler(format="flt", layout="mono", rate=taxa_arquivo).resample(fr)
        for f in frames:
            for p in s.encode(f):
                c.mux(p)
        for p in s.encode(None):
            c.mux(p)
    return buf.getvalue()


@pytest.mark.parametrize("formato,codec,taxa", [("mp4", "aac", 16000), ("webm", "libopus", 48000), ("wav", "pcm_s16le", 16000)])
def test_decodifica_gravacoes_do_iphone_e_do_android(formato, codec, taxa):
    audio = jarvis.decodificar_audio(_gravar(formato, codec, taxa))
    assert audio.dtype == np.float32 and 1.3 < len(audio) / 16000 < 1.7 and 0.1 < float(np.abs(audio).max()) <= 1.0


def test_decodificar_audio_rejeita_lixo():
    pytest.importorskip("av")
    with pytest.raises(Exception):  # noqa: B017  (o PyAV levanta tipos diferentes conforme o lixo)
        jarvis.decodificar_audio(b"isto nao e audio" * 100)


def test_celular_transcrever_usa_o_whisper_local(monkeypatch):
    class Seg:
        def __init__(self, t):
            self.text = t

    chamado = {}

    class Modelo:
        def transcribe(self, amostras, **kw):
            chamado["n"], chamado["kw"] = len(amostras), kw
            return [Seg(" que horas"), Seg(" sao? ")], None

    monkeypatch.setattr(jarvis, "get_whisper", lambda: Modelo())
    monkeypatch.setattr(jarvis, "_busy", threading.Lock())
    texto = jarvis.celular_transcrever(_gravar("mp4", "aac", 16000))
    assert texto == "que horas sao?" and chamado["kw"]["language"] == jarvis.CFG["stt_language"] and chamado["n"] > 20000


def test_celular_transcrever_audio_curto_ou_longo_e_pc_ocupado(monkeypatch):
    monkeypatch.setattr(jarvis, "get_whisper", lambda: pytest.fail("nao devia transcrever"))
    assert jarvis.celular_transcrever(_gravar("wav", "pcm_s16le", 16000, segundos=0.1)) == ""
    with pytest.raises(ValueError):
        jarvis.celular_transcrever(_gravar("wav", "pcm_s16le", 16000, segundos=76))
    assert jarvis._busy.acquire(blocking=False)
    try:
        with pytest.raises(celular.Ocupado, match="computador"):
            jarvis.celular_transcrever(b"qualquer")
    finally:
        jarvis._busy.release()


# ------------------------------------------------------------------ aba Painel: /api/resumo
def test_resumo_exige_token_e_devolve_os_dados():
    falso = _Falso()
    g = falso.ganchos()
    g.resumo = lambda: {"agora": 1, "sistema": {"cpu": 10}, "tarefas": {"abertas": 3}}
    srv, base = _subir(g)
    try:
        assert _chamar(base, "/api/resumo", token=None)[0] == 401
        code, r, _ = _chamar(base, "/api/resumo")
        assert code == 200 and r["ok"] is True and r["sistema"] == {"cpu": 10} and r["tarefas"]["abertas"] == 3
        assert _chamar(base, "/api/resumo", {"a": 1})[0] == 404  # so leitura: POST nao existe
    finally:
        srv.shutdown()
        srv.server_close()


def test_resumo_sem_gancho_e_com_erro_nao_vaza(servidor):
    base, _, _ = servidor
    assert _chamar(base, "/api/resumo")[0] == 404  # o _Falso padrao nao traz resumo
    g = _Falso().ganchos()

    def quebra():
        raise RuntimeError("segredo /dados/privados")

    g.resumo = quebra
    srv, base2 = _subir(g)
    try:
        code, r, _ = _chamar(base2, "/api/resumo")
    finally:
        srv.shutdown()
        srv.server_close()
    assert code == 500 and r["ok"] is False and "segredo" not in json.dumps(r)


def _resumo_com(monkeypatch, lista, **over):
    monkeypatch.setitem(jarvis._cpu_prev_canais, "celular", (0, 0, 0))
    monkeypatch.setattr(jarvis, "sistema_info", lambda canal="": {"cpu": 12, "mem": 94, "livre_mb": 800, "uptime_s": 99, "extra": 1})
    monkeypatch.setitem(jarvis.CFG, "painel", {"clima": {"enabled": False}, "musica": {"enabled": False},
                                               "uso_claude": {"enabled": False}})
    for k, v in over.items():
        monkeypatch.setattr(jarvis, k, v)
    return jarvis._montar_resumo()


def test_resumo_so_traz_o_que_o_celular_precisa(monkeypatch, lista):
    lista.adicionar("vencida", prazo="2026-11-20")
    lista.adicionar("de hoje", prazo="2026-11-27")
    lista.adicionar("sem data")
    r = _resumo_com(monkeypatch, lista)
    assert r["sistema"] == {"cpu": 12, "mem": 94, "livre_mb": 800, "uptime_s": 99}  # sem campos a mais
    assert r["tarefas"] == {"abertas": 3, "hoje": 1, "vencidas": 1}
    assert "clima" not in r and "uso" not in r and "musica" not in r  # desligados no config
    assert set(r) == {"agora", "sistema", "tarefas"}


def test_resumo_inclui_clima_uso_e_musica_ligados(monkeypatch, lista):
    import clima
    import musica
    import uso_claude

    monkeypatch.setattr(clima, "obter", lambda cfg: {"ok": True, "temp": 23, "condicao": "Nublado", "icone": "nuvem", "cidade": "X"})
    monkeypatch.setattr(uso_claude, "obter", lambda: {"ok": True, "plano": "Pro", "limites": []})
    monkeypatch.setattr(musica, "snapshot", lambda app: {"ativo": True, "app": "Spotify", "titulo": "T", "artista": "A", "estado": "tocando",
                                                          "posicao_s": 1, "duracao_s": 2, "capa": True, "cor": "#fff", "pode": {}})
    r = _resumo_com(monkeypatch, lista, clima_cfg=lambda: {"enabled": True}, uso_claude_ligado=lambda: True, musica_ligada=lambda: True)
    assert r["clima"]["temp"] == 23 and r["uso"]["plano"] == "Pro"
    assert r["musica"] == {"ativo": True, "app": "Spotify", "titulo": "T", "artista": "A", "estado": "tocando",
                           "posicao_s": 1, "duracao_s": 2}  # sem capa, cor nem controles


def test_cada_parte_do_resumo_falha_sozinha(monkeypatch, lista):
    import clima

    def quebra(*a, **k):
        raise RuntimeError("falhou")

    monkeypatch.setattr(clima, "obter", quebra)
    lista.adicionar("uma")
    r = _resumo_com(monkeypatch, lista, clima_cfg=lambda: {"enabled": True})
    assert "clima" not in r and r["tarefas"]["abertas"] == 1 and r["sistema"]["cpu"] == 12


def test_resumo_usa_cache_curto(monkeypatch, lista):
    chamadas = []
    monkeypatch.setattr(jarvis, "_montar_resumo", lambda: (chamadas.append(1), {"agora": len(chamadas)})[1])
    monkeypatch.setitem(jarvis._resumo_celular, "dados", None)
    a, b = jarvis.celular_resumo(), jarvis.celular_resumo()
    assert a is b and len(chamadas) == 1
    monkeypatch.setitem(jarvis._resumo_celular, "quando", time.monotonic() - jarvis.RESUMO_TTL - 1)
    assert jarvis.celular_resumo()["agora"] == 2


def test_cpu_do_celular_tem_janela_propria(monkeypatch):
    monkeypatch.setattr(jarvis, "_cpu_prev", None)
    monkeypatch.setattr(jarvis, "_cpu_prev_canais", {})
    jarvis.sistema_info("celular")
    assert jarvis._cpu_prev is None and "celular" in jarvis._cpu_prev_canais  # nao encurta a medida do painel do PC
    jarvis.sistema_info()
    assert jarvis._cpu_prev is not None


def test_pagina_tem_as_tres_abas():
    html = (Path(__file__).resolve().parent.parent / "celular.html").read_text(encoding="utf-8")
    for id_ in ("v-conversa", "v-painel", "v-tarefas", "n-conversa", "n-painel", "n-tarefas", "c-hoje", "c-uso", "c-tarefas", "c-musica"):
        assert f'id="{id_}"' in html, id_
    assert "/api/resumo" in html


# ------------------------------------------------------------------ widget do iPhone (Scriptable)
WIDGET = Path(__file__).resolve().parent.parent / "docs" / "widget" / "jarvis-tarefas.js"


def test_widget_nao_traz_endereco_nem_token_e_so_le_tarefas():
    js = WIDGET.read_text(encoding="utf-8")
    assert "Keychain.set(CHAVE_URL" in js and "Keychain.set(CHAVE_TOKEN" in js  # guarda no Keychain do iPhone
    assert "/api/tarefas" in js and "/api/perguntar" not in js and "/api/falar" not in js
    assert "ts.net" not in js.replace("meu-pc.minha-rede.ts.net", "")  # so o exemplo generico
    assert 'method = "POST"' not in js


def test_widget_tem_sintaxe_valida():
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node nao instalado")
    r = subprocess.run([node, "--check", str(WIDGET)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# ------------------------------------------------------------------ comando de voz de tarefas no celular
@pytest.mark.parametrize("frase", ["anote tarefa comprar café", "inclua uma tarefa comprar café", "nova tarefa comprar café",
                                   "adicione a tarefa comprar café", "anota aí comprar café"])
def test_voz_no_celular_anota_sem_perguntar_a_data(monkeypatch, lista, frase):
    monkeypatch.setattr(jarvis, "_busy", threading.Lock())
    monkeypatch.setattr(jarvis._sessao_celular, "perguntar", lambda *a: pytest.fail("tarefa nao vai ao Claude"))
    r = jarvis.responder_celular(frase)
    assert r.startswith("Anotado") and "quando" not in r.lower()
    assert [t["texto"] for t in lista.abertas()] == ["comprar café"] and lista.abertas()[0]["prazo"] is None
    assert lista.pendente_prazo is None  # nada ficou esperando resposta


def test_voz_no_celular_com_data_dita_usa_a_data(lista):
    r = jarvis.responder_celular("anote tarefa ligar para o contador para amanhã")
    assert "amanhã" in r and [t["prazo"] for t in lista.abertas()] == ["2026-11-28"]


def test_voz_no_celular_conclui_de_varias_formas(lista):
    for texto in ("pagar o boleto", "ligar para o contador", "revisar contrato", "enviar relatório"):
        lista.adicionar(texto)
    assert jarvis.responder_celular("marque a tarefa 1 como concluída").startswith("Conclu")
    assert jarvis.responder_celular("já fiz a tarefa do contador").startswith("Conclu")
    assert jarvis.responder_celular("pronto, terminei a tarefa do relatório").startswith("Conclu")
    assert [t["texto"] for t in lista.abertas()] == ["revisar contrato"]
