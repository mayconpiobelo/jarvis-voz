"""Musica: leitura, controle e comandos de voz, com um player falso (sem Spotify, sem Windows, sem rede)."""
import io
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import musica  # noqa: E402


def png(cor):
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (8, 8), cor).save(b, "PNG")
    return b.getvalue()


class Falso:
    def __init__(self, estado="tocando", titulo="Faixa Um", artista="Banda", sessao=True):
        self.s = {"app": "Spotify", "titulo": titulo, "artista": artista, "album": "Disco", "estado": estado, "posicao_s": 30.0,
                  "duracao_s": 200.0, "tem_capa": True, "pode": {"anterior": True, "proxima": True, "play_pause": True}}
        self.sessao, self.acoes, self.chamadas_capa = sessao, [], 0

    def snapshot(self, preferir):
        return dict(self.s) if self.sessao else None

    def capa(self, preferir):
        self.chamadas_capa += 1
        return png((200, 30, 30))

    def acao(self, acao, preferir):
        self.acoes.append(acao)
        if acao == "play_pause":
            self.s["estado"] = "pausado" if self.s["estado"] == "tocando" else "tocando"
        return True


@pytest.fixture()
def fake():
    f = Falso()
    musica.definir_backend(f)
    yield f
    musica.definir_backend(None)


def test_snapshot_completo_e_capa_so_uma_vez(fake):
    s = musica.snapshot(validade=0)
    assert s["ativo"] and s["titulo"] == "Faixa Um" and s["estado"] == "tocando" and s["duracao_s"] == 200.0
    assert s["pode"]["proxima"] and s["capa"] and s["capa_id"]
    r = int(s["cor"][1:3], 16)
    assert s["cor"].startswith("#") and r > 120                     # capa avermelhada -> cor avermelhada
    musica.snapshot(validade=0)
    assert fake.chamadas_capa == 1                                    # mesma faixa: nao baixa a capa de novo
    fake.s["titulo"] = "Faixa Dois"
    musica.snapshot(validade=0)
    assert fake.chamadas_capa == 2
    dados, mime = musica.capa_bytes()
    assert mime == "image/png" and dados[:4] == b"\x89PNG"


def test_capa_que_falhou_tenta_de_novo(fake, monkeypatch):
    # Bug real: a capa falhou uma vez (Windows ainda sem a imagem / prazo estourado) e a faixa ficou "sem capa" para sempre.
    monkeypatch.setattr(musica, "CAPA_INTERVALO", 0.0)
    falhas = {"n": 2}
    boa = fake.capa

    def capa_falha(preferir):
        if falhas["n"]:
            falhas["n"] -= 1
            raise RuntimeError("sem imagem ainda")
        return boa(preferir)

    fake.capa = capa_falha
    assert musica.snapshot(validade=0)["capa"] is False
    assert musica.snapshot(validade=0)["capa"] is False
    s = musica.snapshot(validade=0)
    assert s["capa"] is True and s["cor"] != "#1db954" and musica.capa_bytes() is not None


def test_capa_nao_insiste_para_sempre(fake, monkeypatch):
    monkeypatch.setattr(musica, "CAPA_INTERVALO", 0.0)
    n = {"c": 0}

    def sempre_falha(preferir):
        n["c"] += 1
        raise RuntimeError("x")

    fake.capa = sempre_falha
    for _ in range(20):
        assert musica.snapshot(validade=0)["capa"] is False
    assert n["c"] == musica.CAPA_TENTATIVAS


def test_sem_sessao_ou_sem_faixa(fake):
    fake.sessao = False
    assert musica.snapshot(validade=0)["ativo"] is False
    fake.sessao = True
    fake.s["titulo"] = fake.s["artista"] = ""
    assert musica.snapshot(validade=0)["ativo"] is False


def test_backend_com_erro_nao_derruba():
    class Quebrado(Falso):
        def snapshot(self, preferir):
            raise RuntimeError("falhou")

    musica.definir_backend(Quebrado())
    try:
        s = musica.snapshot(validade=0)
        assert s["disponivel"] and not s["ativo"]
    finally:
        musica.definir_backend(None)


class Travado(Falso):
    """Como o SMTC do Windows quando para de responder: a chamada nunca volta."""

    def __init__(self):
        super().__init__()
        self.solta = threading.Event()
        self.chamadas = 0

    def snapshot(self, preferir):
        self.chamadas += 1
        self.solta.wait(30)
        return super().snapshot(preferir)

    def acao(self, acao, preferir):
        self.chamadas += 1
        self.solta.wait(30)
        return True


