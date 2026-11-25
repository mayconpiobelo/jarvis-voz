"""Voz Edge TTS (nuvem): repeticao, audio cortado e reserva no Kokoro. Nenhum teste usa a rede."""
import io
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jarvis  # noqa: E402

SR = 24000


def _wav(segundos: float) -> bytes:
    """Um 'MP3' de mentira: o soundfile le WAV igualmente, e e o que importa para o teste."""
    buf = io.BytesIO()
    sf.write(buf, np.full(int(SR * segundos), 0.1, dtype="float32"), SR, format="WAV")
    return buf.getvalue()


def _mp3s(monkeypatch, respostas):
    """Faz _edge_mp3 devolver (ou levantar) cada item de `respostas`, em ordem."""
    chamadas = []

    async def falso(frase, voz, prazo, **ajustes):
        chamadas.append((frase, voz))
        r = respostas[min(len(chamadas) - 1, len(respostas) - 1)]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(jarvis, "_edge_mp3", falso)
    monkeypatch.setattr(jarvis.time, "sleep", lambda s: None)
    jarvis._stop.clear()
    return chamadas


def test_devolve_o_audio_da_frase(monkeypatch):
    chamadas = _mp3s(monkeypatch, [_wav(2.0)])
    audio, sr = jarvis.edge_audio("Perfeitamente, senhor.", "pt-BR-AntonioNeural")
    assert sr == SR and len(audio) == 2 * SR
    assert chamadas == [("Perfeitamente, senhor.", "pt-BR-AntonioNeural")]


def test_repete_quando_a_microsoft_nao_devolve_audio(monkeypatch):
    chamadas = _mp3s(monkeypatch, [RuntimeError("No audio was received"), _wav(2.0)])
    audio, _ = jarvis.edge_audio("Perfeitamente, senhor.", "v")
    assert len(audio) == 2 * SR and len(chamadas) == 2


def test_repete_quando_o_audio_vem_cortado(monkeypatch):
    frase = "Receio que isso esteja bloqueado, senhor. Mas fico feliz em sugerir uma alternativa."
    chamadas = _mp3s(monkeypatch, [_wav(1.7), _wav(6.8)])  # 1,7 s para 85 letras = cortado
    audio, _ = jarvis.edge_audio(frase, "v")
    assert len(audio) == int(6.8 * SR) and len(chamadas) == 2


def test_desiste_depois_das_tentativas(monkeypatch):
    chamadas = _mp3s(monkeypatch, [RuntimeError("sem rede")])
    with pytest.raises(RuntimeError, match="Edge TTS nao respondeu"):
        jarvis.edge_audio("Ola, senhor.", "v", tentativas=3)
    assert len(chamadas) == 3


def test_frase_curta_nao_e_tomada_por_cortada(monkeypatch):
    _mp3s(monkeypatch, [_wav(0.4)])
    audio, _ = jarvis.edge_audio("Ok.", "v")
    assert len(audio) > 0


def _captura_falas(monkeypatch):
    falas = []

    def falso(texto, gerar):
        falas.append([gerar(s) for s in jarvis.split_sentences(texto)])

    monkeypatch.setattr(jarvis, "_falar_frases", falso)
    return falas


def test_speak_edge_usa_a_voz_do_config(monkeypatch):
    chamadas = _mp3s(monkeypatch, [_wav(3.0)])
    monkeypatch.setitem(jarvis.CFG, "edge_voice", "pt-BR-FranciscaNeural")
    monkeypatch.setattr(jarvis, "_edge_pausa_ate", 0.0)
    _captura_falas(monkeypatch)
    jarvis.speak_edge("Tudo certo, senhor.")
    assert chamadas and all(v == "pt-BR-FranciscaNeural" for _, v in chamadas)


def test_se_o_edge_cair_fala_com_o_kokoro_e_descansa(monkeypatch):
    chamadas = _mp3s(monkeypatch, [RuntimeError("sem rede")])
    kokoro = []
    monkeypatch.setattr(jarvis, "_kokoro_gerador", lambda: (lambda f: kokoro.append(f) or (np.zeros(10, "float32"), SR)))
    monkeypatch.setattr(jarvis, "_edge_pausa_ate", 0.0)
    _captura_falas(monkeypatch)

    jarvis.speak_edge("Primeira frase longa o bastante. Segunda frase longa o bastante.")
    assert len(chamadas) == 3                      # 3 tentativas na primeira frase...
    assert len(kokoro) == 2                        # ...e as duas frases saem em Kokoro
    assert jarvis._edge_pausa_ate > jarvis.time.monotonic()

    jarvis.speak_edge("Outra frase, ainda em descanso.")
    assert len(chamadas) == 3                      # nao tentou o Edge de novo durante o descanso
    assert len(kokoro) == 3


