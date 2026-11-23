"""Escolha do microfone e do alto-falante (puro: recebe a lista de dispositivos, nao toca em hardware).

Valores aceitos em `mic_device` e `speaker_device` do config.json:
  null / "auto"   segue o padrao do Windows, mas pula dispositivos virtuais (Steam Streaming, cabos virtuais...)
                  e, se nao houver um bom padrao, usa o microfone/alto-falante do proprio notebook;
  "notebook"      sempre o do notebook (som interno, tipicamente Realtek), sem fone;
  "<trecho>"      o primeiro dispositivo cujo nome contem o trecho (ex.: "HyperX");
  <numero>        o indice do dispositivo (muda quando se liga/desliga algo: prefira o nome).
Se o escolhido nao existir ou falhar ao abrir, o Jarvis tenta o do notebook e depois o padrao do Windows.
"""
from __future__ import annotations

ENTRADA, SAIDA = "entrada", "saida"
_CANAIS = {ENTRADA: "max_input_channels", SAIDA: "max_output_channels"}

VIRTUAIS = ("steam streaming", "virtual", "cable", "voicemeeter", "vb-audio", "oculus", "sunshine", "mapeador", "mapper",
            "mixagem", "stereo mix", "driver de captura", "driver de som")
# saidas de monitor (HDMI/DisplayPort) e acessorios externos: nunca contam como "o do notebook"
NAO_NOTEBOOK = ("nvidia", "amd high definition", "hdmi", "displayport", "display audio", "hyperx", "bluetooth",
                "hands-free", "headset", "usb", "steam", "virtual")
INTERNOS = ("realtek", "smart sound", "conexant", "synaptics", "cirrus", "internal", "interno", "embutid", "built-in",
            "microphone array", "array de microfones", "grupo de microfones")
MONITORES = ("nvidia", "amd high definition", "hdmi", "displayport", "display audio")
APELIDOS_NOTEBOOK = {"notebook", "interno", "embutido", "laptop", "builtin", "built-in"}


def _tem(nome: str, termos: tuple[str, ...]) -> bool:
    n = nome.lower()
    return any(t in n for t in termos)


def e_virtual(nome: str) -> bool:
    return _tem(nome, VIRTUAIS)


def e_do_notebook(nome: str) -> bool:
    return _tem(nome, INTERNOS) and not _tem(nome, NAO_NOTEBOOK) and not e_virtual(nome)


def validos(dispositivos: list[dict], tipo: str, apis: list[dict] | None = None) -> list[dict]:
    """Dispositivos com canais do tipo pedido; se houver da API 'MME' (a mais compativel: converte a taxa), so eles."""
    cand = [d for d in dispositivos if d.get(_CANAIS[tipo], 0) > 0]
    if apis:
        mme = {i for i, a in enumerate(apis) if str(a.get("name", "")).upper() == "MME"}
        so_mme = [d for d in cand if d.get("hostapi") in mme]
        if so_mme:
            return so_mme
    return cand


def do_notebook(dispositivos: list[dict], tipo: str, apis: list[dict] | None = None) -> int | None:
    for d in validos(dispositivos, tipo, apis):
        if e_do_notebook(d["name"]):
            return d["index"]
    return None


def escolher(dispositivos: list[dict], tipo: str, preferencia, padrao: int | None = None,
             apis: list[dict] | None = None) -> int | None:
    """Indice do dispositivo a usar, ou None = deixar o PortAudio usar o padrao.
    `padrao` e o indice padrao atual do sistema (pode ser None ou ja nao existir)."""
    cand = validos(dispositivos, tipo, apis)
    todos_por_indice = {d["index"]: d for d in dispositivos if d.get(_CANAIS[tipo], 0) > 0}

    if isinstance(preferencia, bool):
        preferencia = None
    if isinstance(preferencia, int):
        return preferencia if preferencia in todos_por_indice else escolher(dispositivos, tipo, None, padrao, apis)
    pref = str(preferencia or "").strip().lower()

    if pref in APELIDOS_NOTEBOOK:
        n = do_notebook(dispositivos, tipo, apis)
        return n if n is not None else escolher(dispositivos, tipo, None, padrao, apis)
    if pref and pref != "auto":
        for d in cand:
            if pref in d["name"].lower():
                return d["index"]
        for d in dispositivos:  # nao achou na API preferida: tenta nas outras
            if d.get(_CANAIS[tipo], 0) > 0 and pref in d["name"].lower():
                return d["index"]
        # nome nao encontrado (fone desligado?): cai no automatico

    # Automatico = acompanha o padrao do Windows (o fone/headset vira o padrao ao ser conectado e, ao sair, volta o
    # som do notebook). Pula so o que nao serve de verdade: dispositivo virtual e, na saida, caixa de monitor (HDMI).
    d = todos_por_indice.get(padrao) if padrao is not None else None
    if d is not None and not e_virtual(d["name"]) and not (tipo == SAIDA and _tem(d["name"], MONITORES)):
        return d["index"]
    n = do_notebook(dispositivos, tipo, apis)
    if n is not None:
        return n
    return d["index"] if d is not None else None


def candidatos(dispositivos: list[dict], tipo: str, preferencia, padrao: int | None = None,
               apis: list[dict] | None = None) -> list[int | None]:
    """Ordem de tentativa: o escolhido, o do notebook e, por fim, None (padrao do PortAudio)."""
    ordem: list[int | None] = []
    for c in (escolher(dispositivos, tipo, preferencia, padrao, apis), do_notebook(dispositivos, tipo, apis), None):
        if c not in ordem:
            ordem.append(c)
    return ordem