def test_windows_travado_nao_pendura_o_painel(monkeypatch):
    # Bug real: o controle de midia do Windows travou, cada consulta do painel ficou pendurada para sempre, o navegador
    # esgotou as 6 conexoes e o painel inteiro parou (estado "desligado", tarefas que nao entram).
    monkeypatch.setattr(musica, "LIMITE", 0.2)
    monkeypatch.setattr(musica, "PAUSA", 0.6)
    t = Travado()
    musica.definir_backend(t)
    try:
        t0 = time.monotonic()
        s = musica.snapshot(validade=0)
        assert time.monotonic() - t0 < 1.5                                # desistiu no prazo
        assert s["disponivel"] is False and "não respondeu" in s["motivo"]
        t0 = time.monotonic()
        for _ in range(50):                                               # varias consultas seguidas: respondem na hora
            assert musica.snapshot(validade=0)["disponivel"] is False
        assert time.monotonic() - t0 < 0.5 and t.chamadas == 1            # e sem abrir uma thread presa por consulta
        assert musica.acao("proxima")["ok"] is False                      # o botao tambem nao pendura
        time.sleep(0.7)                                                   # passou a pausa: tenta de novo
        t.solta.set()
        assert musica.snapshot(validade=0)["ativo"] is True               # e volta ao normal quando o Windows volta
    finally:
        t.solta.set()
        musica.definir_backend(None)


def test_consultas_simultaneas_com_windows_travado_voltam_todas_no_prazo(monkeypatch):
    monkeypatch.setattr(musica, "LIMITE", 0.2)
    t = Travado()
    musica.definir_backend(t)
    resultados = []
    try:
        ths = [threading.Thread(target=lambda: resultados.append(musica.snapshot(validade=0))) for _ in range(12)]
        t0 = time.monotonic()
        for th in ths:
            th.start()
        for th in ths:
            th.join(5)
        assert time.monotonic() - t0 < 4 and len(resultados) == 12 and not any(th.is_alive() for th in ths)
        assert all(r["disponivel"] is False for r in resultados)
    finally:
        t.solta.set()
        musica.definir_backend(None)


def test_acao_com_windows_travado_responde_com_erro(monkeypatch):
    monkeypatch.setattr(musica, "LIMITE", 0.2)
    t = Travado()
    musica.definir_backend(t)
    try:
        t0 = time.monotonic()
        r = musica.acao("play_pause")
        assert r["ok"] is False and "não respondeu" in r["erro"] and time.monotonic() - t0 < 1.5
    finally:
        t.solta.set()
        musica.definir_backend(None)


def test_modulo_ausente_vira_indisponivel(monkeypatch):
    monkeypatch.setattr(musica, "WinrtBackend", lambda: (_ for _ in ()).throw(ImportError("sem winrt")))
    musica._backend, musica._indisponivel = None, None
    s = musica.snapshot(validade=0)
    assert s["disponivel"] is False and "sem winrt" in s["motivo"]
    musica.definir_backend(None)


def test_acao_so_aceita_nomes_conhecidos(fake):
    assert musica.acao("apagar_tudo") == {"ok": False, "erro": "acao desconhecida"}
    assert musica.acao("../x")["ok"] is False
    assert musica.acao("proxima")["ok"] is True and fake.acoes == ["proxima"]


@pytest.mark.parametrize("frase,acao", [
    ("Jarvis, pausa a música", "play_pause"), ("pause o spotify", "play_pause"), ("para a música", "play_pause"),
    ("próxima música", "proxima"), ("Jarvis, pula a música", "proxima"), ("toca a próxima", "proxima"),
    ("música anterior", "anterior"), ("volta uma música", "anterior"), ("toca a música anterior", "anterior"),
])
def test_comandos_quando_esta_tocando(fake, frase, acao):
    musica.snapshot(validade=0)
    r = musica.responder(frase)
    assert r and r.endswith("senhor.") and fake.acoes == [acao], (frase, r, fake.acoes)


@pytest.mark.parametrize("frase", ["toca a música", "continua a música", "dá play", "play", "retoma o spotify"])
def test_retomar_quando_pausado(fake, frase):
    fake.s["estado"] = "pausado"
    musica.definir_backend(fake)
    assert musica.responder(frase) == "Retomando, senhor." and fake.acoes == ["play_pause"]


def test_respostas_sensatas_quando_ja_esta_no_estado(fake):
    fake.s["estado"] = "pausado"
    musica.definir_backend(fake)
    assert musica.responder("pausa a música") == "Já está pausado, senhor." and fake.acoes == []
    fake.s["estado"] = "tocando"
    musica.definir_backend(fake)
    assert musica.responder("toca a música") == "Já está tocando, senhor." and fake.acoes == []


def test_o_que_esta_tocando(fake):
    r = musica.responder("Jarvis, o que está tocando?")
    assert "Faixa Um" in r and "Banda" in r and r.startswith("Está tocando")
    fake.s["estado"] = "pausado"
    musica.definir_backend(fake)
    assert musica.responder("que música é essa").startswith("Está pausada")


def test_sem_player_avisa(fake):
    fake.sessao = False
    musica.definir_backend(fake)
    assert musica.responder("próxima música") == "Não encontrei nenhum player de música ativo, senhor."
    assert musica.responder("o que está tocando") == "Não há nada tocando no momento, senhor."


@pytest.mark.parametrize("frase", [
    "toca uma música do Queen", "pausa a reunião", "para o relatório", "próxima reunião da agenda",
    "qual é a capital da França", "o que", "o que é isso", "toca o alarme às seis", "volta para o início do documento",
    "pula essa etapa", "play the song by Queen", "volta a música",   # ambiguo (voltar faixa ou retomar): vai para o Claude
    "toca a música do Queen para mim agora por favor",           # longa demais
])
def test_nao_sequestra_outros_pedidos(fake, frase):
    assert musica.responder(frase) is None
    assert fake.acoes == []