def test_speak_escolhe_o_motor_do_config(monkeypatch):
    usados = []
    monkeypatch.setattr(jarvis, "speak_edge", lambda t: usados.append("edge"))
    monkeypatch.setattr(jarvis, "speak_kokoro", lambda t: usados.append("kokoro"))
    monkeypatch.setattr(jarvis, "speak_sapi", lambda t: usados.append("sapi"))
    for motor, esperado in (("edge", "edge"), ("kokoro", "kokoro"), ("sapi", "sapi")):
        monkeypatch.setitem(jarvis.CFG, "tts_engine", motor)
        usados.clear()
        jarvis.speak("Ola, senhor.")
        assert usados == [esperado]


def test_se_o_motor_levantar_erro_cai_na_voz_do_windows(monkeypatch):
    usados = []

    def quebra(t):
        raise RuntimeError("falhou")

    monkeypatch.setattr(jarvis, "speak_edge", quebra)
    monkeypatch.setattr(jarvis, "speak_sapi", lambda t: usados.append("sapi"))
    monkeypatch.setitem(jarvis.CFG, "tts_engine", "edge")
    jarvis.speak("Ola, senhor.")
    assert usados == ["sapi"]


# ------------------------------------------------------------------ aproximar a voz reserva da principal
def _fala_com_pausas(sr=SR):
    voz = np.sin(2 * np.pi * 150 * np.arange(int(sr * 0.3)) / sr).astype("float32") * 0.5
    sil = np.zeros(int(sr * 0.6), dtype="float32")
    return np.concatenate([sil, voz, sil, voz, sil])


def test_compactar_pausas_encurta_o_silencio_e_mantem_a_fala():
    a = _fala_com_pausas()
    b = jarvis.compactar_pausas(a, SR, 150)
    assert len(b) < len(a) - int(SR * 1.0)             # 3 silencios de 0,6 s viraram ~0,15 s cada
    assert abs(float(np.sum(np.abs(b))) - float(np.sum(np.abs(a)))) < 1e-3 * float(np.sum(np.abs(a)))  # nenhuma fala cortada


def test_compactar_pausas_desligado_ou_sem_silencio_nao_mexe():
    a = _fala_com_pausas()
    assert jarvis.compactar_pausas(a, SR, 0) is a
    so_fala = np.sin(np.arange(SR) / 7).astype("float32")
    assert len(jarvis.compactar_pausas(so_fala, SR, 100)) == len(so_fala)
    assert len(jarvis.compactar_pausas(np.zeros(0, "float32"), SR, 100)) == 0


def test_presenca_realca_o_que_esta_acima_de_600hz():
    t = np.arange(SR) / SR
    grave = np.sin(2 * np.pi * 100 * t).astype("float32") * 0.1
    agudo = np.sin(2 * np.pi * 3000 * t).astype("float32") * 0.1

    def ganho(x, p):
        y = jarvis.shape_voice(x, SR, 1.0, 0.0, 0.0, 0, presence=p)
        return float(np.sqrt(np.mean(y ** 2)) / np.sqrt(np.mean(x ** 2)))

    assert ganho(agudo, 0.5) > 1.3 * ganho(agudo, 0.0)
    assert ganho(grave, 0.5) < ganho(agudo, 0.5)        # o agudo ganha mais que o grave


def test_ajustes_do_edge_validam_o_formato(monkeypatch):
    monkeypatch.setitem(jarvis.CFG, "edge_rate", "+20%")
    monkeypatch.setitem(jarvis.CFG, "edge_pitch", "-5Hz")
    monkeypatch.setitem(jarvis.CFG, "edge_volume", "alto")      # invalido: ignorado
    assert jarvis.edge_ajustes() == {"rate": "+20%", "pitch": "-5Hz"}
    monkeypatch.setitem(jarvis.CFG, "edge_rate", "")
    monkeypatch.setitem(jarvis.CFG, "edge_pitch", None)
    assert jarvis.edge_ajustes() == {}


def test_edge_manda_os_ajustes_ao_servico_e_encurta_as_pausas(monkeypatch):
    visto = {}

    async def falso(frase, voz, prazo, **ajustes):
        visto.update(ajustes)
        return _wav(3.0)

    monkeypatch.setattr(jarvis, "_edge_mp3", falso)
    monkeypatch.setitem(jarvis.CFG, "edge_rate", "+20%")
    monkeypatch.setitem(jarvis.CFG, "edge_pitch", "+5Hz")
    monkeypatch.setitem(jarvis.CFG, "reserva_pausa_max_ms", 150)
    monkeypatch.setattr(jarvis, "_edge_pausa_ate", 0.0)
    jarvis._stop.clear()
    saidas = []
    monkeypatch.setattr(jarvis, "_falar_frases", lambda t, g: saidas.append(g("Tudo certo, senhor.")))
    jarvis.speak_edge("Tudo certo, senhor.")
    assert visto == {"rate": "+20%", "pitch": "+5Hz"}
    assert saidas and saidas[0][1] == SR
