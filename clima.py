"""Temperatura e condicao do tempo da sua cidade para o painel (Open-Meteo: gratis, sem chave nem cadastro).

So saem para a rede as coordenadas da CIDADE (arredondadas, de `painel.clima` do config) para api.open-meteo.com;
nada do usuario, do historico ou do Claude. Consulta no maximo uma vez por hora; se falhar, tenta de novo em 5 min e,
enquanto isso, mostra o ultimo dado (ate 6 h) em vez de sumir.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

URL = "https://api.open-meteo.com/v1/forecast"
TTL_PADRAO = 3600         # 1 h entre consultas
TTL_ERRO = 300            # depois de uma falha, tenta de novo em 5 min
VELHO_MAX = 6 * 3600

# codigo WMO -> (resumo em portugues, icone). O icone de ceu limpo/parcial troca por lua a noite (ver `descrever`).
WMO = {
    0: ("Céu limpo", "sol"), 1: ("Quase limpo", "sol"), 2: ("Parcialmente nublado", "nuvem-sol"), 3: ("Nublado", "nuvem"),
    45: ("Neblina", "neblina"), 48: ("Neblina", "neblina"),
    51: ("Garoa fraca", "chuva"), 53: ("Garoa", "chuva"), 55: ("Garoa forte", "chuva"),
    56: ("Garoa gelada", "chuva"), 57: ("Garoa gelada", "chuva"),
    61: ("Chuva fraca", "chuva"), 63: ("Chuva", "chuva"), 65: ("Chuva forte", "chuva"),
    66: ("Chuva gelada", "chuva"), 67: ("Chuva gelada", "chuva"),
    71: ("Neve fraca", "neve"), 73: ("Neve", "neve"), 75: ("Neve forte", "neve"), 77: ("Granizo fino", "neve"),
    80: ("Pancadas de chuva", "chuva"), 81: ("Pancadas de chuva", "chuva"), 82: ("Pancadas fortes", "chuva"),
    85: ("Pancadas de neve", "neve"), 86: ("Pancadas de neve", "neve"),
    95: ("Tempestade", "tempestade"), 96: ("Tempestade com granizo", "tempestade"), 99: ("Tempestade com granizo", "tempestade"),
}


def descrever(codigo, dia: bool = True) -> tuple[str, str]:
    """(resumo, icone) para o codigo WMO; desconhecido vira 'Tempo indefinido'."""
    texto, icone = WMO.get(codigo if isinstance(codigo, int) and not isinstance(codigo, bool) else -1, ("Tempo indefinido", "nuvem"))
    if not dia:
        icone = {"sol": "lua", "nuvem-sol": "nuvem-lua"}.get(icone, icone)
    return texto, icone


def coordenadas(cfg: dict) -> tuple[float, float] | None:
    """(lat, lon) validas do config, ou None (clima desligado ou mal configurado)."""
    try:
        lat, lon = float(cfg["lat"]), float(cfg["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    return (round(lat, 2), round(lon, 2)) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _http(lat: float, lon: float) -> dict:
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code,is_day",
                                "timezone": "auto"})
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "jarvis-voz-painel", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 (URL fixa, https)
        return json.loads(r.read(200_000))


def resumir(dados: dict, cidade: str = "") -> dict:
    atual = dados.get("current") if isinstance(dados, dict) else None
    temp = atual.get("temperature_2m") if isinstance(atual, dict) else None
    if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not -60 <= temp <= 60:
        return {"ok": False, "motivo": "O serviço de clima não respondeu com a temperatura."}
    texto, icone = descrever(atual.get("weather_code"), bool(atual.get("is_day", 1)))
    return {"ok": True, "cidade": cidade[:40], "temp": round(temp), "condicao": texto, "icone": icone}


class Clima:
    """Busca com cache: o painel pode perguntar a vontade, a rede so e usada uma vez por `ttl`."""

    def __init__(self, http: Callable[[float, float], dict] = _http, relogio: Callable[[], float] = time.time,
                 ttl: float = TTL_PADRAO) -> None:
        self._http, self._rel, self.ttl = http, relogio, ttl
        self._trava = threading.Lock()
        self._ate = 0.0
        self._chave: tuple | None = None   # (lat, lon, cidade) do dado guardado: trocar de cidade invalida o cache
        self._ultimo: dict | None = None
        self._quando = 0.0
        self._erro: dict | None = None

    def obter(self, cfg: dict) -> dict:
        coord = coordenadas(cfg)
        if coord is None:
            return {"ok": False, "desligado": True, "motivo": "Informe lat e lon da cidade em painel.clima."}
        cidade = str(cfg.get("cidade") or "")
        chave = (*coord, cidade)
        with self._trava:
            agora = self._rel()
            if chave != self._chave:
                self._chave, self._ultimo, self._erro, self._ate = chave, None, None, 0.0
            if agora >= self._ate:
                try:
                    novo = resumir(self._http(*coord), cidade)
                    if novo["ok"]:
                        self._ultimo, self._quando, self._erro, self._ate = novo, agora, None, agora + self.ttl
                    else:
                        self._erro, self._ate = novo, agora + TTL_ERRO
                except urllib.error.HTTPError as e:
                    self._erro, self._ate = {"ok": False, "motivo": f"Serviço de clima indisponível (HTTP {e.code})."}, agora + TTL_ERRO
                except (OSError, ValueError):
                    self._erro, self._ate = {"ok": False, "motivo": "Sem conexão para ver o clima."}, agora + TTL_ERRO
            if self._ultimo and self._erro is None:
                return {**self._ultimo, "atualizado": int(self._quando)}
            if self._ultimo and agora - self._quando < VELHO_MAX:
                return {**self._ultimo, "atualizado": int(self._quando), "velho": True}
            return dict(self._erro or {"ok": False, "motivo": "Clima indisponível."})


_clima = Clima()


def obter(cfg: dict) -> dict:
    return _clima.obter(cfg)
