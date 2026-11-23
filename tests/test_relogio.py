import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import relogio  # noqa: E402

SEG = datetime(2026, 11, 23, 15, 40)  # segunda-feira


@pytest.mark.parametrize("fala,esperado", [
    ("Que horas são?", "São 15 horas e 40 minutos, senhor."),
    ("jarvis, que horas são agora", "São 15 horas e 40 minutos, senhor."),
    ("Me diga as horas", "São 15 horas e 40 minutos, senhor."),
    ("qual a hora certa", "São 15 horas e 40 minutos, senhor."),
    ("Que dia é hoje?", "Hoje é segunda-feira, 23 de novembro de 2026, senhor."),
    ("qual a data de hoje", "Hoje é segunda-feira, 23 de novembro de 2026, senhor."),
    ("em que dia estamos", "Hoje é segunda-feira, 23 de novembro de 2026, senhor."),
])
def test_responde_hora_e_data(fala, esperado):
    assert relogio.responder(fala, SEG) == esperado


@pytest.mark.parametrize("fala", [
    "que horas é a reunião com a ISA hoje",          # pergunta sobre agenda: segue para o Claude
    "que dia é a minha viagem",
    "qual a previsão do tempo hoje",
    "me lembra daqui a uma hora",
    "marca uma reunião para as 15 horas",
    "",
])
def test_nao_intercepta_perguntas_que_precisam_do_claude(fala):
    assert relogio.responder(fala, SEG) is None


def test_formas_especiais_da_hora():
    assert relogio.fala_hora(datetime(2026, 1, 1, 1, 0)) == "É uma hora em ponto, senhor."
    assert relogio.fala_hora(datetime(2026, 1, 1, 1, 1)) == "É uma hora e 1 minuto, senhor."
    assert relogio.fala_hora(datetime(2026, 1, 1, 9, 0)) == "São 9 horas em ponto, senhor."
    assert relogio.fala_hora(datetime(2026, 1, 1, 0, 0)) == "É meia-noite em ponto, senhor."
    assert relogio.fala_hora(datetime(2026, 1, 1, 0, 5)) == "É meia-noite e 5 minutos, senhor."
