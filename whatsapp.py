"""Ligacao pelo WhatsApp Desktop (Windows), por voz e SEMPRE com a sua confirmacao.

Como funciona (o WhatsApp Desktop nao deixa o Windows clicar em botoes dentro da janela dele):
  1. "Jarvis, liga para a Maria no WhatsApp"  ->  o Jarvis acha "maria" na lista `whatsapp.contatos` do config.json;
  2. pergunta "Ligar para Maria pelo WhatsApp, senhor. Confirma?" e so segue com o seu "confirma";
  3. abre a conversa pelo numero (whatsapp://send?phone=...), espera o WhatsApp ficar em primeiro plano e envia o
     atalho de ligacao de voz do proprio WhatsApp (Ctrl+Shift+C).
Travas: nunca com jogo/apresentacao em tela cheia; so envia a tecla se a janela em primeiro plano for o WhatsApp
(se nao for, desiste sem ligar); `whatsapp.dry_run: true` faz tudo menos a tecla.

Este modulo e puro (as partes que tocam no Windows entram por parametro) para ser testado sem ligar para ninguem.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Callable

ATALHO_LIGAR_VOZ = (0x11, 0x10, 0x43)  # Ctrl + Shift + C
_FILLER = {"para", "pra", "pro", "a", "o", "as", "os", "no", "na", "nos", "nas", "pelo", "pela", "via", "de", "do", "da",
           "um", "uma", "ao", "com", "whatsapp", "zap", "zapzap", "whats", "voz", "ligacao", "ligacoes", "chamada", "por",
           "favor", "jarvis", "senhor", "ai", "me"}
_VERBO = re.compile(r"^(?:jarvis\s+)?(?:por\s+favor\s+)?(?:liga|ligue|ligar|chama|chame|chamar|telefona|telefone|telefonar|"
                    r"(?:faz|faca|fazer)\s+(?:uma\s+)?(?:ligacao|chamada))\b")
_APP = re.compile(r"\b(?:whatsapp|whats|zap|zapzap)\b")


def norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def interpretar(texto: str) -> str | None:
    """"liga para a Maria no WhatsApp" -> "maria". None se nao for pedido de ligacao pelo WhatsApp.
    Exige citar o WhatsApp/zap (senao pode ser outra ligacao, como pelo Teams) e um nome."""
    n = norm(texto)
    if not n or len(n) > 90 or not _APP.search(n) or not _VERBO.match(n):
        return None
    resto = _VERBO.sub(" ", n, count=1)
    nome = [p for p in resto.split() if p not in _FILLER]
    if not nome or len(nome) > 4:
        return None
    return " ".join(nome)


def normalizar_numero(bruto: str, ddi_padrao: str = "55") -> str | None:
    """"(11) 99999-0000" -> "5511999990000". Aceita com ou sem DDI; None se nao parecer um telefone."""
    d = re.sub(r"\D", "", str(bruto or ""))
    if d.startswith("00"):
        d = d[2:]
    if len(d) in (10, 11):  # so DDD + numero: acrescenta o DDI padrao
        d = re.sub(r"\D", "", ddi_padrao) + d
    return d if 11 <= len(d) <= 15 else None


def resolver(nome: str, contatos: dict) -> list[tuple[str, str]]:
    """Contatos que combinam com o nome falado: [(nome_no_config, numero_bruto)]. Um item = certeza."""
    alvo = norm(nome)
    todos = [(str(k), v) for k, v in (contatos or {}).items() if isinstance(v, (str, int))]
    for k, v in todos:
        if norm(k) == alvo:
            return [(k, str(v))]
    palavras = alvo.split()
    achados = [(k, str(v)) for k, v in todos if all(p in norm(k).split() for p in palavras)]
    if not achados:  # "maria silva" falado, "maria" no config
        achados = [(k, str(v)) for k, v in todos if norm(k) and all(p in palavras for p in norm(k).split())]
    return achados


class Ligador:
    """Executa a ligacao. As funcoes que tocam no Windows entram no construtor (testes usam falsas)."""

    def __init__(self, abrir: Callable[[str], None], janela_ativa: Callable[[], tuple[str, str]],
                 enviar_atalho: Callable[[tuple[int, ...]], None], tela_cheia: Callable[[], bool],
                 esperar: Callable[[float], None] = time.sleep, dry_run: bool = False):
        self.abrir, self.janela_ativa, self.enviar_atalho = abrir, janela_ativa, enviar_atalho
        self.tela_cheia, self.esperar, self.dry_run = tela_cheia, esperar, dry_run

    def _whatsapp_na_frente(self) -> bool:
        proc, titulo = self.janela_ativa()
        return proc.lower().startswith("whatsapp") and titulo.strip().lower() == "whatsapp"

    def ligar(self, numero: str) -> tuple[bool, str]:
        """(ok, frase). Nunca envia a tecla se algo parecer errado."""
        if self.tela_cheia():
            return False, "Há um jogo ou apresentação em tela cheia; não liguei, senhor."
        self.abrir(f"whatsapp://send?phone={numero}")
        for _ in range(40):  # ate ~10 s para o WhatsApp abrir e ficar em primeiro plano
            if self._whatsapp_na_frente():
                break
            self.esperar(0.25)
        else:
            return False, "Não consegui trazer o WhatsApp para a frente; não liguei, senhor."
        self.esperar(1.6)  # a conversa carrega
        if not self._whatsapp_na_frente() or self.tela_cheia():
            return False, "O WhatsApp perdeu o foco antes de ligar; não liguei, senhor."
        if self.dry_run:
            return True, "Simulação: tudo pronto, mas não apertei o botão de ligar, senhor."
        self.enviar_atalho(ATALHO_LIGAR_VOZ)
        return True, ""


# ------------------------------------------------------------------ pecas reais do Windows
def abrir_real(uri: str) -> None:
    import os

    os.startfile(uri)


def janela_ativa_real() -> tuple[str, str]:
    import ctypes
    from ctypes import wintypes

    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    h = u.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(h, buf, 256)
    titulo = buf.value
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    proc = ""
    ph = k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if ph:
        n = wintypes.DWORD(520)
        caminho = ctypes.create_unicode_buffer(520)
        if k.QueryFullProcessImageNameW(ph, 0, caminho, ctypes.byref(n)):
            proc = caminho.value.rsplit("\\", 1)[-1]
        k.CloseHandle(ph)
    return proc, titulo


def tela_cheia_real() -> bool:
    import ctypes

    e = ctypes.c_int(0)
    return ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(e)) == 0 and e.value in (2, 3, 4)


def enviar_atalho_real(vks: tuple[int, ...]) -> None:
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def evento(vk: int, soltar: bool) -> INPUT:
        return INPUT(1, _U(ki=KEYBDINPUT(vk, 0, 0x0002 if soltar else 0, 0, 0)))

    seq = [evento(v, False) for v in vks] + [evento(v, True) for v in reversed(vks)]
    arr = (INPUT * len(seq))(*seq)
    ctypes.windll.user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def ligador_real(dry_run: bool = False) -> Ligador:
    return Ligador(abrir_real, janela_ativa_real, enviar_atalho_real, tela_cheia_real, dry_run=dry_run)
