"""Consumo do plano do Claude Code no painel: resumo, cache, falhas e o cuidado de nunca vazar o login."""
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uso_claude  # noqa: E402
from uso_claude import Consumo, SemCredencial  # noqa: E402

RESPOSTA = {
    "five_hour": {"utilization": 2.0, "resets_at": "2026-11-24T15:50:00.047863+00:00"},
    "seven_day": {"utilization": 48.0, "resets_at": "2026-11-25T23:00:00.047886+00:00"},
    "limits": [
        {"kind": "session", "percent": 2, "resets_at": "2026-11-24T15:50:00.047863+00:00"},
        {"kind": "weekly_all", "percent": 48, "resets_at": "2026-11-25T23:00:00.047886+00:00"},
    ],
    "seven_day_breakdown": {"rows": [
        {"key": "chat", "display_name": "Chats", "percent": 0, "percent_of_limit": 0},
        {"key": "claude_code", "display_name": "Claude Code", "percent": 77, "percent_of_limit": 37},
        {"key": "cowork", "display_name": "Cowork", "percent": 22, "percent_of_limit": 10},
        {"key": "other", "display_name": "Other", "percent": 1, "percent_of_limit": 1},
    ]},
}


def test_resumir_traz_sessao_semana_e_origens():
    r = uso_claude.resumir(RESPOSTA, "Pro")
    assert r["ok"] and r["plano"] == "Pro"
    sess, sem = r["limites"]
    assert (sess["id"], sess["pct"], sess["nivel"]) == ("session", 2, "normal")
    assert (sem["id"], sem["pct"]) == ("weekly_all", 48)
    assert sess["reinicia"] == 1795535400            # 2026-11-24 15:50 UTC, em segundos
    assert [o["nome"] for o in r["origens"]] == ["Claude Code", "Cowork", "Outros"]   # sem os zerados, maior primeiro
    assert [o["pct"] for o in r["origens"]] == [37, 10, 1]


def test_resumir_sem_lista_limits_usa_os_campos_antigos_e_nao_duplica():
    antigo = {k: v for k, v in RESPOSTA.items() if k != "limits"}
    assert [x["id"] for x in uso_claude.resumir(antigo)["limites"]] == ["session", "weekly_all"]
    assert len(uso_claude.resumir(RESPOSTA)["limites"]) == 2            # limits + campos antigos: cada um uma vez


def test_resumir_niveis_e_limites_do_percentual():
    assert [uso_claude.nivel(p) for p in (0, 69, 70, 89, 90, 100)] == ["normal", "normal", "atencao", "atencao", "critico", "critico"]
    r = uso_claude.resumir({"five_hour": {"utilization": 250, "resets_at": None}, "seven_day": {"utilization": -3}})
    assert [x["pct"] for x in r["limites"]] == [100, 0]
    assert r["limites"][0]["reinicia"] is None


def test_resumir_resposta_estranha_nao_quebra():
    for lixo in ({}, {"limits": "x"}, {"limits": [None, 3, {"kind": 5}], "seven_day_breakdown": []},
                 {"five_hour": {"utilization": "alto"}}, {"five_hour": {"utilization": True}}):
        assert uso_claude.resumir(lixo)["ok"] is False
    r = uso_claude.resumir({"five_hour": {"utilization": 5, "resets_at": "ontem"}, "seven_day_breakdown": {"rows": [1, {"display_name": 3}]}})
    assert r["ok"] and r["limites"][0]["reinicia"] is None and r["origens"] == []


def _cred(tmp_path, expira_ms, **extra):
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps({"claudeAiOauth": {"accessToken": "TOKEN-SECRETO", "expiresAt": expira_ms, "subscriptionType": "pro", **extra}}),
                 encoding="utf-8")
    return p


