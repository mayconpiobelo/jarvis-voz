"""Funcoes puras do jarvis.py: atalho, confirmacao por voz, preparo do texto para fala, config."""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import jarvis  # noqa: E402


# ---- atalho global
def test_atalho_valido():
    assert jarvis.parse_hotkey("ctrl+alt+j") == (0x4000 | 0x2 | 0x1, 0x4A)
    assert jarvis.parse_hotkey("Ctrl+Shift+F9") == (0x4000 | 0x2 | 0x4, 0x78)


@pytest.mark.parametrize("ruim", ["j", "ctrl+", "ctrl+alt", "ctrl+alt+???", ""])
def test_atalho_invalido(ruim):
    with pytest.raises(ValueError):
        jarvis.parse_hotkey(ruim)


# ---- confirmacao por voz
@pytest.mark.parametrize("frase,esperado", [
    ("sim", "sim"), ("Sim, confirma.", "sim"), ("pode", "sim"), ("confirmo", "sim"), ("Ok, manda", "sim"),
    ("não", "nao"), ("Não, deixa para lá", "nao"), ("cancela", "nao"),
    ("sim, mas cancela", "nao"),                      # qualquer negacao vence: lado seguro
    ("quero saber a previsão do tempo para amanhã em são paulo", None),   # longa demais para ser confirmacao
    ("qual a capital da França", None),
    ("", None),
])
def test_classificar_confirmacao(frase, esperado):
    assert jarvis.classify_confirmation(frase) == esperado


def test_detecta_pedido_de_confirmacao():
    assert jarvis.asks_confirmation("Vou enviar o e-mail ao cliente com o resumo. Confirma, senhor?")
    assert not jarvis.asks_confirmation("Pronto, senhor. O e-mail foi enviado.")


# ---- texto para fala
def test_limpa_markdown_links_e_codigo():
    t = jarvis.clean_for_speech("## Titulo\n**negrito** e [link](https://x.com) https://y.com\n```py\nprint(1)\n```\n- item")
    assert "http" not in t and "**" not in t and "```" not in t and "print" not in t and "#" not in t
    assert "negrito" in t and "link" in t and "item" in t


def test_resposta_longa_e_cortada_com_aviso():
    longa = ". ".join(f"Esta é a frase número {i} da resposta" for i in range(80)) + "."
    t = jarvis.clean_for_speech(longa)
    assert len(t) < len(longa) and t.endswith("O restante esta salvo no arquivo.")


def test_dividir_frases_preserva_o_texto_e_encurta_o_primeiro_trecho():
    texto = ("São 8 pastas, senhor: dbs-scout é a ferramenta de engenharia com visualizador e simulador; "
             "outra guarda um pacote compactado de distribuição dessa ferramenta; a financeira é o sistema da empresa. Fim.")
    partes = jarvis.split_sentences(texto)
    assert " ".join(partes) == re.sub(r"\s+", " ", texto)
    # a fala comeca antes de gerar a frase inteira (pedacos < 25 caracteres sao juntados ao seguinte)
    assert len(partes[0]) <= 100 < len(texto) and len(partes) >= 3


def test_envelope_de_volume_fica_entre_0_e_1():
    sr = 24000
    onda = (np.sin(np.linspace(0, 400 * np.pi, sr)) * np.linspace(0.1, 1, sr)).astype(np.float32)
    env = jarvis.frame_envelope(onda, sr)
    assert env.min() >= 0 and env.max() <= 1 and abs(len(env) - 25) <= 1
    assert jarvis.frame_envelope(np.zeros(10, dtype=np.float32), sr).shape == (1,)


# ---- ferramentas e config
def test_nomes_amigaveis_das_ferramentas():
    assert jarvis.tool_label("mcp__claude_ai_Microsoft_365__outlook_email_search") == "Buscando e-mails"
    assert jarvis.tool_label("Bash") == "Executando comando"
    assert jarvis.tool_label("mcp__x__fazer_coisa") == "Usando fazer coisa"


def test_expande_variaveis_nos_caminhos(monkeypatch):
    monkeypatch.setenv("USERPROFILE", "C:\\Teste")
    assert jarvis.expand_path("%USERPROFILE%\\a") in ("C:\\Teste\\a", "%USERPROFILE%\\a")  # Windows expande; outros SO nao


def test_config_de_exemplo_e_valida_e_completa():
    ex = json.loads((RAIZ / "config.example.json").read_text(encoding="utf-8"))
    for chave in ("hotkey", "claude_exe", "workdir", "permission_mode", "confirm_by_voice", "persona",
                  "deny_always", "deny_outward", "tts_engine", "kokoro_voice", "overlay", "tarefas", "owner_name"):
        assert chave in ex, chave
    assert "{dono}" in ex["persona"]
    assert ex["allow_outward_actions"] is False and ex["confirm_by_voice"] is True   # padrao seguro
    assert not any("outlook_send" in x for x in ex["deny_always"])                    # envio e CONFIRMAVEL, nao permanente
    assert any("delete" in x.lower() or "rm" in x for x in ex["deny_always"])         # destrutivo e permanente
