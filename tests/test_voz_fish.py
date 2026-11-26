"""Voz Fish Audio (nuvem, paga): pedido, saldo, chave e reserva no Edge/Kokoro. Nenhum teste usa a rede."""
import io
import json
import sys
import urllib.error
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jarvis  # noqa: E402

SR = 24000
CHAVE = "chave-de-teste-nao-vazar"
VOZ = "0123456789abcdef0123456789abcdef"


def _wav(segundos: float = 1.0) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.full(int(SR * segundos), 0.1, dtype="float32"), SR, format="WAV")
    return buf.getvalue()


class _Resp:
    def __init__(self, dados):
        self._d = dados

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http(codigo, corpo=b""):
    return urllib.error.HTTPError("https://api.fish.audio/v1/tts", codigo, "x", {}, io.BytesIO(corpo))


def _urlopen(monkeypatch, respostas):
    """Cada chamada devolve (ou levanta) o proximo item; guarda os pedidos feitos."""
    pedidos = []

    def falso(req, timeout=None):
        pedidos.append(req)
        r = respostas[min(len(pedidos) - 1, len(respostas) - 1)]
        if isinstance(r, Exception):
            raise r
        return _Resp(r)

    monkeypatch.setattr(jarvis.urllib.request, "urlopen", falso)
    monkeypatch.setattr(jarvis.time, "sleep", lambda s: None)
    jarvis._stop.clear()
    return pedidos


# ------------------------------------------------------------------ id da voz e chave
def test_aceita_id_ou_url_da_voz():
    assert jarvis.fish_voice_id(VOZ) == VOZ
    assert jarvis.fish_voice_id(f"https://fish.audio/m/{VOZ.upper()}/") == VOZ
    assert jarvis.fish_voice_id("") == "" and jarvis.fish_voice_id(None) == ""
    assert jarvis.fish_voice_id("minha-voz-sem-id") == ""


def test_chave_vem_do_config_ou_do_ambiente(monkeypatch):
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    monkeypatch.setitem(jarvis.CFG, "fish_api_key", "")
    assert jarvis.fish_chave() == ""
    monkeypatch.setenv("FISH_API_KEY", " do-ambiente ")
    assert jarvis.fish_chave() == "do-ambiente"
    monkeypatch.setitem(jarvis.CFG, "fish_api_key", "do-config")
    assert jarvis.fish_chave() == "do-config"


# ------------------------------------------------------------------ o pedido
def test_pedido_leva_chave_modelo_voz_e_texto(monkeypatch):
    pedidos = _urlopen(monkeypatch, [_wav()])
    assert jarvis._fish_pedido("Ola, senhor.", CHAVE, VOZ, "s2-pro", 5) == _wav()
    req = pedidos[0]
    assert req.full_url == "https://api.fish.audio/v1/tts" and req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer " + CHAVE
    assert req.get_header("Model") == "s2-pro"
    corpo = json.loads(req.data)
    assert corpo["text"] == "Ola, senhor." and corpo["reference_id"] == VOZ
    assert corpo["format"] == "wav" and corpo["sample_rate"] == 24000 and corpo["temperature"] == 0.3


def test_sem_voz_escolhida_usa_a_voz_padrao_do_fish(monkeypatch):
    pedidos = _urlopen(monkeypatch, [_wav()])
    jarvis._fish_pedido("Ola.", CHAVE, "", "s2-pro", 5)
    assert "reference_id" not in json.loads(pedidos[0].data)


@pytest.mark.parametrize("codigo,corpo", [(402, b""), (403, b'{"message":"insufficient balance"}'),
                                         (400, b"out of credit"), (401, b"")])
def test_sem_saldo_ou_chave_recusada_levanta_fish_sem_credito(monkeypatch, codigo, corpo):
    _urlopen(monkeypatch, [_http(codigo, corpo)])
    with pytest.raises(jarvis.FishSemCredito):
        jarvis._fish_pedido("Ola.", CHAVE, VOZ, "s2-pro", 5)


def test_outro_erro_http_nao_vaza_a_resposta_nem_a_chave(monkeypatch):
    _urlopen(monkeypatch, [_http(500, ("corpo secreto " + CHAVE).encode())])
    with pytest.raises(RuntimeError) as e:
        jarvis._fish_pedido("Ola.", CHAVE, VOZ, "s2-pro", 5)
    assert "500" in str(e.value) and CHAVE not in str(e.value) and "secreto" not in str(e.value)


# ------------------------------------------------------------------ repeticao
def test_repete_em_falha_comum_e_devolve_o_audio(monkeypatch):
    pedidos = _urlopen(monkeypatch, [_http(429), _wav(2.0)])
    audio, sr = jarvis.fish_audio("Ola, senhor.", CHAVE, VOZ, "s2-pro")
    assert sr == SR and len(audio) == 2 * SR and len(pedidos) == 2


