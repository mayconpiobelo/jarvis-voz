"""Musica: le e controla o que esta tocando (Spotify e outros players) pelo controle de midia do Windows.

Sem login, sem chave de API e sem rede: usa o mesmo mecanismo dos botoes de midia do sistema (SMTC).
Funciona com o Spotify instalado (inclusive o da Microsoft Store); se houver outro player, usa o que
estiver ativo quando o Spotify nao estiver aberto.

Modulos opcionais (requirements.txt): winrt-Windows.Media.Control e winrt-Windows.Storage.Streams.
Sem eles, o painel mostra "indisponivel" e nada mais quebra.
"""
from __future__ import annotations

import asyncio
import io
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Protocol

ACOES = {"play_pause", "proxima", "anterior"}
_ESTADOS = {4: "tocando", 5: "pausado", 3: "parado", 2: "carregando", 1: "aberto", 0: "fechado"}


class Backend(Protocol):
    def snapshot(self, preferir: str) -> dict | None: ...
    def capa(self, preferir: str) -> bytes | None: ...
    def acao(self, acao: str, preferir: str) -> bool: ...


# ------------------------------------------------------------------ backend real (WinRT)
class WinrtBackend:
    """Fala com o Windows (SMTC). Cada chamada abre e fecha o seu proprio loop: simples e a prova de thread."""

    def __init__(self) -> None:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M  # noqa: F401

    @staticmethod
    async def _sessao(preferir: str):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

        mgr = await M.request_async()
        if preferir:
            for s in mgr.get_sessions():
                if preferir.lower() in (s.source_app_user_model_id or "").lower():
                    return s
        return mgr.get_current_session()

    @staticmethod
    def _nome_app(aumid: str) -> str:
        a = (aumid or "").lower()
        if "spotify" in a:
            return "Spotify"
        return re.split(r"[!_.]", aumid or "")[-1].replace(".exe", "").title() or "Player"

    def snapshot(self, preferir: str) -> dict | None:
        async def _run():
            s = await self._sessao(preferir)
            if s is None:
                return None
            props = await s.try_get_media_properties_async()
            info, tl = s.get_playback_info(), s.get_timeline_properties()
            c = info.controls
            estado = int(info.playback_status)
            dur = max(0.0, (tl.end_time - tl.start_time).total_seconds())
            pos = max(0.0, tl.position.total_seconds())
            if estado == 4 and tl.last_updated_time:  # tocando: o Windows so atualiza a posicao de vez em quando
                pos += max(0.0, (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds())
            return {
                "app": self._nome_app(s.source_app_user_model_id), "titulo": props.title or "", "artista": props.artist or "",
                "album": props.album_title or "", "estado": _ESTADOS.get(estado, "parado"),
                "posicao_s": min(pos, dur) if dur else pos, "duracao_s": dur, "tem_capa": props.thumbnail is not None,
                "pode": {"anterior": bool(c.is_previous_enabled), "proxima": bool(c.is_next_enabled),
                         "play_pause": bool(c.is_play_enabled or c.is_pause_enabled)},
            }

        return asyncio.run(_run())

    def capa(self, preferir: str) -> bytes | None:
        async def _run():
            from winrt.windows.storage.streams import DataReader

            s = await self._sessao(preferir)
            if s is None:
                return None
            props = await s.try_get_media_properties_async()
            if props.thumbnail is None:
                return None
            stream = await props.thumbnail.open_read_async()
            n = int(stream.size)
            if not 0 < n < 8_000_000:
                return None
            leitor = DataReader(stream.get_input_stream_at(0))
            await leitor.load_async(n)
            dados = bytearray(n)
            leitor.read_bytes(dados)
            return bytes(dados)

        return asyncio.run(_run())

    def acao(self, acao: str, preferir: str) -> bool:
        async def _run():
            s = await self._sessao(preferir)
            if s is None:
                return False
            if acao == "play_pause":
                return bool(await s.try_toggle_play_pause_async())
            if acao == "proxima":
                return bool(await s.try_skip_next_async())
            return bool(await s.try_skip_previous_async())

        return asyncio.run(_run())


# ------------------------------------------------------------------ cache e API publica
_lock = threading.Lock()
_backend: Backend | None = None
_indisponivel: str | None = None
_cache: dict[str, Any] = {"t": 0.0, "snap": None, "capa_chave": None, "capa": None, "cor": "#1db954"}


def _obter_backend() -> Backend | None:
    global _backend, _indisponivel
    if _backend is None and _indisponivel is None:
        try:
            _backend = WinrtBackend()
        except Exception as e:  # pacote ausente ou Windows sem SMTC
            _indisponivel = f"{type(e).__name__}: {e}"
    return _backend


def definir_backend(b: Backend | None) -> None:
    """Para testes: injeta um backend falso (e limpa o cache)."""
    global _backend, _indisponivel
    _backend, _indisponivel = b, None
    _cache.update(t=0.0, snap=None, capa_chave=None, capa=None)


def cor_dominante(img_bytes: bytes) -> str:
    """Cor media, com mais peso para tons saturados (a cor 'da capa'), em #rrggbb."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(img_bytes)).convert("RGB").resize((24, 24))
        r = g = b = pesos = 0.0
        pixels = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
        for pr, pg, pb in pixels:
            mx, mn = max(pr, pg, pb), min(pr, pg, pb)
            sat = (mx - mn) / mx if mx else 0.0
            w = 0.15 + sat * (0.4 + 0.6 * mx / 255)
            r, g, b, pesos = r + pr * w, g + pg * w, b + pb * w, pesos + w
        return "#{:02x}{:02x}{:02x}".format(int(r / pesos), int(g / pesos), int(b / pesos))
    except Exception:
        return "#1db954"


def snapshot(preferir: str = "Spotify", validade: float = 0.8) -> dict:
    """Estado atual da musica, pronto para o painel. Nunca levanta excecao."""
    b = _obter_backend()
    if b is None:
        return {"disponivel": False, "ativo": False, "motivo": _indisponivel or "sem backend"}
    with _lock:
        agora = time.monotonic()
        if _cache["snap"] is not None and agora - _cache["t"] < validade:
            return dict(_cache["snap"])
        try:
            s = b.snapshot(preferir)
        except Exception as e:
            return {"disponivel": True, "ativo": False, "motivo": f"erro: {type(e).__name__}"}
        if not s or not (s["titulo"] or s["artista"]):
            res = {"disponivel": True, "ativo": False, "app": (s or {}).get("app", ""), "motivo": "nada carregado"}
        else:
            chave = f"{s['app']}|{s['titulo']}|{s['artista']}|{s['album']}"
            if chave != _cache["capa_chave"]:
                dados = None
                if s.get("tem_capa"):
                    try:
                        dados = b.capa(preferir)
                    except Exception:
                        dados = None
                _cache.update(capa_chave=chave, capa=dados, cor=cor_dominante(dados) if dados else "#1db954")
            res = {"disponivel": True, "ativo": True, **{k: s[k] for k in ("app", "titulo", "artista", "album", "estado",
                                                                              "posicao_s", "duracao_s", "pode")},
                   "capa": bool(_cache["capa"]), "capa_id": str(abs(hash(chave)) % 10**9), "cor": _cache["cor"]}
        _cache.update(t=agora, snap=res)
        return dict(res)


def capa_bytes() -> tuple[bytes, str] | None:
    dados = _cache.get("capa")
    if not dados:
        return None
    mime = "image/png" if dados[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return dados, mime


def acao(nome: str, preferir: str = "Spotify") -> dict:
    """play_pause | proxima | anterior. So aceita esses nomes."""
    if nome not in ACOES:
        return {"ok": False, "erro": "acao desconhecida"}
    b = _obter_backend()
    if b is None:
        return {"ok": False, "erro": "midia indisponivel"}
    try:
        ok = bool(b.acao(nome, preferir))
    except Exception as e:
        return {"ok": False, "erro": type(e).__name__}
    with _lock:
        _cache["t"] = 0.0  # o proximo snapshot ja reflete a mudanca
    return {"ok": ok}


# ------------------------------------------------------------------ comandos de voz (resposta imediata)
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


_ALVO = r"(?:a |o |essa |esta |essa aqui )?(?:musica|faixa|som|spotify|player|musica atual)"
_PAUSA = re.compile(rf"^(?:jarvis )?(?:por favor )?(?:pausa|pause|pausar|para|pare|parar|silencia|silencie) {_ALVO}$")
_RETOMA = re.compile(rf"^(?:jarvis )?(?:por favor )?(?:(?:continua|continue|continuar|retoma|retome|retomar|toca|toque|tocar|da play|de play|play) {_ALVO}|da play|de play|play|despausa|despause)$")
_PROXIMA = re.compile(rf"^(?:jarvis )?(?:por favor )?(?:proxima(?: musica| faixa)?|(?:pula|pule|pular|avanca|avance|avancar|passa|passe|toca|toque|tocar) (?:a )?(?:proxima(?: musica| faixa)?|{_ALVO}))$")
_ANTERIOR = re.compile(rf"^(?:jarvis )?(?:por favor )?(?:(?:musica|faixa) anterior|anterior|(?:volta|volte|voltar|toca|toque|tocar) (?:a )?(?:anterior|{_ALVO} anterior)|(?:volta|volte|voltar) (?:uma |1 )(?:musica|faixa))$")
_QUAL = re.compile(r"^(?:jarvis )?(?:o que|que musica|qual musica|qual a musica|que som|qual o som)(?: (?:esta|e|ta|tem|estou))? (?:tocando|essa|ouvindo)(?: agora)?$")


def responder(texto: str) -> str | None:
    """Se a frase for um comando simples de musica, executa e devolve a fala; senao None (segue para o Claude).
    So aceita frases curtas e exatas: 'toca uma musica do Queen' NAO e tratado aqui."""
    t = _norm(texto)
    if not t or len(t.split()) > 6:
        return None
    if _QUAL.match(t):
        s = snapshot()
        if not s.get("disponivel"):
            return "O controle de música não está disponível, senhor."
        if not s.get("ativo"):
            return "Não há nada tocando no momento, senhor."
        verbo = "Está tocando" if s["estado"] == "tocando" else "Está pausada"
        return f"{verbo}, senhor: {s['titulo']}" + (f", de {s['artista']}." if s["artista"] else ".")
    for rx, nome, fala in ((_PAUSA, "play_pause", "Pausado, senhor."), (_RETOMA, "play_pause", "Retomando, senhor."),
                           (_PROXIMA, "proxima", "Próxima faixa, senhor."), (_ANTERIOR, "anterior", "Faixa anterior, senhor.")):
        if rx.match(t):
            s = snapshot()
            if not s.get("disponivel") or not s.get("ativo"):
                return "Não encontrei nenhum player de música ativo, senhor."
            if rx is _PAUSA and s["estado"] != "tocando":
                return "Já está pausado, senhor."
            if rx is _RETOMA and s["estado"] == "tocando":
                return "Já está tocando, senhor."
            return fala if acao(nome).get("ok") else "Não consegui controlar o player, senhor."
    return None
