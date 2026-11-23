"""Escolha de microfone/alto-falante (sem hardware): usa uma lista de dispositivos de exemplo, como a de um
notebook com fone sem fio, monitores por HDMI e a Steam."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_disp as ad  # noqa: E402

APIS = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]


def d(i, nome, entradas, saidas, api=0):
    return {"index": i, "name": nome, "max_input_channels": entradas, "max_output_channels": saidas, "hostapi": api}


DEVS = [
    d(0, "Mapeador de som da Microsoft - Input", 2, 0),
    d(1, "Microfone (4- HyperX Cloud Stinger Wireless)", 1, 0),
    d(2, "Grupo de microfones (Realtek(R) Audio)", 2, 0),
    d(3, "Microfone (Steam Streaming Microphone)", 8, 0),
    d(4, "Mapeador de som da Microsoft - Output", 0, 2),
    d(5, "Alto-falantes (Steam Streaming Speakers)", 0, 8),
    d(6, "Alto-falantes (4- HyperX Cloud Stinger Wireless)", 0, 2),
    d(7, "1 - MONITOR (AMD High Definition Audio Device)", 0, 2),
    d(8, "Alto-falantes (Realtek(R) Audio)", 0, 2),
    d(9, "Monitor (NVIDIA High Definition Audio)", 0, 2),
    d(12, "Microfone (4- HyperX Cloud Stinger Wireless)", 1, 0, api=1),
    d(13, "Grupo de microfones (Realtek(R) Audio)", 2, 0, api=1),
    d(19, "Alto-falantes (Realtek(R) Audio)", 0, 2, api=1),
]


def nome(i):
    return next(x["name"] for x in DEVS if x["index"] == i)


def test_notebook_pega_o_som_interno_e_ignora_fone_monitor_e_virtuais():
    assert nome(ad.escolher(DEVS, ad.ENTRADA, "notebook", 1, APIS)) == "Grupo de microfones (Realtek(R) Audio)"
    assert nome(ad.escolher(DEVS, ad.SAIDA, "notebook", 5, APIS)) == "Alto-falantes (Realtek(R) Audio)"
    assert ad.escolher(DEVS, ad.SAIDA, "notebook", 5, APIS) == 8                      # API MME, nao a DirectSound (19)


def test_auto_pula_dispositivo_virtual_mas_respeita_um_padrao_real():
    assert ad.escolher(DEVS, ad.SAIDA, None, 5, APIS) == 8                            # padrao = Steam (virtual) -> notebook
    assert ad.escolher(DEVS, ad.SAIDA, "auto", 6, APIS) == 6                          # padrao = fone real -> segue o Windows
    assert ad.escolher(DEVS, ad.ENTRADA, "", 2, APIS) == 2


def test_auto_acompanha_o_headset_quando_ele_e_o_padrao_e_volta_ao_notebook_sem_ele():
    # com o headset conectado o Windows o torna padrao (entrada e saida): o Jarvis vai junto
    assert ad.escolher(DEVS, ad.ENTRADA, "auto", 1, APIS) == 1 and ad.escolher(DEVS, ad.SAIDA, "auto", 6, APIS) == 6
    # sem headset o padrao do Windows e o som do notebook: tambem vai junto
    sem_fone = [x for x in DEVS if "HyperX" not in x["name"]]
    assert ad.escolher(sem_fone, ad.ENTRADA, "auto", 2, APIS) == 2 and ad.escolher(sem_fone, ad.SAIDA, "auto", 8, APIS) == 8
    # padrao sumiu junto com o headset (indice antigo): cai no notebook
    assert ad.escolher(sem_fone, ad.SAIDA, "auto", 6, APIS) == 8 and ad.escolher(sem_fone, ad.ENTRADA, "auto", 1, APIS) == 2


def test_auto_pula_caixa_de_monitor_como_saida_padrao():
    assert ad.escolher(DEVS, ad.SAIDA, "auto", 7, APIS) == 8                          # padrao = monitor AMD (HDMI): usa o notebook
    assert ad.escolher(DEVS, ad.SAIDA, "auto", 9, APIS) == 8                          # padrao = monitor NVIDIA


def test_nome_ou_indice_explicito():
    assert ad.escolher(DEVS, ad.ENTRADA, "hyperx", 2, APIS) == 1
    assert ad.escolher(DEVS, ad.SAIDA, "REALTEK", None, APIS) == 8                    # sem diferenciar maiusculas
    assert ad.escolher(DEVS, ad.ENTRADA, 2, None, APIS) == 2
    assert ad.escolher(DEVS, ad.ENTRADA, 999, 2, APIS) == 2                           # indice que sumiu: automatico


def test_fone_desligado_cai_no_notebook_sem_quebrar():
    sem_fone = [x for x in DEVS if "HyperX" not in x["name"]]
    assert ad.escolher(sem_fone, ad.ENTRADA, "hyperx", 1, APIS) == 2                  # nome nao existe mais: notebook
    assert ad.escolher(sem_fone, ad.ENTRADA, None, 1, APIS) == 2                      # padrao antigo (1) nao existe mais
    assert ad.escolher(sem_fone, ad.SAIDA, None, 6, APIS) == 8


def test_candidatos_tem_reserva_e_terminam_no_padrao():
    c = ad.candidatos(DEVS, ad.SAIDA, "hyperx", 5, APIS)
    assert c == [6, 8, None]
    assert ad.candidatos(DEVS, ad.SAIDA, "notebook", 5, APIS) == [8, None]


def test_sem_nenhum_dispositivo_devolve_none():
    assert ad.escolher([], ad.ENTRADA, "notebook", None, APIS) is None
    assert ad.candidatos([], ad.SAIDA, None, None, APIS) == [None]


def test_so_entradas_para_entrada_e_so_saidas_para_saida():
    assert all(DEVS[i]["max_input_channels"] > 0 for i in range(len(DEVS)) if DEVS[i]["index"] == ad.escolher(DEVS, ad.ENTRADA, "notebook", None, APIS))
    assert ad.escolher([x for x in DEVS if x["max_output_channels"] == 0], ad.SAIDA, "notebook", None, APIS) is None


def test_saida_de_monitor_nao_e_notebook():
    so_monitor = [x for x in DEVS if "AMD" in x["name"] or "NVIDIA" in x["name"]]
    assert ad.do_notebook(so_monitor, ad.SAIDA, APIS) is None