def test_nao_repete_quando_falta_saldo(monkeypatch):
    pedidos = _urlopen(monkeypatch, [_http(402)])
    with pytest.raises(jarvis.FishSemCredito):
        jarvis.fish_audio("Ola.", CHAVE, VOZ, "s2-pro", tentativas=3)
    assert len(pedidos) == 1


def test_desiste_depois_das_tentativas(monkeypatch):
    pedidos = _urlopen(monkeypatch, [OSError("sem rede")])
    with pytest.raises(RuntimeError, match="Fish Audio nao respondeu"):
        jarvis.fish_audio("Ola.", CHAVE, VOZ, "s2-pro", tentativas=2)
    assert len(pedidos) == 2


# ------------------------------------------------------------------ speak_fish
def _setup(monkeypatch, chave=CHAVE):
    monkeypatch.setitem(jarvis.CFG, "fish_api_key", chave)
    monkeypatch.setitem(jarvis.CFG, "fish_voice_id", VOZ)
    monkeypatch.setitem(jarvis.CFG, "fish_model", "s2-pro")
    monkeypatch.setattr(jarvis, "_fish_pausa_ate", 0.0)
    monkeypatch.setattr(jarvis, "_fish_gratis_pausa_ate", 0.0)
    monkeypatch.setitem(jarvis.CFG, "fish_model_gratis", "s2.1-pro-free")
    fish, reserva = [], []
    monkeypatch.setattr(jarvis, "fish_audio", lambda *a, **k: fish.append(a) or (np.zeros(10, "float32"), SR))
    monkeypatch.setattr(jarvis, "_gerador_edge_com_reserva",
                        lambda: (lambda f: reserva.append(f) or (np.zeros(5, "float32"), SR)))
    falas = []

    def captura(texto, gerar):
        falas.append([gerar(s) for s in jarvis.split_sentences(texto)])

    monkeypatch.setattr(jarvis, "_falar_frases", captura)
    return fish, reserva


