"""Testes da lista de tarefas (sem microfone, sem Claude, sem rede)."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tarefas  # noqa: E402

HOJE = datetime(2026, 11, 23, 9, 0)  # segunda-feira


@pytest.fixture()
def lista(tmp_path):
    return tarefas.Tarefas(tmp_path / "tarefas.json", tmp_path / "TAREFAS.md", agora=lambda: HOJE)


def falar(lista, frase):
    return tarefas.responder(frase, lista)


# ---- o comando do exemplo
def test_exemplo_do_usuario(lista):
    r = falar(lista, "Jarvis insira: atualizar workload geral na lista de tarefas")
    assert r == "Anotado, senhor: atualizar workload geral."
    ab = lista.abertas()
    assert [t["texto"] for t in ab] == ["atualizar workload geral"]
    assert ab[0]["origem"] == "voz" and ab[0]["status"] == "aberta"


@pytest.mark.parametrize("frase", [
    "Jarvis, insira atualizar workload geral na lista de tarefas.",
    "insira: atualizar workload geral",
    "Jarvis anote atualizar workload geral",
    "adicione atualizar workload geral na lista de tarefas",
    "crie uma tarefa: atualizar workload geral",
    "por favor, adicione na lista de tarefas: atualizar workload geral",
])
def test_variacoes_de_adicionar(lista, frase):
    assert falar(lista, frase).startswith("Anotado, senhor: atualizar workload geral")
    assert len(lista.abertas()) == 1


@pytest.mark.parametrize("frase", [
    "crie um rascunho de e-mail para o cliente",
    "adicione um evento na agenda amanhã",
    "coloque a música para tocar",
    "registre o ponto de hoje",
    "qual é a capital da França",
])
def test_pedidos_que_nao_sao_tarefas_seguem_para_o_claude(lista, frase):
    assert falar(lista, frase) is None
    assert lista.abertas() == []


@pytest.mark.parametrize("frase", [
    "crie duas tarefas: revisar contrato e ligar para o fornecedor",
    "adicione 3 tarefas na lista: A, B e C",
    "insira as tarefas da semana: revisar escopo, atualizar workload",
    "anote " + "um texto muito longo ditado como paragrafo " * 8,
])
def test_varias_tarefas_ou_paragrafo_vao_para_o_claude(lista, frase):
    assert falar(lista, frase) is None
    assert lista.abertas() == []


def test_nao_duplica(lista):
    falar(lista, "insira: revisar contrato")
    r = falar(lista, "Jarvis insira revisar contrato na lista de tarefas")
    assert r.startswith("Já consta na lista")
    assert len(lista.abertas()) == 1


def test_adicionar_sem_texto_pergunta(lista):
    assert falar(lista, "insira na lista de tarefas") == "Qual é a tarefa, senhor?"
    assert falar(lista, "Jarvis, insira:") == "Qual é a tarefa, senhor?"
    assert lista.abertas() == []


# ---- prazo e prioridade
def test_prazos(lista):
    assert "para amanhã" in falar(lista, "insira enviar relatório para amanhã")
    assert lista.abertas()[0]["prazo"] == "2026-11-24"
    falar(lista, "insira pagar boleto para sexta")
    assert [t["prazo"] for t in lista.todas() if t["texto"] == "pagar boleto"] == ["2026-11-27"]
    falar(lista, "anote ligar para o fornecedor para o dia 5")
    assert [t["prazo"] for t in lista.todas() if t["texto"].startswith("ligar")] == ["2026-12-05"]
    falar(lista, "anote fechar o mês para hoje")
    assert [t["prazo"] for t in lista.todas() if t["texto"].startswith("fechar")] == ["2026-11-23"]


def test_segunda_para_segunda_vai_para_a_proxima(lista):
    falar(lista, "anote revisar escopo para segunda")  # hoje e segunda: proxima segunda
    assert lista.abertas()[0]["prazo"] == "2026-11-30"


def test_prioridade_urgente_vem_primeiro(lista):
    falar(lista, "anote tarefa comum")
    falar(lista, "anote ligar para o cliente urgente")
    ab = lista.abertas()
    assert ab[0]["texto"] == "ligar para o cliente" and ab[0]["prioridade"] == "alta"


# ---- listar
def test_listar_vazia_e_com_itens(lista):
    assert falar(lista, "quais são as minhas tarefas") == "A sua lista está vazia, senhor."
    falar(lista, "insira: primeira coisa")
    falar(lista, "insira: segunda coisa")
    r = falar(lista, "liste minhas tarefas")
    assert r.startswith("Senhor, são 2 tarefas abertas.") and "primeira coisa" in r


def test_listar_limita_a_cinco(lista):
    for i in range(7):
        falar(lista, f"insira: item {i}")
    r = falar(lista, "o que tenho pendente")
    assert "E mais 2." in r


# ---- concluir / remover / desfazer
def test_concluir_por_numero_e_por_trecho(lista):
    for x in ("atualizar workload geral", "revisar contrato", "pagar boleto"):
        falar(lista, f"insira: {x}")
    assert falar(lista, "conclua a tarefa 2").startswith("Concluída, senhor:")
    assert len(lista.abertas()) == 2
    assert falar(lista, "Jarvis, conclua a tarefa do workload").startswith("Concluída, senhor: atualizar workload")
    assert [t["texto"] for t in lista.abertas()] == ["pagar boleto"]
    assert [t["texto"] for t in lista.recentes_concluidas()]


def test_concluir_por_palavra_numerica(lista):
    falar(lista, "insira: alfa"); falar(lista, "insira: beta")
    assert falar(lista, "marque como feita a segunda tarefa").startswith("Concluída")
    assert len(lista.abertas()) == 1


def test_referencia_ambigua(lista):
    falar(lista, "insira: revisar contrato A"); falar(lista, "insira: revisar contrato B")
    r = falar(lista, "conclua a tarefa revisar contrato")
    assert r.startswith("Encontrei mais de uma")
    assert len(lista.abertas()) == 2


def test_nao_encontrada(lista):
    falar(lista, "insira: alfa")
    assert falar(lista, "conclua a tarefa zeta quimica") == "Não encontrei essa tarefa, senhor."
    assert falar(lista, "remova o relatório mensal") is None  # sem a palavra tarefa: pode ser outro pedido


def test_remover_e_desfazer(lista):
    falar(lista, "insira: alfa"); falar(lista, "insira: beta")
    assert falar(lista, "remova a tarefa 1").startswith("Removida, senhor:")
    assert [t["texto"] for t in lista.abertas()] == ["beta"]
    assert any(t["status"] == "removida" for t in lista.todas())   # exclusao suave: nada se perde
    assert falar(lista, "desfazer a última alteração") == "Desfeito, senhor."
    assert len(lista.abertas()) == 2
    assert falar(lista, "desfaça") in ("Desfeito, senhor.", "Não há nada para desfazer, senhor.")


# ---- armazenamento
def test_ids_estaveis_e_persistencia(lista, tmp_path):
    a, _ = lista.adicionar("um"); b, _ = lista.adicionar("dois")
    assert (a["id"], b["id"]) == (1, 2)
    lista.concluir(a)
    outra = tarefas.Tarefas(tmp_path / "tarefas.json")
    assert [t["id"] for t in outra.abertas()] == [2]
    c, _ = outra.adicionar("tres")
    assert c["id"] == 3  # nao reutiliza ids


def test_arquivo_corrompido_nao_derruba(tmp_path):
    f = tmp_path / "tarefas.json"; f.write_text("{ isso nao e json", encoding="utf-8")
    t = tarefas.Tarefas(f)
    assert t.abertas() == []
    t.adicionar("recomecar")
    assert len(t.abertas()) == 1


def test_markdown_gerado(lista, tmp_path):
    falar(lista, "insira: atualizar workload geral para amanhã")
    md = (tmp_path / "TAREFAS.md").read_text(encoding="utf-8")
    assert "- [ ] 1. atualizar workload geral" in md and "2026-11-24" in md


def test_painel_texto_livre_vira_tarefa_com_prazo_e_prioridade(lista):
    msg, mudou, pergunta = tarefas.entrada_do_painel(lista, "revisar contrato para sexta urgente")
    assert mudou and not pergunta and msg.startswith("Anotado: revisar contrato")
    t = lista.abertas()[0]
    assert t["prazo"] == "2026-11-27" and t["prioridade"] == "alta" and t["origem"] == "painel"


def test_painel_aceita_comandos_digitados(lista):
    tarefas.entrada_do_painel(lista, "alfa")
    tarefas.entrada_do_painel(lista, "beta")
    msg, mudou, _ = tarefas.entrada_do_painel(lista, "conclua a tarefa 1")
    assert mudou and msg.startswith("Concluída, senhor:")
    assert [t["texto"] for t in lista.abertas()] == ["beta"]
    assert tarefas.entrada_do_painel(lista, "   ") == (None, False, False)
    assert tarefas.entrada_do_painel(lista, "beta")[1] is False       # duplicada nao cria


# ---- "para quando?": opcional, na voz e no painel
@pytest.fixture()
def lista_pergunta(tmp_path):
    relogio = {"agora": HOJE}
    lst = tarefas.Tarefas(tmp_path / "tarefas.json", agora=lambda: relogio["agora"], perguntar_prazo=True)
    lst.relogio = relogio
    return lst


def test_voz_sem_data_pergunta_para_quando_e_aceita_a_resposta(lista_pergunta):
    r = falar(lista_pergunta, "Jarvis insira: atualizar workload geral na lista de tarefas")
    assert r.startswith("Anotado, senhor: atualizar workload geral.") and "Para quando?" in r
    assert tarefas.responder_prazo("sexta", lista_pergunta) == "Combinado, senhor: atualizar workload geral, para sexta."
    assert lista_pergunta.abertas()[0]["prazo"] == "2026-11-27"
    assert lista_pergunta.pendente_prazo is None


def test_voz_com_data_na_frase_nao_pergunta(lista_pergunta):
    r = falar(lista_pergunta, "insira: revisar contrato para amanhã")
    assert "Para quando?" not in r and lista_pergunta.pendente_prazo is None


def test_resposta_sem_data_deixa_a_tarefa_sem_prazo(lista_pergunta):
    falar(lista_pergunta, "anote: ligar para o fornecedor")
    assert tarefas.responder_prazo("sem data", lista_pergunta) == "Certo, senhor, sem data."
    assert lista_pergunta.abertas()[0]["prazo"] is None


def test_outra_fala_cancela_a_pergunta_e_segue_o_fluxo_normal(lista_pergunta):
    falar(lista_pergunta, "anote: ligar para o fornecedor")
    assert tarefas.responder_prazo("qual a previsão do tempo", lista_pergunta) is None   # nao e data: vai para o resto
    assert lista_pergunta.pendente_prazo is None
    assert tarefas.responder_prazo("amanhã", lista_pergunta) is None                      # a pergunta valia uma fala so
    assert lista_pergunta.abertas()[0]["prazo"] is None


def test_pergunta_expira(lista_pergunta):
    falar(lista_pergunta, "anote: ligar para o fornecedor")
    lista_pergunta.relogio["agora"] = HOJE + tarefas.timedelta(seconds=tarefas.PERGUNTA_PRAZO_TTL + 5)
    assert tarefas.responder_prazo("amanhã", lista_pergunta) is None
    assert lista_pergunta.abertas()[0]["prazo"] is None


def test_pergunta_desligada_por_config(lista):  # `lista` usa perguntar_prazo=False
    assert "Para quando?" not in falar(lista, "anote: ligar para o fornecedor")


def test_nao_pergunta_em_tarefa_repetida(lista_pergunta):
    falar(lista_pergunta, "anote: ligar para o fornecedor")
    lista_pergunta.pendente_prazo = None
    assert "Já consta" in falar(lista_pergunta, "anote: ligar para o fornecedor")
    assert lista_pergunta.pendente_prazo is None


@pytest.mark.parametrize("fala,esperado", [
    ("amanhã", ("data", "2026-11-24")), ("Para sexta-feira.", ("data", "2026-11-27")), ("dia 25", ("data", "2026-11-25")),
    ("25", ("data", "2026-11-25")), ("25 de dezembro", ("data", "2026-12-25")), ("25/12", ("data", "2026-12-25")),
    ("05/03/27", ("data", "2027-03-05")), ("semana que vem", ("data", "2026-11-30")),
    ("daqui a 3 dias", ("data", "2026-11-26")), ("em duas semanas", ("data", "2026-12-07")), ("depois de amanhã", ("data", "2026-11-25")),
    ("sem data", ("sem", None)), ("não precisa", ("sem", None)), ("tanto faz", ("sem", None)),
    ("qual a previsão do tempo", None), ("abre o spotify e toca algo legal", None), ("", None), ("31/02", None),
])
def test_interpretar_prazo(fala, esperado):
    assert tarefas.interpretar_prazo(fala, HOJE.date()) == esperado


def test_datas_numericas_e_por_extenso_na_frase():
    h = HOJE.date()
    assert tarefas.extrair_prazo_prioridade("revisar contrato para 25/12", h)[:2] == ("revisar contrato", "2026-12-25")
    assert tarefas.extrair_prazo_prioridade("ligar para dia 25 de dezembro urgente", h) == ("ligar", "2026-12-25", "alta")
    assert tarefas.extrair_prazo_prioridade("planejar para semana que vem", h)[:2] == ("planejar", "2026-11-30")
    assert tarefas.extrair_prazo_prioridade("pagar boleto para dia 25", h)[1] == "2026-11-25"


def test_painel_pergunta_prazo_e_nao_cria_ate_escolher(lista_pergunta):
    assert tarefas.entrada_do_painel(lista_pergunta, "comprar pão") == (None, False, True)
    assert lista_pergunta.abertas() == []                                                  # nada criado ainda
    msg, mudou, pergunta = tarefas.entrada_do_painel(lista_pergunta, "comprar pão", prazo="2026-11-25")
    assert mudou and not pergunta and lista_pergunta.abertas()[0]["prazo"] == "2026-11-25"


def test_painel_sem_data_e_opcional(lista_pergunta):
    msg, mudou, pergunta = tarefas.entrada_do_painel(lista_pergunta, "comprar pão", prazo="")
    assert mudou and not pergunta and lista_pergunta.abertas()[0]["prazo"] is None


def test_painel_nao_pergunta_se_o_texto_ja_tem_data_ou_e_comando(lista_pergunta):
    assert tarefas.entrada_do_painel(lista_pergunta, "comprar pão para sexta")[2] is False
    assert tarefas.entrada_do_painel(lista_pergunta, "anote: ligar fornecedor para amanhã")[2] is False
    assert tarefas.entrada_do_painel(lista_pergunta, "conclua a tarefa 1")[2] is False
    assert tarefas.entrada_do_painel(lista_pergunta, "desfazer")[2] is False


def test_painel_anote_digitado_pergunta_o_prazo_sem_criar_pela_voz(lista_pergunta):
    assert tarefas.entrada_do_painel(lista_pergunta, "anote: comprar pão") == (None, False, True)
    assert lista_pergunta.pendente_prazo is None                                           # pergunta do painel nao e a da voz


def test_definir_prazo_e_cli(tmp_path, monkeypatch, capsys):
    lst = tarefas.Tarefas(tmp_path / "t.json", agora=lambda: HOJE)
    monkeypatch.setattr(tarefas, "lista_padrao", lambda: lst)
    t, _ = lst.adicionar("revisar contrato")
    assert lst.definir_prazo(t["id"], "2026-12-01")["prazo"] == "2026-12-01"
    assert lst.definir_prazo(999, "2026-12-01") is None
    assert tarefas.main(["prazo", "contrato", "nenhum"]) == 0 and lst.abertas()[0]["prazo"] is None
    assert tarefas.main(["prazo", "contrato", "2026-12-05"]) == 0 and lst.abertas()[0]["prazo"] == "2026-12-05"
    with pytest.raises(ValueError):
        lst.definir_prazo(t["id"], "31/12/2026")


def test_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tarefas, "lista_padrao", lambda: tarefas.Tarefas(tmp_path / "t.json", agora=lambda: HOJE))
    assert tarefas.main(["add", "teste pela cli", "--prazo", "2026-12-01", "--prio", "alta"]) == 0
    assert tarefas.main(["list"]) == 0
    assert "teste pela cli" in capsys.readouterr().out
    assert tarefas.main(["done", "cli"]) == 0
    assert tarefas.main(["done", "inexistente"]) == 1
    with pytest.raises(ValueError):
        tarefas.main(["add", "x", "--prazo", "31/12/2026"])
