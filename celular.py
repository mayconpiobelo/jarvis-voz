"""Jarvis no celular: um app web instalavel (PWA) servido pelo proprio Jarvis, desligado por padrao.

Servidor HTTP proprio (porta 8767), separado do servidor local do painel (8765, que continua so em 127.0.0.1). Serve a
pagina `celular.html` e uma API pequena (conversa por voz ou texto, voz de resposta, tarefas). Defesas:

  1. escuta so em loopback ou na rede do Tailscale (100.64.0.0/10), nunca em 0.0.0.0 nem na rede local;
  2. a API exige `Authorization: Bearer <token>` (tempo constante); erros repetidos travam o IP por um tempo;
  3. quem conversa (`perguntar`, do jarvis.py) roda o Claude em modo SOMENTE CONSULTA: sem Bash, sem gravar arquivos,
     sem e-mail/mensagens; as tarefas so podem ser vistas, criadas e concluidas.

A pagina e os icones nao exigem token (nao contem nada seu); tudo o que mexe em dados exige.

Este modulo nao importa o jarvis.py: recebe `Ganchos` prontos, para ser testavel sozinho.
"""
from __future__ import annotations

import hmac
import io
import ipaddress
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

log = logging.getLogger("jarvis")

PORTA_PADRAO = 8767
TOKEN_MIN = 24                 # caracteres; `gerar_token()` faz 43
MAX_JSON = 4096                # bytes de um pedido JSON
MAX_AUDIO = 6_000_000          # bytes de uma gravacao (cerca de 1 min em AAC)
MAX_TEXTO = 500                # caracteres do que foi falado ou digitado
ERROS_ANTES_DE_TRAVAR = 5
TRAVA_SEGUNDOS = 300.0

_TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
PAGINA = Path(__file__).resolve().parent / "celular.html"

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; "
       "media-src 'self' blob: data:; connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")


class Ocupado(Exception):
    """Um gancho levanta isto quando o uso local tem prioridade (o servidor responde 429 com a mensagem)."""


@dataclass
class Ganchos:
    """O que o servidor precisa do Jarvis; cada um e uma funcao simples, trocavel nos testes."""
    transcrever: Callable[[bytes], str]                    # audio gravado -> texto
    perguntar: Callable[[str], str]                        # texto -> resposta (curta, ja limpa para fala)
    falar: Callable[[str], bytes | None]                   # texto -> WAV; None = sem voz neural (a pagina usa a do iPhone)
    tarefas: Callable[[], dict]                            # {"abertas": [...], "concluidas": [...]}
    tarefa_adicionar: Callable[[str, str | None], dict]    # (texto, quando|None) -> {"ok", "mensagem", "pergunta"}
    tarefa_concluir: Callable[[int], bool]


def host_permitido(host: str) -> bool:
    """True so para loopback e para enderecos do Tailscale. 0.0.0.0, '' e a rede local (HTTP puro) ficam de fora."""
    try:
        ip = ipaddress.ip_address(str(host).strip())
    except ValueError:
        return False
    if ip.is_unspecified:
        return False
    return ip.is_loopback or ip in _TAILSCALE_V4 or ip in _TAILSCALE_V6


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def garantir_token(arquivo: Path) -> str:
    """Devolve o `celular.token` do config; se nao houver, gera um e grava (o config.json fica fora do git)."""
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    cel = dados.setdefault("celular", {})
    token = str(cel.get("token") or "").strip()
    if len(token) >= TOKEN_MIN:
        return token
    token = gerar_token()
    cel["token"] = token
    cel.setdefault("enabled", False)
    cel.setdefault("host", "127.0.0.1")
    cel.setdefault("port", PORTA_PADRAO)
    arquivo.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return token


