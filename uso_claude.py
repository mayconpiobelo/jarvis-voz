"""Consumo do plano do Claude Code para o painel: sessao de 5 h, semana e de onde veio o gasto.

Fonte: o mesmo endpoint que o proprio Claude Code consulta no `/usage` (api.anthropic.com/api/oauth/usage), lido com o
login que o Claude Code ja guardou em `~/.claude/.credentials.json`. Pontos de seguranca:
- o token so existe aqui dentro: nunca vai para o navegador, para o log nem para o historico; so o resumo sai;
- o Jarvis NAO renova o login (renovar gira o refresh token e poderia deslogar o Claude Code): se o token vencer, o painel
  avisa e volta sozinho quando o Claude Code renovar (o que acontece sempre que ele e usado);
- o endpoint nao e documentado: qualquer mudanca vira "indisponivel", nunca um erro no painel;
- consulta no maximo a cada `ttl` segundos (padrao 120), qualquer que seja o numero de paineis abertos.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

URL = "https://api.anthropic.com/api/oauth/usage"
TTL_PADRAO = 120          # segundos entre consultas
TTL_ERRO = 45             # depois de uma falha, tenta de novo mais cedo
VELHO_MAX = 30 * 60       # um dado bom serve de reserva (marcado como "velho") por ate 30 min

NOMES = {"session": "Sessão · 5 h", "weekly_all": "Semana", "weekly_sonnet": "Semana · Sonnet",
         "weekly_opus": "Semana · Opus"}
ORIGENS = {"Other": "Outros"}
PLANOS = {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise", "free": "Free"}


class SemCredencial(Exception):
    """Sem login do Claude Code, ou o token vencido; a mensagem ja serve para o usuario."""


def caminho_credencial() -> Path:
    raiz = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(raiz) if raiz else Path.home() / ".claude") / ".credentials.json"


def ler_credencial(agora: float | None = None, caminho: Path | None = None) -> tuple[str, str]:
    """(token, plano). Relido a cada consulta: o Claude Code troca o arquivo quando renova o login."""
    agora = time.time() if agora is None else agora
    try:
        bruto = json.loads((caminho or caminho_credencial()).read_text(encoding="utf-8"))
        oauth = bruto["claudeAiOauth"]
        token = oauth["accessToken"]
    except (OSError, ValueError, KeyError, TypeError):
        raise SemCredencial("Sem login do Claude Code neste computador.") from None
    if not isinstance(token, str) or not token:
        raise SemCredencial("Sem login do Claude Code neste computador.")
    expira = oauth.get("expiresAt")
    if isinstance(expira, (int, float)) and expira / 1000 < agora + 30:
        raise SemCredencial("Login do Claude Code vencido. Use o Claude Code (ou fale com o Jarvis) para renová-lo.")
    plano = str(oauth.get("subscriptionType") or "")
    return token, PLANOS.get(plano.lower(), plano.capitalize())


def _http(token: str) -> dict:
    req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20",
                                               "User-Agent": "jarvis-voz-painel", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 (URL fixa, https)
        return json.loads(r.read(1_000_000))


def _pct(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return max(0, min(100, round(v)))


def _reset(v) -> int | None:
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


def nivel(pct: int) -> str:
    return "critico" if pct >= 90 else "atencao" if pct >= 70 else "normal"


def resumir(dados: dict, plano: str = "") -> dict:
    """Resposta do endpoint -> o que o painel precisa (so numeros e rotulos, nada do login)."""
    limites: list[dict] = []
    vistos: set[str] = set()

    def juntar(id_: str, pct, reset) -> None:
        p = _pct(pct)
        if p is None or id_ in vistos:
            return
        vistos.add(id_)
        nome = NOMES.get(id_) or id_.replace("_", " ").capitalize()
        limites.append({"id": id_, "nome": nome, "pct": p, "nivel": nivel(p), "reinicia": _reset(reset)})

    lista = dados.get("limits")
    if isinstance(lista, list):
        for it in lista:
            if isinstance(it, dict) and isinstance(it.get("kind"), str):
                juntar(it["kind"][:40], it.get("percent"), it.get("resets_at"))
    for chave, id_ in (("five_hour", "session"), ("seven_day", "weekly_all"),
                       ("seven_day_sonnet", "weekly_sonnet"), ("seven_day_opus", "weekly_opus")):
        bloco = dados.get(chave)
        if isinstance(bloco, dict):
            juntar(id_, bloco.get("utilization"), bloco.get("resets_at"))
    ordem = {"session": 0, "weekly_all": 1}
    limites.sort(key=lambda x: ordem.get(x["id"], 9))

    origens: list[dict] = []
    quebra = dados.get("seven_day_breakdown")
    for r in (quebra.get("rows") if isinstance(quebra, dict) and isinstance(quebra.get("rows"), list) else []):
        if not isinstance(r, dict):
            continue
        p = _pct(r.get("percent_of_limit"))
        nome = r.get("display_name")
        if p and isinstance(nome, str):
            origens.append({"nome": ORIGENS.get(nome, nome)[:30], "pct": p})
    origens.sort(key=lambda x: -x["pct"])

    if not limites:
        return {"ok": False, "motivo": "O Claude não informou o consumo agora."}
    return {"ok": True, "plano": plano, "limites": limites[:5], "origens": origens[:6]}


class Consumo:
    """Busca com cache: varios paineis ou consultas seguidas viram uma chamada so a cada `ttl` segundos."""

    def __init__(self, credencial: Callable[[], tuple[str, str]] = ler_credencial,
                 http: Callable[[str], dict] = _http, relogio: Callable[[], float] = time.time,
                 ttl: float = TTL_PADRAO) -> None:
        self._cred, self._http, self._rel, self.ttl = credencial, http, relogio, ttl
        self._trava = threading.Lock()
        self._ate = 0.0          # nao consulta de novo antes disso
        self._ultimo: dict | None = None   # ultimo resultado bom
        self._quando = 0.0
        self._erro: dict | None = None

    def obter(self) -> dict:
        with self._trava:
            agora = self._rel()
            if agora < self._ate:
                return self._saida(agora)
            try:
                token, plano = self._cred()
                novo = resumir(self._http(token), plano)
                if novo.get("ok"):
                    self._ultimo, self._quando, self._erro, self._ate = novo, agora, None, agora + self.ttl
                else:                      # resposta sem numeros: mantem o ultimo dado bom como reserva
                    self._erro, self._ate = novo, agora + TTL_ERRO
            except SemCredencial as e:
                self._erro, self._ate = {"ok": False, "motivo": str(e)}, agora + 10   # relê logo: o Claude Code pode ter renovado
            except urllib.error.HTTPError as e:
                msg = ("Muitas consultas seguidas; tento de novo já." if e.code == 429 else
                       "O Claude recusou o login atual." if e.code in (401, 403) else
                       f"Serviço de consumo indisponível (HTTP {e.code}).")
                self._erro, self._ate = {"ok": False, "motivo": msg}, agora + TTL_ERRO
            except (OSError, ValueError):
                self._erro, self._ate = {"ok": False, "motivo": "Sem conexão com o Claude."}, agora + TTL_ERRO
            return self._saida(agora)

    def _saida(self, agora: float) -> dict:
        if self._erro is None and self._ultimo and self._ultimo.get("ok"):
            return {**self._ultimo, "atualizado": int(self._quando)}
        if self._ultimo and self._ultimo.get("ok") and agora - self._quando < VELHO_MAX:
            return {**self._ultimo, "atualizado": int(self._quando), "velho": True, "motivo": (self._erro or {}).get("motivo", "")}
        return dict(self._erro or {"ok": False, "motivo": "Consumo indisponível."})


_consumo = Consumo()


def obter() -> dict:
    return _consumo.obter()
