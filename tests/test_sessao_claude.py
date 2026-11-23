"""Claude aberto entre os pedidos (SessaoClaude), com um 'claude' de mentira: sem rede, sem custo."""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jarvis  # noqa: E402

FALSO = r'''
import json, os, sys, time
modo = os.environ.get("FALSO_MODO", "ok")
for linha in sys.stdin:
    msg = json.loads(linha)
    texto = msg["message"]["content"][0]["text"]
    if modo == "morre":
        sys.exit(3)
    if modo == "trava":
        time.sleep(60)
    if modo == "ferramenta_e_morre":
        print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]}}), flush=True)
        sys.exit(3)
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]}}), flush=True)
    print(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}}), flush=True)
    print(json.dumps({"type": "result", "result": f"pid={os.getpid()} eco={texto}", "session_id": "sid-falso"}), flush=True)
'''


@pytest.fixture()
def falso(tmp_path, monkeypatch):
    script = tmp_path / "claude_falso.py"
    script.write_text(FALSO, encoding="utf-8")
    monkeypatch.setitem(jarvis.CFG, "workdir", str(tmp_path))
    monkeypatch.setitem(jarvis.CFG, "claude_idle_minutes", 20)
    monkeypatch.setattr(jarvis, "CURRENT", {"tools": []})
    s = jarvis.SessaoClaude()
    yield s, [sys.executable, str(script), "-p", "--output-format", "stream-json"], {**__import__("os").environ}
    s.fechar()


def test_mesmo_processo_atende_varios_pedidos(falso):
    s, args, env = falso
    r1, _ = s.perguntar(args, env, "primeiro", 10)
    r2, _ = s.perguntar(args, env, "segundo", 10)
    assert r1["result"].endswith("eco=primeiro") and r2["result"].endswith("eco=segundo")
    assert r1["result"].split()[0] == r2["result"].split()[0]                     # mesmo pid: nao reabriu


def test_acompanha_ferramentas_em_uso(falso):
    s, args, env = falso
    s.perguntar(args, env, "x", 10)
    assert jarvis.CURRENT["tools"] == [{"id": "t1", "label": "Executando comando", "done": True}]


def test_aquecer_abre_antes_do_pedido(falso):
    s, args, env = falso
    assert not s.vivo()
    s.abrir(args, env)
    assert s.vivo()
    r1, _ = s.perguntar(args, env, "oi", 10)
    r2, _ = s.perguntar(args, env, "oi de novo", 10)
    assert r1["result"].split()[0] == r2["result"].split()[0]                     # o mesmo processo aquecido atendeu os dois


def test_reabre_se_o_processo_morreu_antes_de_agir(falso, monkeypatch):
    s, args, env = falso
    monkeypatch.setenv("FALSO_MODO", "ok")
    s.perguntar(args, {**env, "FALSO_MODO": "ok"}, "a", 10)
    s.proc.kill()
    s.proc.wait()
    r, erro = s.perguntar(args, {**env, "FALSO_MODO": "ok"}, "b", 10)
    assert r is not None and r["result"].endswith("eco=b")


def test_nao_repete_pedido_se_caiu_depois_de_usar_ferramenta(falso):
    s, args, env = falso
    r, erro = s.perguntar(args, {**env, "FALSO_MODO": "ferramenta_e_morre"}, "faz algo", 10)
    assert r is None and erro                                                      # sem 2a tentativa: poderia repetir a acao
    assert not s.vivo()


def test_processo_que_morre_sem_responder_falha_com_erro(falso):
    s, args, env = falso
    r, erro = s.perguntar(args, {**env, "FALSO_MODO": "morre"}, "x", 10)
    assert r is None and erro


def test_tempo_esgotado_fecha_o_processo(falso):
    s, args, env = falso
    t0 = time.time()
    r, erro = s.perguntar(args, {**env, "FALSO_MODO": "trava"}, "x", 1.5)
    assert r is None and erro == "tempo esgotado" and time.time() - t0 < 6
    assert not s.vivo()


def test_fechar_e_reabrir_gera_processo_novo(falso):
    s, args, env = falso
    pid1 = s.perguntar(args, env, "a", 10)[0]["result"].split()[0]
    s.fechar()
    assert not s.vivo()
    pid2 = s.perguntar(args, env, "b", 10)[0]["result"].split()[0]
    assert pid1 != pid2


def test_inatividade_fecha_o_processo(falso, monkeypatch):
    s, args, env = falso
    monkeypatch.setitem(jarvis.CFG, "claude_idle_minutes", 0.001)                  # ~0,06 s
    monkeypatch.setattr(jarvis.SessaoClaude, "INTERVALO_VIGIA", 0.05)
    s.perguntar(args, env, "a", 10)
    for _ in range(100):
        if not s.vivo():
            break
        time.sleep(0.05)
    assert not s.vivo()


def test_claude_args_incluem_modelo_e_esforco_so_se_configurados(monkeypatch):
    monkeypatch.setitem(jarvis.CFG, "claude_model", "")
    monkeypatch.setitem(jarvis.CFG, "claude_effort", "")
    a, _ = jarvis._claude_args({})
    assert "--model" not in a and "--effort" not in a
    monkeypatch.setitem(jarvis.CFG, "claude_model", "sonnet")
    monkeypatch.setitem(jarvis.CFG, "claude_effort", "low")
    a, _ = jarvis._claude_args({})
    assert a[a.index("--model") + 1] == "sonnet" and a[a.index("--effort") + 1] == "low"


def test_retoma_a_sessao_quando_ja_comecou(monkeypatch):
    a, sid = jarvis._claude_args({"session_id": "abc", "started": True})
    assert a[-2:] == ["--resume", "abc"] and sid == "abc"
    a, sid = jarvis._claude_args({})
    assert a[-2] == "--session-id" and a[-1] == sid and len(sid) == 36


def test_json_de_entrada_do_claude_e_uma_linha_por_pedido(falso):
    s, args, env = falso
    s.abrir(args, env)
    enviado = []
    real = s.proc.stdin
    class Espiao:
        def write(self, b): enviado.append(b); return real.write(b)
        def flush(self): return real.flush()
    s.proc.stdin = Espiao()
    s.perguntar(args, env, "linha 1\nlinha 2", 10)
    assert len(enviado) == 1 and enviado[0].endswith(b"\n") and enviado[0].count(b"\n") == 1   # a quebra vai escapada no JSON
    assert json.loads(enviado[0])["message"]["content"][0]["text"] == "linha 1\nlinha 2"