def token_confere(cabecalho: str, token: str) -> bool:
    """`Authorization: Bearer xxx` contra o token do config, em tempo constante."""
    if len(token) < TOKEN_MIN:
        return False  # sem token configurado nada passa
    partes = (cabecalho or "").split(None, 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return False
    return hmac.compare_digest(partes[1].strip().encode("utf-8"), token.encode("utf-8"))


class LimiteDeErros:
    """Conta erros de autenticacao por IP; passado o limite, recusa tudo desse IP por TRAVA_SEGUNDOS."""

    def __init__(self, maximo: int = ERROS_ANTES_DE_TRAVAR, segundos: float = TRAVA_SEGUNDOS, relogio=time.monotonic):
        self.maximo, self.segundos, self.relogio = maximo, segundos, relogio
        self._erros: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def travado(self, ip: str) -> bool:
        with self._lock:
            return self._recentes(ip) >= self.maximo

    def errou(self, ip: str) -> None:
        with self._lock:
            self._recentes(ip)
            self._erros.setdefault(ip, []).append(self.relogio())

    def acertou(self, ip: str) -> None:
        with self._lock:
            self._erros.pop(ip, None)

    def _recentes(self, ip: str) -> int:
        agora = self.relogio()
        lista = [t for t in self._erros.get(ip, []) if agora - t < self.segundos]
        if lista:
            self._erros[ip] = lista
        else:
            self._erros.pop(ip, None)
        return len(lista)


def icone_png(tamanho: int) -> bytes:
    """Icone do app (esfera ciano-violeta sobre fundo escuro), gerado na hora: nada de binario no repositorio."""
    from PIL import Image, ImageDraw, ImageFilter

    n = max(32, min(int(tamanho), 1024))
    img = Image.new("RGB", (n, n), (7, 11, 22))
    brilho = Image.new("RGB", (n, n), (7, 11, 22))
    d = ImageDraw.Draw(brilho)
    c, r = n / 2, n * 0.30
    d.ellipse((c - r, c - r, c + r, c + r), fill=(60, 200, 255))
    d.ellipse((c - r * 0.55, c - r * 0.55 + r * 0.25, c + r * 0.95, c + r * 0.95), fill=(150, 100, 255))
    brilho = brilho.filter(ImageFilter.GaussianBlur(n * 0.045))
    img.paste(brilho)
    d = ImageDraw.Draw(img)
    r2 = n * 0.085
    d.ellipse((c - r2, c - r2, c + r2, c + r2), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


MANIFEST = json.dumps({
    "name": "Jarvis", "short_name": "Jarvis", "start_url": "/", "scope": "/", "display": "standalone",
    "orientation": "portrait", "background_color": "#070b16", "theme_color": "#070b16", "lang": "pt-BR",
    "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
}).encode("utf-8")


def criar_servidor(host: str, porta: int, token: str, g: Ganchos) -> ThreadingHTTPServer:
    """Monta (sem iniciar) o servidor. Levanta ValueError se o host nao for permitido ou o token for curto."""
    if not host_permitido(host):
        raise ValueError(f"celular.host {host!r} nao permitido: use 127.0.0.1 ou o IP do Tailscale (100.x.y.z)")
    if len(token) < TOKEN_MIN:
        raise ValueError(f"celular.token precisa ter pelo menos {TOKEN_MIN} caracteres")

    limite = LimiteDeErros()
    vagas = {"perguntar": threading.BoundedSemaphore(2), "transcrever": threading.BoundedSemaphore(1),
             "falar": threading.BoundedSemaphore(1)}
    icones: dict[int, bytes] = {}

    class H(BaseHTTPRequestHandler):
        timeout = 15  # leitura do pedido (o Claude pode demorar mais; so a leitura tem prazo)

        # ---- respostas
        def _enviar(self, codigo: int, corpo: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(corpo)

        def _json(self, codigo: int, ok: bool, **campos) -> None:
            corpo = json.dumps({"ok": ok, **campos}, ensure_ascii=False).encode("utf-8")
            self._enviar(codigo, corpo, "application/json; charset=utf-8")

        def _erro(self, codigo: int, texto: str, **campos) -> None:
            self._json(codigo, False, texto=texto, **campos)

        # ---- entrada
        def _autorizado(self) -> bool:
            ip = self.client_address[0]
            if limite.travado(ip):
                self._erro(429, "Muitas tentativas. Aguarde alguns minutos.")
                return False
            if not token_confere(self.headers.get("Authorization", ""), token):
                limite.errou(ip)
                log.warning("celular: acesso negado (%s)", ip)
                self._erro(401, "Acesso negado.")
                return False
            limite.acertou(ip)
            return True

        def _corpo(self, maximo: int) -> bytes | None:
            """Corpo do pedido, ou None (e a resposta de erro ja enviada)."""
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n <= 0 or n > maximo:
                self._erro(413, "Pedido vazio ou grande demais.")
                return None
            try:
                return self.rfile.read(n)
            except OSError:
                self._erro(400, "Nao consegui ler o pedido.")
                return None

        def _json_corpo(self) -> dict | None:
            if "application/json" not in self.headers.get("Content-Type", ""):
                self._erro(415, "O pedido precisa ser JSON.")
                return None
            bruto = self._corpo(MAX_JSON)
            if bruto is None:
                return None
            try:
                dados = json.loads(bruto.decode("utf-8-sig", errors="replace"))
            except ValueError:
                dados = None
            if not isinstance(dados, dict):
                self._erro(400, "Nao entendi o pedido.")
                return None
            return dados

        def _texto(self, dados: dict) -> str | None:
            t = str(dados.get("texto", "")).strip()
            if not t:
                self._erro(400, "Nao ouvi nada, senhor.")
                return None
            return t[:MAX_TEXTO]

        def _com_vaga(self, nome: str, fazer: Callable[[], None]) -> None:
            if not vagas[nome].acquire(blocking=False):
                return self._erro(429, "Ocupado com outro pedido, senhor.")
            try:
                fazer()
            except Ocupado as e:  # o PC vem primeiro: avisa e deixa para depois
                self._erro(429, str(e) or "O Jarvis esta ocupado no computador, senhor.")
            except Exception:
                log.exception("erro no celular (%s)", nome)
                self._erro(500, "Tive um problema para responder, senhor.")
            finally:
                vagas[nome].release()

        # ---- rotas
        def do_GET(self) -> None:  # noqa: N802
            caminho = self.path.split("?")[0]
            if caminho in ("/", "/index.html"):  # a pagina nao tem segredo: o token fica no aparelho
                try:
                    corpo = PAGINA.read_bytes()
                except OSError:
                    return self._erro(404, "celular.html ausente.")
                return self._enviar(200, corpo, "text/html; charset=utf-8",
                                    {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY"})
            if caminho == "/manifest.webmanifest":
                return self._enviar(200, MANIFEST, "application/manifest+json")
            tam = {"/icon-180.png": 180, "/icon-192.png": 192, "/icon-512.png": 512}.get(caminho)
            if tam:
                if tam not in icones:
                    try:
                        icones[tam] = icone_png(tam)
                    except Exception:
                        log.exception("nao consegui gerar o icone")
                        return self._erro(500, "Sem icone.")
                return self._enviar(200, icones[tam], "image/png", {"Cache-Control": "public, max-age=86400"})
            if not caminho.startswith("/api/"):
                return self._erro(404, "Nao encontrado.")
            if not self._autorizado():
                return
            if caminho == "/api/ping":
                return self._json(200, True, texto="Jarvis ao seu dispor, senhor.")
            if caminho == "/api/tarefas":
                return self._json(200, True, **g.tarefas())
            self._erro(404, "Nao encontrado.")

        def do_POST(self) -> None:  # noqa: N802
            caminho = self.path.split("?")[0]
            if not caminho.startswith("/api/"):
                return self._erro(404, "Nao encontrado.")
            if not self._autorizado():
                return

            if caminho == "/api/transcrever":
                if not self.headers.get("Content-Type", "").startswith(("audio/", "video/", "application/octet-stream")):
                    return self._erro(415, "Envie o audio gravado.")
                dados = self._corpo(MAX_AUDIO)
                if dados is None:
                    return
                return self._com_vaga("transcrever", lambda: self._json(200, True, texto=g.transcrever(dados)))

            if caminho == "/api/perguntar":
                corpo = self._json_corpo()
                texto = None if corpo is None else self._texto(corpo)
                if texto is None:
                    return
                return self._com_vaga("perguntar", lambda: self._json(200, True, texto=g.perguntar(texto)))

            if caminho == "/api/falar":
                corpo = self._json_corpo()
                texto = None if corpo is None else self._texto(corpo)
                if texto is None:
                    return

                def falar() -> None:
                    wav = g.falar(texto)
                    if wav is None:
                        return self._json(200, False, texto="Sem voz neural configurada.", sem_voz=True)
                    self._enviar(200, wav, "audio/wav")

                return self._com_vaga("falar", falar)

            if caminho == "/api/tarefas/adicionar":
                corpo = self._json_corpo()
                if corpo is None:
                    return
                texto = str(corpo.get("texto", "")).strip()[:300]
                if not texto:
                    return self._erro(400, "Qual e a tarefa, senhor?")
                quando = corpo.get("quando")
                quando = None if quando is None else str(quando)[:40]
                return self._json(200, True, **g.tarefa_adicionar(texto, quando))

            if caminho == "/api/tarefas/concluir":
                corpo = self._json_corpo()
                if corpo is None:
                    return
                try:
                    ok = g.tarefa_concluir(int(corpo.get("id")))
                except (TypeError, ValueError):
                    ok = False
                return self._json(200 if ok else 404, ok)

            self._erro(404, "Nao encontrado.")

        def log_message(self, *a) -> None:  # silencia o log do http.server
            pass

    class Servidor(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):  # cliente que cai no meio nao e erro
            import sys

            if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError)):
                return
            log.exception("erro no servidor do celular")

    return Servidor((host, int(porta)), H)


def iniciar(cfg: dict, g: Ganchos) -> ThreadingHTTPServer | None:
    """Liga o servidor se `celular.enabled`. Nunca derruba o Jarvis: qualquer problema vira aviso no log."""
    cel = cfg.get("celular") or {}
    if not cel.get("enabled", False):
        return None
    try:
        srv = criar_servidor(str(cel.get("host", "127.0.0.1")), int(cel.get("port", PORTA_PADRAO)),
                             str(cel.get("token") or ""), g)
    except (ValueError, OSError) as e:
        log.warning("celular desligado: %s", e)
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("celular em http://%s:%s (conversa somente-consulta + tarefas)", *srv.server_address[:2])
    return srv