def test_com_chave_fala_pelo_fish_com_a_voz_e_o_modelo_do_config(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    jarvis.speak_fish("Tudo certo, senhor.")
    assert len(fish) == 1 and reserva == []
    frase, chave, voz, modelo = fish[0][:4]
    assert chave == CHAVE and voz == VOZ and modelo == "s2-pro"


def test_sem_chave_nem_tenta_o_fish(monkeypatch):
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    fish, reserva = _setup(monkeypatch, chave="")
    jarvis.speak_fish("Tudo certo, senhor.")
    assert fish == [] and len(reserva) == 1


def test_falha_comum_cai_na_reserva_e_descansa_um_minuto(monkeypatch):
    fish, reserva = _setup(monkeypatch)

    def quebra(*a, **k):
        raise RuntimeError("falhou")

    monkeypatch.setattr(jarvis, "fish_audio", quebra)
    jarvis.speak_fish("Primeira frase longa o bastante. Segunda frase longa o bastante.")
    assert len(reserva) == 2
    assert 0 < jarvis._fish_pausa_ate - jarvis.time.monotonic() <= jarvis.FISH_PAUSA


def test_sem_saldo_descansa_uma_hora_e_nao_insiste(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    chamadas = []

    def sem_saldo(*a, **k):
        chamadas.append(1)
        raise jarvis.FishSemCredito("Fish Audio: sem saldo")

    monkeypatch.setattr(jarvis, "fish_audio", sem_saldo)
    jarvis.speak_fish("Primeira frase longa o bastante. Segunda frase longa o bastante.")
    assert len(chamadas) == 2 and len(reserva) == 2   # pago + gratuito na 1a frase; a 2a ja nem tenta o Fish
    assert jarvis._fish_pausa_ate - jarvis.time.monotonic() > 3000
    assert jarvis._fish_gratis_pausa_ate - jarvis.time.monotonic() > 3000


def test_speak_escolhe_o_fish(monkeypatch):
    usados = []
    monkeypatch.setattr(jarvis, "speak_fish", lambda t: usados.append("fish"))
    monkeypatch.setattr(jarvis, "speak_sapi", lambda t: usados.append("sapi"))
    monkeypatch.setitem(jarvis.CFG, "tts_engine", "fish")
    jarvis.speak("Ola, senhor.")
    assert usados == ["fish"]


def test_config_de_exemplo_do_fish():
    # O autor decidiu publicar a PROPRIA chave no exemplo (decisao dele, ciente de que o repositorio e publico).
    ex = json.loads((Path(__file__).resolve().parent.parent / "config.example.json").read_text(encoding="utf-8"))
    assert str(ex.get("fish_api_key", "")).startswith("sk-fish-")
    assert ex.get("fish_model", "s2-pro") == "s2-pro"


# ------------------------------------------------------------------ modelo gratuito (mesma voz) antes do Edge
def _modelos_usados(monkeypatch, falha_pago=None, falha_gratis=None):
    usados = []

    def fala(frase, chave, voz, modelo, *a, **k):
        usados.append((modelo, voz))
        erro = falha_pago if modelo == "s2-pro" else falha_gratis
        if erro:
            raise erro
        return np.zeros(10, "float32"), SR

    monkeypatch.setattr(jarvis, "fish_audio", fala)
    return usados


def test_sem_saldo_continua_com_a_mesma_voz_no_modelo_gratuito(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    usados = _modelos_usados(monkeypatch, falha_pago=jarvis.FishSemCredito("sem saldo"))
    jarvis.speak_fish("Primeira frase longa o bastante. Segunda frase longa o bastante.")
    assert usados == [("s2-pro", VOZ), ("s2.1-pro-free", VOZ), ("s2.1-pro-free", VOZ)]  # 2a frase vai direto ao gratuito
    assert reserva == []                                                            # Edge/Kokoro nem foram usados


def test_se_o_gratuito_tambem_falhar_cai_no_edge_e_kokoro(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    _modelos_usados(monkeypatch, falha_pago=jarvis.FishSemCredito("sem saldo"), falha_gratis=RuntimeError("fora do ar"))
    jarvis.speak_fish("Primeira frase longa o bastante. Segunda frase longa o bastante.")
    assert len(reserva) == 2


def test_chave_recusada_nao_tenta_o_gratuito(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    usados = _modelos_usados(monkeypatch, falha_pago=jarvis.FishSemCredito("chave", chave_recusada=True))
    jarvis.speak_fish("Primeira frase longa o bastante. Segunda frase longa o bastante.")
    assert [m for m, _ in usados] == ["s2-pro"] and len(reserva) == 2


def test_falha_comum_do_pago_tenta_o_gratuito_antes_do_edge(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    usados = _modelos_usados(monkeypatch, falha_pago=RuntimeError("429"))
    jarvis.speak_fish("Tudo certo, senhor.")
    assert [m for m, _ in usados] == ["s2-pro", "s2.1-pro-free"] and reserva == []


def test_gratuito_desligado_vai_direto_para_o_edge(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    monkeypatch.setitem(jarvis.CFG, "fish_model_gratis", "")
    usados = _modelos_usados(monkeypatch, falha_pago=jarvis.FishSemCredito("sem saldo"))
    jarvis.speak_fish("Tudo certo, senhor.")
    assert [m for m, _ in usados] == ["s2-pro"] and len(reserva) == 1


# ------------------------------------------------------------------ velocidade da fala
def test_pedido_so_leva_velocidade_quando_diferente_de_1(monkeypatch):
    pedidos = _urlopen(monkeypatch, [_wav(), _wav()])
    jarvis._fish_pedido("Ola.", CHAVE, VOZ, "s2-pro", 5)
    assert "prosody" not in json.loads(pedidos[0].data)
    jarvis._fish_pedido("Ola.", CHAVE, VOZ, "s2-pro", 5, 0.95)
    assert json.loads(pedidos[1].data)["prosody"] == {"speed": 0.95, "volume": 0}


def test_velocidade_do_config_invalida_vira_normal(monkeypatch):
    for bruto, esperado in ((0.95, 0.95), ("0.9", 0.9), (None, 1.0), ("", 1.0), ("rapido", 1.0), (0.1, 1.0), (5, 1.0)):
        monkeypatch.setitem(jarvis.CFG, "fish_speed_x", bruto)
        assert jarvis.fish_velocidade("fish_speed_x") == esperado, bruto


def test_cada_modelo_usa_a_sua_velocidade(monkeypatch):
    fish, reserva = _setup(monkeypatch)
    monkeypatch.setitem(jarvis.CFG, "fish_speed", 1.0)
    monkeypatch.setitem(jarvis.CFG, "fish_speed_gratis", 0.94)
    vistas = []

    def fala(frase, chave, voz, modelo, *a, velocidade=1.0, **k):
        vistas.append((modelo, velocidade))
        if modelo == "s2-pro":
            raise jarvis.FishSemCredito("sem saldo")
        return np.zeros(10, "float32"), SR

    monkeypatch.setattr(jarvis, "fish_audio", fala)
    jarvis.speak_fish("Tudo certo, senhor.")
    assert vistas == [("s2-pro", 1.0), ("s2.1-pro-free", 0.94)]