def test_ler_credencial_valida_vencida_e_ausente(tmp_path):
    assert uso_claude.ler_credencial(agora=1000, caminho=_cred(tmp_path, 5_000_000)) == ("TOKEN-SECRETO", "Pro")
    with pytest.raises(SemCredencial, match="vencido"):
        uso_claude.ler_credencial(agora=10_000, caminho=_cred(tmp_path, 5_000_000))     # o Jarvis nao renova o login
    with pytest.raises(SemCredencial, match="Sem login"):
        uso_claude.ler_credencial(caminho=tmp_path / "nao-existe.json")
    ruim = tmp_path / "ruim.json"
    ruim.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(SemCredencial):
        uso_claude.ler_credencial(caminho=ruim)
    ruim.write_text(json.dumps({"claudeAiOauth": {"accessToken": ""}}), encoding="utf-8")
    with pytest.raises(SemCredencial):
        uso_claude.ler_credencial(caminho=ruim)


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _consumo(respostas, relogio, cred=lambda: ("t", "Pro"), ttl=120):
    chamadas = []

    def http(token):
        chamadas.append(token)
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    return Consumo(credencial=cred, http=http, relogio=relogio, ttl=ttl), chamadas


def test_cache_consulta_so_uma_vez_por_ttl():
    rel = Relogio()
    c, chamadas = _consumo([RESPOSTA, RESPOSTA], rel)
    a = c.obter()
    rel.t += 100
    assert c.obter() == a and len(chamadas) == 1
    rel.t += 30                                       # passou do ttl (120 s)
    c.obter()
    assert len(chamadas) == 2
    assert a["ok"] and a["atualizado"] == 1000 and "velho" not in a


def test_falha_mostra_motivo_e_tenta_de_novo_logo():
    rel = Relogio()
    erro = urllib.error.HTTPError("u", 503, "x", {}, None)
    c, chamadas = _consumo([erro, RESPOSTA], rel)
    r = c.obter()
    assert r["ok"] is False and "503" in r["motivo"]
    assert c.obter() == r and len(chamadas) == 1       # dentro do TTL_ERRO nao insiste
    rel.t += uso_claude.TTL_ERRO + 1
    assert c.obter()["ok"] is True


def test_dado_bom_vira_reserva_marcada_como_velho():
    rel = Relogio()
    c, _ = _consumo([RESPOSTA, OSError("sem rede"), OSError("sem rede")], rel)
    assert c.obter()["ok"]
    rel.t += 200
    r = c.obter()
    assert r["ok"] and r["velho"] is True and "conexão" in r["motivo"]
    rel.t += uso_claude.VELHO_MAX + 200                # velho demais: so o erro
    r = c.obter()
    assert r["ok"] is False and "conexão" in r["motivo"]


def test_http_401_e_429_tem_mensagens_proprias():
    for codigo, trecho in ((401, "recusou"), (429, "Muitas")):
        c, _ = _consumo([urllib.error.HTTPError("u", codigo, "x", {}, None)], Relogio())
        assert trecho in c.obter()["motivo"]


def test_sem_credencial_nao_chama_a_rede_e_relê_logo():
    rel = Relogio()
    estado = {"ok": False}

    def cred():
        if not estado["ok"]:
            raise SemCredencial("Login do Claude Code vencido.")
        return "t", "Pro"

    c, chamadas = _consumo([RESPOSTA], rel, cred=cred)
    assert c.obter()["ok"] is False and chamadas == []
    estado["ok"] = True                                # o Claude Code renovou o login
    rel.t += 11
    assert c.obter()["ok"] is True and len(chamadas) == 1


def test_resposta_sem_numeros_nao_apaga_o_ultimo_dado_bom():
    rel = Relogio()
    c, _ = _consumo([RESPOSTA, {}], rel)
    c.obter()
    rel.t += 200
    r = c.obter()
    assert r["ok"] and r["velho"] is True


def test_o_token_nunca_aparece_na_saida():
    rel = Relogio()
    c, _ = _consumo([RESPOSTA], rel, cred=lambda: ("TOKEN-SECRETO", "Pro"))
    assert "TOKEN-SECRETO" not in json.dumps(c.obter())
