"""Clima da cidade no painel: descricao, cache de 1 h, falhas e o que sai para a rede."""
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clima  # noqa: E402
from clima import Clima  # noqa: E402

CFG = {"enabled": True, "cidade": "Jundiaí", "lat": -23.19, "lon": -46.9}
RESP = {"current": {"time": "2026-11-24T08:00", "temperature_2m": 24.7, "weather_code": 2, "is_day": 1}}


class Relogio:
    t = 1000.0

    def __call__(self):
        return self.t


def _clima(respostas, rel, ttl=3600):
    chamadas = []

    def http(lat, lon):
        chamadas.append((lat, lon))
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    return Clima(http=http, relogio=rel, ttl=ttl), chamadas


def test_descrever_condicoes_e_noite():
    assert clima.descrever(2) == ("Parcialmente nublado", "nuvem-sol")
    assert clima.descrever(2, dia=False) == ("Parcialmente nublado", "nuvem-lua")
    assert clima.descrever(0, dia=False) == ("Céu limpo", "lua")
    assert clima.descrever(63) == ("Chuva", "chuva")
    assert clima.descrever(95)[1] == "tempestade"
    assert clima.descrever(1234) == ("Tempo indefinido", "nuvem") and clima.descrever(None)[0] == "Tempo indefinido"
    assert clima.descrever(True)[0] == "Tempo indefinido"
    for codigo, (texto, icone) in clima.WMO.items():           # todo codigo tem texto e um icone que o painel desenha
        assert texto and icone in {"sol", "nuvem-sol", "nuvem", "neblina", "chuva", "neve", "tempestade"}, codigo


def test_resumir_arredonda_e_rejeita_lixo():
    r = clima.resumir(RESP, "Jundiaí")
    assert r == {"ok": True, "cidade": "Jundiaí", "temp": 25, "condicao": "Parcialmente nublado", "icone": "nuvem-sol"}
    assert clima.resumir({"current": {**RESP["current"], "is_day": 0}})["icone"] == "nuvem-lua"
    assert clima.resumir({"current": {"temperature_2m": -0.4, "weather_code": 0}})["temp"] == 0
    for lixo in ({}, None, {"current": None}, {"current": {"temperature_2m": "quente"}}, {"current": {"temperature_2m": 999}},
                 {"current": {"temperature_2m": True}}):
        assert clima.resumir(lixo)["ok"] is False


def test_coordenadas_validas_e_arredondadas():
    assert clima.coordenadas({"lat": -23.1857, "lon": -46.8978}) == (-23.19, -46.9)      # so a cidade, nunca um ponto exato
    assert clima.coordenadas({"lat": "-23.5", "lon": "-46.6"}) == (-23.5, -46.6)
    for ruim in ({}, {"lat": 1}, {"lat": 91, "lon": 0}, {"lat": 0, "lon": 181}, {"lat": "x", "lon": 1}, {"lat": None, "lon": None}):
        assert clima.coordenadas(ruim) is None


def test_consulta_a_rede_so_uma_vez_por_hora():
    rel = Relogio()
    c, chamadas = _clima([RESP, RESP], rel)
    a = c.obter(CFG)
    assert a["ok"] and a["temp"] == 25 and a["cidade"] == "Jundiaí" and a["atualizado"] == 1000
    rel.t += 3599
    assert c.obter(CFG) == a and len(chamadas) == 1                       # dentro da hora: so o cache
    rel.t += 2
    c.obter(CFG)
    assert chamadas == [(-23.19, -46.9)] * 2                              # passou da hora: consulta de novo


def test_falha_tenta_em_5_minutos_e_mostra_o_ultimo_dado():
    rel = Relogio()
    c, chamadas = _clima([RESP, OSError("sem rede"), RESP], rel)
    c.obter(CFG)
    rel.t += 3601
    r = c.obter(CFG)
    assert r["ok"] and r["velho"] is True and r["temp"] == 25             # sem rede: nao some, marca como velho
    rel.t += 100
    c.obter(CFG)
    assert len(chamadas) == 2                                             # ainda nao passaram os 5 min
    rel.t += clima.TTL_ERRO
    r = c.obter(CFG)
    assert len(chamadas) == 3 and "velho" not in r


def test_sem_dado_bom_devolve_o_motivo_e_dado_muito_velho_some():
    rel = Relogio()
    c, _ = _clima([urllib.error.HTTPError("u", 500, "x", {}, None)], rel)
    r = c.obter(CFG)
    assert r["ok"] is False and "500" in r["motivo"]
    c2, _ = _clima([RESP, OSError("x"), OSError("x")], rel)
    c2.obter(CFG)
    rel.t += clima.VELHO_MAX + 3700
    assert c2.obter(CFG)["ok"] is False


def test_trocar_de_cidade_nao_mostra_o_clima_da_outra():
    rel = Relogio()
    outra = {"current": {"temperature_2m": 10.2, "weather_code": 3, "is_day": 1}}
    c, chamadas = _clima([RESP, outra], rel)
    assert c.obter(CFG)["temp"] == 25
    r = c.obter({**CFG, "cidade": "Curitiba", "lat": -25.43, "lon": -49.27})
    assert r["temp"] == 10 and r["cidade"] == "Curitiba" and chamadas[-1] == (-25.43, -49.27)


def test_sem_coordenadas_fica_desligado_sem_chamar_a_rede():
    c, chamadas = _clima([], Relogio())
    r = c.obter({"enabled": True, "cidade": "X"})
    assert r["ok"] is False and r["desligado"] is True and chamadas == []


def test_so_as_coordenadas_da_cidade_vao_para_a_rede(monkeypatch):
    visto = {}

    class Resp:
        def read(self, n=-1):
            return b'{"current": {"temperature_2m": 20, "weather_code": 0, "is_day": 1}}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def falso(req, timeout=0):
        visto["url"], visto["cab"] = req.full_url, dict(req.header_items())
        return Resp()

    monkeypatch.setattr(clima.urllib.request, "urlopen", falso)
    assert clima._http(-23.19, -46.9)["current"]["temperature_2m"] == 20
    assert visto["url"].startswith("https://api.open-meteo.com/") and "latitude=-23.19" in visto["url"]
    assert not any(k.lower() in ("authorization", "cookie") for k in visto["cab"])
