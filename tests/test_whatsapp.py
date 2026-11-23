"""Ligacao pelo WhatsApp: interpretacao, contatos, travas e confirmacao por voz (sem ligar para ninguem)."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jarvis  # noqa: E402
import whatsapp  # noqa: E402

CONTATOS = {"maria": "(11) 90000-0001", "joao silva": "+55 21 90000-0002", "joao souza": "21 90000-0003"}


@pytest.mark.parametrize("fala,nome", [
    ("Jarvis, liga para a Maria no WhatsApp", "maria"),
    ("liga pro João Silva no zap", "joao silva"),
    ("faz uma ligação para a Maria pelo WhatsApp", "maria"),
    ("chama o João no whatsapp", "joao"),
    ("por favor, ligue para a Maria no WhatsApp", "maria"),
])
def test_interpretar_pedidos_de_ligacao(fala, nome):
    assert whatsapp.interpretar(fala) == nome


@pytest.mark.parametrize("fala", [
    "liga para a Maria",                                  # sem citar o WhatsApp: pode ser outra ligacao
    "abre o WhatsApp",                                    # sem verbo de ligar
    "manda mensagem para a Maria no WhatsApp",
    "liga no whatsapp",                                   # sem nome
    "qual a previsão do tempo",
    "liga para o fornecedor de materiais elétricos de São Paulo no WhatsApp amanhã cedo por favor urgente " * 2,
])
def test_nao_interpreta_o_que_nao_e_ligacao(fala):
    assert whatsapp.interpretar(fala) is None


def test_resolver_contatos():
    assert whatsapp.resolver("maria", CONTATOS) == [("maria", "(11) 90000-0001")]
    assert whatsapp.resolver("joao silva", CONTATOS) == [("joao silva", "+55 21 90000-0002")]
    assert [k for k, _ in whatsapp.resolver("joao", CONTATOS)] == ["joao silva", "joao souza"]   # ambiguo
    assert whatsapp.resolver("carlos", CONTATOS) == []
    assert whatsapp.resolver("maria santos", CONTATOS) == [("maria", "(11) 90000-0001")]          # falou o sobrenome a mais
    assert whatsapp.resolver("maria", {}) == []


@pytest.mark.parametrize("bruto,esperado", [
    ("(11) 90000-0001", "5511900000001"), ("+55 21 90000-0002", "5521900000002"), ("21 3000-0000", "552130000000"),
    ("0055 11 90000-0001", "5511900000001"), ("1234", None), ("", None), ("abc", None), ("1" * 20, None),
])
def test_normalizar_numero(bruto, esperado):
    assert whatsapp.normalizar_numero(bruto) == esperado


class Falsos:
    """Windows de mentira: registra o que seria feito."""

    def __init__(self, proc="WhatsApp.Root.exe", titulo="WhatsApp", tela_cheia=False, abre_em=0):
        self.eventos, self.proc, self.titulo, self._tela_cheia, self.abre_em, self.chamadas = [], proc, titulo, tela_cheia, abre_em, 0

    def abrir(self, uri):
        self.eventos.append(("abrir", uri))

    def janela(self):
        self.chamadas += 1
        return (self.proc, self.titulo) if self.chamadas > self.abre_em else ("explorer.exe", "Outra coisa")

    def atalho(self, vks):
        self.eventos.append(("atalho", vks))

    def tela_cheia(self):
        return self._tela_cheia

    def ligador(self, dry_run=False):
        return whatsapp.Ligador(self.abrir, self.janela, self.atalho, self.tela_cheia, esperar=lambda s: None, dry_run=dry_run)


def test_liga_abrindo_a_conversa_e_enviando_o_atalho():
    f = Falsos()
    ok, frase = f.ligador().ligar("5511900000001")
    assert ok and frase == ""
    assert f.eventos == [("abrir", "whatsapp://send?phone=5511900000001"), ("atalho", whatsapp.ATALHO_LIGAR_VOZ)]
    assert whatsapp.ATALHO_LIGAR_VOZ == (0x11, 0x10, 0x43)


def test_espera_o_whatsapp_ficar_na_frente():
    f = Falsos(abre_em=5)
    assert f.ligador().ligar("5511900000001")[0] is True


def test_nao_envia_tecla_se_outra_janela_esta_na_frente():
    f = Falsos(proc="chrome.exe", titulo="Banco - Chrome")
    ok, frase = f.ligador().ligar("5511900000001")
    assert not ok and "não liguei" in frase
    assert all(e[0] != "atalho" for e in f.eventos)
    f2 = Falsos(titulo="WhatsApp Business Web")                                         # titulo diferente de "WhatsApp"
    assert not f2.ligador().ligar("5511900000001")[0] and all(e[0] != "atalho" for e in f2.eventos)


def test_nao_liga_com_jogo_em_tela_cheia():
    f = Falsos(tela_cheia=True)
    ok, frase = f.ligador().ligar("5511900000001")
    assert not ok and "tela cheia" in frase and f.eventos == []                          # nem abre o WhatsApp


def test_dry_run_faz_tudo_menos_ligar():
    f = Falsos()
    ok, frase = f.ligador(dry_run=True).ligar("5511900000001")
    assert ok and "Simulação" in frase
    assert [e[0] for e in f.eventos] == ["abrir"]


# ---- confirmacao por voz no jarvis.py
class LigadorFalso:
    chamadas: list = []

    def __init__(self, dry_run=False):
        pass

    def ligar(self, numero):
        LigadorFalso.chamadas.append(numero)
        return True, ""


@pytest.fixture()
def cfg_whatsapp(monkeypatch):
    LigadorFalso.chamadas = []
    monkeypatch.setitem(jarvis.CFG, "whatsapp", {"enabled": True, "ddi_padrao": "55", "dry_run": True, "contatos": dict(CONTATOS)})
    monkeypatch.setattr(jarvis, "_ligacao_pendente", None)
    monkeypatch.setattr(jarvis, "_pending_until", 0.0)
    monkeypatch.setattr(whatsapp, "ligador_real", lambda dry_run=False: LigadorFalso())
    return LigadorFalso


def test_pede_confirmacao_e_so_liga_depois_do_sim(cfg_whatsapp):
    fala, depois = jarvis.tratar_ligacao("Jarvis, liga para a Maria no WhatsApp")
    assert "Ligar para maria pelo WhatsApp" in fala and "Confirma?" in fala and depois is None
    assert cfg_whatsapp.chamadas == []                                                     # nada acontece antes do "confirma"
    fala2, depois2 = jarvis.tratar_ligacao("confirma")
    assert fala2.startswith("Ligando para maria") and depois2 is not None
    assert cfg_whatsapp.chamadas == []                                                     # ainda nao: so depois de falar
    depois2()
    assert cfg_whatsapp.chamadas == ["5511900000001"]
    assert jarvis.tratar_ligacao("confirma") is None                                       # o "confirma" vale uma vez so


def test_cancelar_ou_falar_outra_coisa_nao_liga(cfg_whatsapp):
    jarvis.tratar_ligacao("liga para a Maria no zap")
    assert jarvis.tratar_ligacao("não") == ("Cancelado, senhor.", None)
    jarvis.tratar_ligacao("liga para a Maria no zap")
    assert jarvis.tratar_ligacao("qual a previsão do tempo") is None                       # outra coisa: cai a pergunta
    assert jarvis.tratar_ligacao("confirma") is None                                       # e o "confirma" tardio nao liga
    assert cfg_whatsapp.chamadas == []


def test_confirmacao_expira(cfg_whatsapp, monkeypatch):
    jarvis.tratar_ligacao("liga para a Maria no zap")
    nome, numero, _ = jarvis._ligacao_pendente
    monkeypatch.setattr(jarvis, "_ligacao_pendente", (nome, numero, time.time() - 1))
    assert jarvis.tratar_ligacao("confirma") is None and cfg_whatsapp.chamadas == []


def test_contato_desconhecido_ambiguo_ou_invalido(cfg_whatsapp, monkeypatch):
    assert "Não tenho o número de carlos" in jarvis.tratar_ligacao("liga para o Carlos no WhatsApp")[0]
    assert "mais de um contato" in jarvis.tratar_ligacao("liga para o João no WhatsApp")[0]
    monkeypatch.setitem(jarvis.CFG["whatsapp"], "contatos", {"ana": "123"})
    assert "não parece válido" in jarvis.tratar_ligacao("liga para a Ana no WhatsApp")[0]
    assert jarvis._ligacao_pendente is None                                                # nenhum desses deixa pedido pendente


def test_desligado_no_config_ignora_o_pedido(cfg_whatsapp, monkeypatch):
    monkeypatch.setitem(jarvis.CFG["whatsapp"], "enabled", False)
    assert jarvis.tratar_ligacao("liga para a Maria no WhatsApp") is None
