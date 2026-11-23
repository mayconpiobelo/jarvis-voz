"""Hora e data por voz, na hora: sem chamar o Claude (que levaria alguns segundos para dizer o que o relogio ja sabe)."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]

_HORA = re.compile(r"^(?:jarvis\s+)?(?:por\s+favor\s+)?(?:(?:me\s+)?(?:diga|diz|fala|fale|informe)\s+)?"
                   r"(?:que\s+horas?\s+(?:sao|e|eh)(?:\s+agora)?|(?:qual\s+(?:e\s+)?)?(?:a\s+)?hora\s+(?:certa|agora|atual)|"
                   r"(?:as\s+)?horas(?:\s+agora)?)$")
_DATA = re.compile(r"^(?:jarvis\s+)?(?:por\s+favor\s+)?(?:(?:me\s+)?(?:diga|diz|fala|fale|informe)\s+)?"
                   r"(?:que\s+dia\s+(?:e|eh|da\s+semana\s+e|do\s+mes\s+e)(?:\s+hoje)?|(?:qual\s+(?:e\s+)?)?(?:a\s+)?data(?:\s+de\s+hoje|\s+atual)?|"
                   r"em\s+que\s+dia\s+(?:estamos|nos\s+estamos)|que\s+data\s+(?:e|eh)\s+hoje|hoje\s+e\s+que\s+dia)$")


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def fala_hora(agora: datetime) -> str:
    h, m = agora.hour, agora.minute
    if h == 0:
        return "É meia-noite em ponto, senhor." if m == 0 else f"É meia-noite e {m} {'minuto' if m == 1 else 'minutos'}, senhor."
    horas = "uma hora" if h == 1 else f"{h} horas"
    verbo = "É" if h == 1 else "São"
    if m == 0:
        return f"{verbo} {horas} em ponto, senhor."
    return f"{verbo} {horas} e {m} {'minuto' if m == 1 else 'minutos'}, senhor."


def fala_data(agora: datetime) -> str:
    return f"Hoje é {DIAS[agora.weekday()]}, {agora.day} de {MESES[agora.month - 1]} de {agora.year}, senhor."


def responder(texto: str, agora: datetime | None = None) -> str | None:
    """Fala da hora/data se for exatamente essa pergunta; None segue para o resto."""
    t = _norm(texto)
    if not t or len(t) > 60:
        return None
    agora = agora or datetime.now()
    if _HORA.match(t):
        return fala_hora(agora)
    if _DATA.match(t):
        return fala_data(agora)
    return None
