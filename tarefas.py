#!/usr/bin/env python3
"""Lista de tarefas do Jarvis.

Fonte da verdade: tarefas.json (local, fora do git). Uma visao em Markdown (TAREFAS.md) e regravada a
cada alteracao, para abrir no Obsidian ou em qualquer editor (o caminho pode apontar para o seu cofre).

Tres formas de uso:
  1. Voz, resposta imediata e sem o Claude:  "Jarvis, insira: atualizar workload geral na lista de tarefas"
  2. Pedidos complexos por voz: o Claude usa este mesmo arquivo pela linha de comando abaixo.
  3. Linha de comando:
       python tarefas.py add "texto" [--prazo AAAA-MM-DD] [--prio alta|media|baixa] [--tag x]
       python tarefas.py list [--todas]      python tarefas.py done REF
       python tarefas.py remove REF          python tarefas.py undo       python tarefas.py md
       python tarefas.py prazo REF AAAA-MM-DD|nenhum     (define ou limpa o prazo de uma tarefa)
     REF = numero na lista de abertas (como o Jarvis fala) ou um trecho do texto da tarefa.

So usa a biblioteca padrao do Python.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

BASE = Path(__file__).resolve().parent
PRIO_ORDEM = {"alta": 0, "media": 1, "baixa": 2}
DIAS_SEMANA = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
NOMES_DIA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
PERGUNTA_PRAZO_TTL = 60  # segundos que o Jarvis espera a resposta de "para quando?"
NUMEROS = {"um": 1, "uma": 1, "primeira": 1, "primeiro": 1, "dois": 2, "duas": 2, "segunda": 2, "segundo": 2,
           "tres": 3, "terceira": 3, "terceiro": 3, "quatro": 4, "quarta": 4, "quarto": 4, "cinco": 5,
           "quinta": 5, "quinto": 5, "seis": 6, "sexta": 6, "sexto": 6, "sete": 7, "setima": 7, "oito": 8,
           "oitava": 8, "nove": 9, "nona": 9, "dez": 10, "decima": 10}


def norm(texto: str) -> str:
    """minusculas, sem acentos nem pontuacao (para comparar)."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _limpa(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip(" \t\r\n.,;:!?-")


# ------------------------------------------------------------------ armazenamento
class Tarefas:
    def __init__(self, arquivo: Path, md: Path | None = None, agora: Callable[[], datetime] = datetime.now,
                 perguntar_prazo: bool = False):
        self.arquivo = Path(arquivo)
        self.md = Path(md) if md else None
        self.agora = agora
        self.perguntar_prazo = perguntar_prazo  # ao criar tarefa sem data, pergunta "para quando?" (opcional responder)
        self.pendente_prazo: tuple[int, datetime] | None = None  # (id da tarefa, ate quando aceita a resposta)

    # -- leitura/gravacao (atomica, com uma copia para "desfazer")
    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            if isinstance(dados, dict) and isinstance(dados.get("tarefas"), list):
                return dados
        except (OSError, ValueError):
            pass
        return {"versao": 1, "proximo_id": 1, "tarefas": []}

    def _gravar(self, dados: dict) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        if self.arquivo.exists():
            try:
                self.arquivo.replace(self.arquivo.with_suffix(".bak"))  # estado anterior (para desfazer)
            except OSError:
                pass
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.arquivo)
        self.escrever_md()

    # -- consultas
    def todas(self) -> list[dict]:
        return self._ler()["tarefas"]

    def abertas(self) -> list[dict]:
        """Ordem fixa usada na fala, na janela e nas referencias por numero."""
        ab = [t for t in self.todas() if t["status"] == "aberta"]
        return sorted(ab, key=lambda t: (PRIO_ORDEM.get(t.get("prioridade", "media"), 1), t.get("prazo") or "9999", t["id"]))

    def recentes_concluidas(self, n: int = 10) -> list[dict]:
        c = [t for t in self.todas() if t["status"] == "concluida"]
        return sorted(c, key=lambda t: t.get("concluida") or "", reverse=True)[:n]

    # -- alteracoes
    def adicionar(self, texto: str, prazo: str | None = None, prioridade: str = "media",
                  tags: tuple[str, ...] = (), origem: str = "voz") -> tuple[dict, bool]:
        """Devolve (tarefa, criada). Se ja existe uma aberta igual, nao duplica."""
        texto = _limpa(texto)
        dados = self._ler()
        for t in dados["tarefas"]:
            if t["status"] == "aberta" and norm(t["texto"]) == norm(texto):
                return t, False
        agora = self.agora().isoformat(timespec="seconds")
        t = {"id": dados["proximo_id"], "texto": texto, "status": "aberta",
             "prioridade": prioridade if prioridade in PRIO_ORDEM else "media", "prazo": prazo,
             "tags": list(tags), "criada": agora, "atualizada": agora, "concluida": None, "origem": origem}
        dados["proximo_id"] += 1
        dados["tarefas"].append(t)
        self._gravar(dados)
        return t, True

    def resolver(self, ref: str) -> list[dict]:
        """Numero (da lista de abertas), 'ultima' ou trecho do texto -> tarefas candidatas."""
        ab = self.abertas()
        r = norm(ref)
        if not r:
            return []
        if r in ("ultima", "ultimo", "a ultima"):
            return ab[-1:]
        m = re.fullmatch(r"(?:n |numero )?(\d+)", r)
        if m:
            i = int(m.group(1))
            return [ab[i - 1]] if 1 <= i <= len(ab) else []
        palavras = r.split()
        if len(palavras) == 2 and palavras[1] == "tarefa" and (palavras[0] in NUMEROS or palavras[0].isdigit()):
            palavras = palavras[:1]  # "segunda tarefa" / "2 tarefa"
            if palavras[0].isdigit():
                i = int(palavras[0])
                return [ab[i - 1]] if 1 <= i <= len(ab) else []
        if len(palavras) == 1 and palavras[0] in NUMEROS:
            i = NUMEROS[palavras[0]]
            return [ab[i - 1]] if 1 <= i <= len(ab) else []
        consulta = [p for p in palavras if len(p) > 2 and p not in ("tarefa", "lista", "para", "uma", "dos", "das")]
        if not consulta:
            return []
        melhor, cands = 0.0, []
        for t in ab:
            alvo = norm(t["texto"])
            pontos = sum(1 for p in consulta if p in alvo) / len(consulta)
            if pontos > melhor + 1e-9:
                melhor, cands = pontos, [t]
            elif abs(pontos - melhor) < 1e-9 and pontos > 0:
                cands.append(t)
        return cands if melhor >= 0.6 else []

    def _mudar(self, tarefa: dict, status: str) -> dict:
        dados = self._ler()
        for t in dados["tarefas"]:
            if t["id"] == tarefa["id"]:
                agora = self.agora().isoformat(timespec="seconds")
                t["status"], t["atualizada"] = status, agora
                t["concluida"] = agora if status == "concluida" else None
                self._gravar(dados)
                return t
        raise KeyError(tarefa["id"])

    def definir_prazo(self, tarefa_id: int, prazo: str | None) -> dict | None:
        """Define (AAAA-MM-DD) ou limpa (None) o prazo de uma tarefa aberta; None se ela nao existe mais."""
        if prazo:
            date.fromisoformat(prazo)
        dados = self._ler()
        for t in dados["tarefas"]:
            if t["id"] == tarefa_id and t["status"] == "aberta":
                t["prazo"], t["atualizada"] = prazo or None, self.agora().isoformat(timespec="seconds")
                self._gravar(dados)
                return t
        return None

    def concluir(self, tarefa: dict) -> dict:
        return self._mudar(tarefa, "concluida")

    def remover(self, tarefa: dict) -> dict:  # exclusao "suave": fica no arquivo, fora das listas
        return self._mudar(tarefa, "removida")

    def desfazer(self) -> bool:
        bak = self.arquivo.with_suffix(".bak")
        if not bak.exists():
            return False
        os.replace(bak, self.arquivo)
        self.escrever_md()
        return True

    # -- visao em Markdown
    def render_md(self) -> str:
        linhas = ["# Tarefas", "", f"_Gerado pelo Jarvis em {self.agora():%d/%m/%Y %H:%M}. Edite pelo Jarvis ou por tarefas.py._", ""]
        ab = self.abertas()
        linhas.append(f"## Abertas ({len(ab)})")
        for i, t in enumerate(ab, 1):
            extra = []
            if t.get("prioridade") == "alta":
                extra.append("🔴 alta")
            if t.get("prazo"):
                extra.append(f"📅 {t['prazo']}")
            extra += [f"#{x}" for x in t.get("tags", [])]
            linhas.append(f"- [ ] {i}. {t['texto']}" + (f"  ({', '.join(extra)})" if extra else ""))
        if not ab:
            linhas.append("_(nenhuma)_")
        conc = self.recentes_concluidas()
        linhas += ["", "## Concluídas recentemente"]
        linhas += [f"- [x] {t['texto']}  ({(t.get('concluida') or '')[:10]})" for t in conc] or ["_(nenhuma)_"]
        return "\n".join(linhas) + "\n"

    def escrever_md(self) -> None:
        if not self.md:
            return
        try:
            self.md.parent.mkdir(parents=True, exist_ok=True)
            self.md.write_text(self.render_md(), encoding="utf-8")
        except OSError:
            pass


# ------------------------------------------------------------------ interpretacao da fala
_PREF = r"^(?:jarvis\W+)?(?:por favor\W*)?"
_ADD = re.compile(_PREF + r"(?P<v>insira|insere|inserir|anote|anota|anotar|registre|registra|registrar|adicione|adiciona|"
                  r"adicionar|inclua|inclui|incluir|crie|cria|criar|coloque|coloca|colocar)\b[\s,:\-]*(?P<resto>.+)$", re.I | re.S)
_NOVA = re.compile(_PREF + r"(?:nova\s+tarefa|tarefa\s+nova)\b[\s,:\-]*(?P<resto>.+)$", re.I | re.S)
_DONE = re.compile(_PREF + r"(?P<v>conclua|conclui|concluir|finalize|finaliza|finalizar|risque|riscar|"
                   r"(?:marque|marcar|marca)\s+como\s+(?:feita|feito|conclu[ií]da|conclu[ií]do|pronta|pronto)|d[êe]\s+baixa(?:\s+(?:na|em))?)"
                   r"\b[\s,:\-]*(?P<ref>.+)$", re.I | re.S)
_PRONTO = r"(?:(?:pronto|ok|certo|feito)\W+)?"  # "pronto, terminei a tarefa..."
_FEITA = r"(?:feit[ao]|conclu[ií]d[ao]|pront[ao]|resolvid[ao]|finalizad[ao])"
_DONE_MARCA = re.compile(_PREF + _PRONTO + r"(?:marque|marcar|marca)\s+(?P<ref>.+?)\s+como\s+" + _FEITA + r"[\s.!?]*$", re.I | re.S)
_DONE_DE = re.compile(_PREF + _PRONTO + r"(?:d[êe]|dar|da)\s+como\s+" + _FEITA + r"\b[\s,:\-]*(?P<ref>.+)$", re.I | re.S)
# passado e sufixo so valem com a palavra "tarefa" (senao "ja fiz o almoco" viraria comando)
_DONE_PASSADO = re.compile(_PREF + _PRONTO + r"(?:j[áa]\s+)?(?:fiz|terminei|finalizei|conclu[ií]|completei)\s+"
                           r"(?P<ref>(?:a\s+|essa\s+|esta\s+)?tarefa\b.+)$", re.I | re.S)
_DONE_SUFIXO = re.compile(_PREF + _PRONTO + r"(?P<ref>(?:a\s+)?tarefa\s+.+?)\s+(?:(?:est[áa]|ficou)\s+)?" + _FEITA + r"[\s.!?]*$",
                          re.I | re.S)
_REM = re.compile(_PREF + r"(?P<v>remova|remove|remover|exclua|exclui|excluir|apague|apaga|apagar|delete|tire|tira|"
                  r"cancele|cancela)\b[\s,:\-]*(?P<ref>.+)$", re.I | re.S)
_UNDO = re.compile(_PREF + r"(?:desfa[çc]a|desfazer|desfaz)\b", re.I)
_LISTA = re.compile(_PREF + r"(?:liste|lista|leia|ler|mostre|mostra|quais|qual|me\s+diga|diga|o\s+que|como\s+est[aá])\b.*"
                    r"\b(?:tarefas?|pendentes?|pend[êe]ncias?|a\s+fazer|afazeres)\b", re.I | re.S)
_SUF_LISTA = re.compile(r"\s+(?:na|à|a|em|para\s+a|pra)\s+(?:minha\s+|nossa\s+)?(?:lista(?:\s+de\s+(?:tarefas|afazeres))?|tarefas)[\s.!?]*$", re.I)
_PRE_LISTA = re.compile(r"^(?:na|à|a)\s+(?:minha\s+|nossa\s+)?lista(?:\s+de\s+(?:tarefas|afazeres))?\s*[:,\-]?\s*", re.I)
_PLURAL = re.compile(r"^(?:\d+|duas|dois|tr[êe]s|quatro|cinco|seis|v[áa]rias|algumas|as|minhas|novas)\s+(?:novas\s+)?tarefas\b", re.I)
_FILLER = re.compile(r"^(?:a[ií]|ent[ãa]o)\s*[,:]?\s+", re.I)  # "anota ai comprar cafe"
_PRE_TAREFA = re.compile(r"^(?:uma\s+|a\s+|essa\s+|esta\s+)?(?:nova\s+)?tarefa\s*[:,\-]?\s*", re.I)


def extrair_prazo_prioridade(texto: str, hoje: date) -> tuple[str, str | None, str]:
    """Tira do texto 'para amanha', 'sexta', 'dia 25', 'urgente', 'prioridade alta'... -> (texto, prazo, prio)."""
    prazo, prio, t = None, "media", " " + texto + " "

    def tira(padrao: str) -> re.Match | None:
        nonlocal t
        m = re.search(padrao, t, re.I)
        if m:
            t = t[: m.start()] + " " + t[m.end():]
        return m

    if tira(r"\s(?:com\s+)?(?:prioridade\s+alta|alta\s+prioridade|urgente|urgentissimo)\b"):
        prio = "alta"
    elif tira(r"\s(?:com\s+)?(?:prioridade\s+baixa|baixa\s+prioridade)\b"):
        prio = "baixa"
    # datas por extenso/numericas e "semana que vem" (antes de "dia N", para "dia 25 de dezembro" nao virar "dia 25")
    m = tira(r"\s(?:para|pra|at[ée]|prazo)\s+(?:o\s+)?(?:dia\s+)?(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?(?!\d)")
    if m:
        prazo = _data_dm(int(m.group(1)), int(m.group(2)), m.group(3), hoje)
    else:
        m = tira(r"\s(?:para|pra|at[ée]|prazo)\s+(?:o\s+)?(?:dia\s+)?(\d{1,2})\s+de\s+"
                 r"(janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b")
        if m:
            prazo = _data_dm(int(m.group(1)), MESES[norm(m.group(2))], None, hoje)
        elif tira(r"\s(?:para|pra|at[ée]|prazo)\s+(?:a\s+)?(?:semana\s+que\s+vem|pr[óo]xima\s+semana)\b"):
            prazo = (hoje + timedelta(days=7 - hoje.weekday())).isoformat()  # segunda-feira da semana seguinte
    if prazo is None:
        m = tira(r"\s(?:para|pra|at[ée]|prazo)\s+(?:o\s+)?(depois\s+de\s+amanh[ãa]|amanh[ãa]|hoje)\b")
        if m:
            k = norm(m.group(1))
            prazo = (hoje + timedelta(days={"hoje": 0, "amanha": 1}.get(k, 2))).isoformat()
        else:
            m = tira(r"\s(?:para|pra|at[ée]|prazo)\s+(?:o\s+dia\s+|dia\s+)(\d{1,2})\b")
            if m:
                dia = int(m.group(1))
                if 1 <= dia <= 31:
                    ano, mes = hoje.year, hoje.month
                    for _ in range(3):
                        try:
                            cand = date(ano, mes, dia)
                        except ValueError:
                            cand = None
                        if cand and cand >= hoje:
                            prazo = cand.isoformat()
                            break
                        mes, ano = (1, ano + 1) if mes == 12 else (mes + 1, ano)
            else:
                m = tira(r"\s(?:para|pra|at[ée]|prazo)\s+(?:a\s+|o\s+)?(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)(?:-feira)?\b")
                if m:
                    alvo = DIAS_SEMANA[norm(m.group(1))]
                    dias = (alvo - hoje.weekday()) % 7 or 7
                    prazo = (hoje + timedelta(days=dias)).isoformat()
    return _limpa(t), prazo, prio


def _data_dm(dia: int, mes: int, ano: str | None, hoje: date) -> str | None:
    """dia/mes (e ano opcional) -> AAAA-MM-DD; sem ano, a proxima ocorrencia a partir de hoje."""
    try:
        if ano:
            a = int(ano)
            return date(a + 2000 if a < 100 else a, mes, dia).isoformat()
        for a in (hoje.year, hoje.year + 1):
            try:
                cand = date(a, mes, dia)
            except ValueError:
                continue
            if cand >= hoje:
                return cand.isoformat()
    except ValueError:
        pass
    return None


_SEM_DATA = re.compile(r"\b(?:sem\s+(?:data|prazo)|nao\s+(?:precisa|tem|quero)|nenhuma?|tanto\s+faz|qualquer\s+(?:dia|data)|"
                       r"deixa\s+assim|sem|nao|depois)\b")


def interpretar_prazo(texto: str, hoje: date) -> tuple[str, str | None] | None:
    """Resposta a "para quando?": ("data", AAAA-MM-DD), ("sem", None) ou None (nao e uma resposta de data)."""
    t = norm(texto)
    if not t or len(t.split()) > 9:
        return None
    m = re.search(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?(?!\d)", texto)  # "25/12" (norm tira a barra)
    if m:
        d = _data_dm(int(m.group(1)), int(m.group(2)), m.group(3), hoje)
        return ("data", d) if d else None
    t = re.sub(r"^(?:e\s+|eh\s+|seria\s+|sera\s+|pode\s+ser\s+|coloca\s+|marca\s+|bota\s+)?(?:para\s+|pra\s+|ate\s+)?(?:o\s+|a\s+)?", "", t)
    if re.fullmatch(r"\d{1,2}", t):
        t = "dia " + t
    m = re.search(r"\b(?:daqui\s+a|em)\s+(\d+|" + "|".join(NUMEROS) + r")\s+(dias?|semanas?)\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else NUMEROS[m.group(1)]
        return "data", (hoje + timedelta(days=n * (7 if m.group(2).startswith("semana") else 1))).isoformat()
    _, prazo, _ = extrair_prazo_prioridade("x para " + t, hoje)
    if prazo:
        return "data", prazo
    if _SEM_DATA.search(t):
        return "sem", None
    return None


def responder_prazo(texto: str, lista: Tarefas) -> str | None:
    """Se o Jarvis acabou de perguntar "para quando?", trata a resposta; senao None (segue o fluxo normal).
    A pergunta vale uma unica fala: qualquer outra coisa dita depois a cancela."""
    p, lista.pendente_prazo = lista.pendente_prazo, None
    if not p:
        return None
    tid, ate = p
    agora = lista.agora()
    if agora > ate:
        return None
    r = interpretar_prazo(texto, agora.date())
    if r is None:
        return None
    if r[0] == "sem":
        return "Certo, senhor, sem data."
    t = lista.definir_prazo(tid, r[1])
    if not t:
        return None
    return f"Combinado, senhor: {t['texto']}{_fala_prazo(r[1], agora.date())}."


def _fala_prazo(prazo: str | None, hoje: date) -> str:
    if not prazo:
        return ""
    d = date.fromisoformat(prazo)
    delta = (d - hoje).days
    if delta == 0:
        return ", para hoje"
    if delta == 1:
        return ", para amanhã"
    if 1 < delta < 7:
        return f", para {NOMES_DIA[d.weekday()]}"
    return f", para o dia {d.day}"


def _adicao(t: str) -> tuple[str, str]:
    """Frase de "anote/insira/adicione ... tarefa" -> ("ok", texto da tarefa); ("plural", _) se for varias/ditado longo
    (quem interpreta e o Claude); ("nao", _) se nao for pedido de adicionar."""
    nova = _NOVA.match(t)
    if nova:  # "nova tarefa comprar cafe": o proprio pedido ja diz que e tarefa
        resto = _FILLER.sub("", nova.group("resto"))
        return ("plural", "") if _PLURAL.match(resto) or len(resto) > 220 else ("ok", _SUF_LISTA.sub("", resto))
    m = _ADD.match(t)
    if not m:
        return "nao", ""
    v, resto = norm(m.group("v")), m.group("resto")
    menciona = bool(re.search(r"\b(tarefas?|lista)\b", norm(resto)))
    explicito = v in ("insira", "insere", "inserir", "anote", "anota", "anotar")
    # "adicione/crie/registre/coloque ..." so valem quando a frase fala de tarefa ou lista
    # (senao pode ser outro pedido, como "crie um rascunho de e-mail": segue para o Claude)
    if not (explicito or menciona):
        return "nao", ""
    if _PLURAL.match(resto) or len(resto) > 220:
        return "plural", ""
    resto = _PRE_LISTA.sub("", resto)
    resto = _PRE_TAREFA.sub("", resto)
    resto = _FILLER.sub("", resto)
    return "ok", _SUF_LISTA.sub("", resto)


def responder(texto: str, lista: Tarefas) -> str | None:
    """Se a frase for um comando de tarefas, executa e devolve a fala do Jarvis; senao None (segue para o Claude)."""
    t = texto.strip()
    if not t or len(t) > 400:
        return None
    hoje = lista.agora().date()
    tn = norm(t)

    if _UNDO.match(t) and ("ultima" in tn or "alteracao" in tn or "acao" in tn or len(tn.split()) <= 3):
        return "Desfeito, senhor." if lista.desfazer() else "Não há nada para desfazer, senhor."

    tipo, resto = _adicao(t)
    if tipo == "plural":
        return None
    if tipo == "ok":
        texto_t, prazo, prio = extrair_prazo_prioridade(resto, hoje)
        if not texto_t:
            return "Qual é a tarefa, senhor?"
        tarefa, criada = lista.adicionar(texto_t, prazo=prazo, prioridade=prio)
        if not criada:
            return f"Já consta na lista, senhor: {tarefa['texto']}."
        fala = f"Anotado, senhor: {tarefa['texto']}{_fala_prazo(tarefa['prazo'], hoje)}."
        if not tarefa["prazo"] and lista.perguntar_prazo:  # opcional: pode dizer a data ou "sem data"
            lista.pendente_prazo = (tarefa["id"], lista.agora() + timedelta(seconds=PERGUNTA_PRAZO_TTL))
            fala += " Para quando? Pode dizer a data, ou sem data."
        return fala

    for padrao, acao in ((_DONE, "concluir"), (_DONE_MARCA, "concluir"), (_DONE_DE, "concluir"), (_DONE_PASSADO, "concluir"),
                         (_DONE_SUFIXO, "concluir"), (_REM, "remover")):
        m = padrao.match(t)
        if not m:
            continue
        ref = _PRE_LISTA.sub("", re.sub(r"\s+(?:da|na|de|em)\s+(?:minha\s+)?lista(?:\s+de\s+tarefas)?[\s.!?]*$", "", m.group("ref"), flags=re.I))
        tem_palavra = "tarefa" in tn
        ref = re.sub(r"^(?:a\s+|essa\s+|esta\s+)?(?:tarefa\s*)?(?:n[úu]mero\s*)?", "", _limpa(ref), flags=re.I)
        cands = lista.resolver(ref)
        if not cands:
            if tem_palavra:
                return "Não encontrei essa tarefa, senhor."
            return None  # pode ser outro tipo de pedido: segue para o Claude
        if len(cands) > 1:
            nums = ", ".join(f"{lista.abertas().index(c) + 1}: {c['texto']}" for c in cands[:3])
            return f"Encontrei mais de uma, senhor. Qual delas? {nums}."
        alvo = cands[0]
        if acao == "concluir":
            lista.concluir(alvo)
            return f"Concluída, senhor: {alvo['texto']}."
        lista.remover(alvo)
        return f"Removida, senhor: {alvo['texto']}. Se foi engano, diga desfazer."

    if _LISTA.match(t) and len(tn.split()) <= 14:
        ab = lista.abertas()
        if not ab:
            return "A sua lista está vazia, senhor."
        ordinais = ["Primeira", "Segunda", "Terceira", "Quarta", "Quinta"]
        partes = [f"{ordinais[i]}, {x['texto']}{_fala_prazo(x['prazo'], hoje)}" for i, x in enumerate(ab[:5])]
        resto = f" E mais {len(ab) - 5}." if len(ab) > 5 else ""
        n = len(ab)
        return f"Senhor, {'há' if n == 1 else 'são'} {n} tarefa{'s' if n > 1 else ''} aberta{'s' if n > 1 else ''}. " + ". ".join(partes) + "." + resto
    return None


def adicionar_livre(lista: Tarefas, texto: str, origem: str = "painel") -> tuple[dict | None, bool]:
    """Texto digitado no painel ('revisar contrato para sexta urgente') -> tarefa com prazo e prioridade."""
    texto = _limpa(texto)
    if not texto:
        return None, False
    limpo, prazo, prio = extrair_prazo_prioridade(texto, lista.agora().date())
    if not limpo:
        return None, False
    return lista.adicionar(limpo, prazo=prazo, prioridade=prio, origem=origem)


def entrada_do_painel(lista: Tarefas, texto: str, prazo: str | None = None) -> tuple[str | None, bool, bool]:
    """Campo 'Nova tarefa': aceita tambem os comandos de voz digitados ('conclua a tarefa 2').
    `prazo`: None = o usuario ainda nao escolheu; "" = escolheu "sem data"; AAAA-MM-DD = escolheu essa data.
    Devolve (frase para mostrar, mudou_algo, perguntar_prazo): quando a tarefa nao traz data e ainda nao houve
    escolha, nada e criado e o painel mostra as opcoes de prazo (que sao opcionais)."""
    t = _limpa(texto)
    if not t:
        return None, False, False
    tipo, base = _adicao(t)
    if tipo != "ok":
        fala = responder(t, lista)
        if fala is not None:
            return fala, True, False
        base = t
    limpo, prazo_texto, prio = extrair_prazo_prioridade(base, lista.agora().date())
    if not limpo:
        return None, False, False
    if prazo is None:
        if prazo_texto is None and lista.perguntar_prazo:
            return None, False, True
        prazo = prazo_texto
    tarefa, criada = lista.adicionar(limpo, prazo=prazo or None, prioridade=prio, origem="painel")
    return (f"Anotado: {tarefa['texto']}" if criada else f"Já consta na lista: {tarefa['texto']}"), criada, False


# ------------------------------------------------------------------ linha de comando
def lista_padrao() -> Tarefas:
    cfg: dict = {}
    for nome in ("config.json", "config.example.json"):
        try:
            cfg = json.loads((BASE / nome).read_text(encoding="utf-8"))
            break
        except Exception:
            continue
    c = cfg.get("tarefas", {})

    def caminho(p: str) -> Path:
        q = Path(os.path.expandvars(os.path.expanduser(p)))
        return q if q.is_absolute() else BASE / q

    return Tarefas(caminho(c.get("arquivo", "tarefas.json")), caminho(c.get("md", "TAREFAS.md")),
                   perguntar_prazo=bool(c.get("perguntar_prazo", True)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lista de tarefas do Jarvis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("texto"); a.add_argument("--prazo"); a.add_argument("--prio", default="media")
    a.add_argument("--tag", action="append", default=[])
    ls = sub.add_parser("list"); ls.add_argument("--todas", action="store_true")
    for nome in ("done", "remove"):
        s = sub.add_parser(nome); s.add_argument("ref")
    pz = sub.add_parser("prazo"); pz.add_argument("ref"); pz.add_argument("data", help="AAAA-MM-DD ou 'nenhum'")
    sub.add_parser("undo"); sub.add_parser("md")
    args = ap.parse_args(argv)
    lista = lista_padrao()
    out = lambda o: print(json.dumps(o, ensure_ascii=False))  # noqa: E731

    if args.cmd == "add":
        if args.prazo:
            date.fromisoformat(args.prazo)  # valida AAAA-MM-DD
        t, criada = lista.adicionar(args.texto, prazo=args.prazo, prioridade=args.prio, tags=tuple(args.tag), origem="cli")
        out({"ok": True, "criada": criada, "tarefa": t})
    elif args.cmd == "list":
        itens = lista.todas() if args.todas else lista.abertas()
        for i, t in enumerate(itens, 1):
            print(f"{i}. [{t['status']}] {t['texto']}" + (f"  (prazo {t['prazo']})" if t.get("prazo") else "") + (f"  [{t['prioridade']}]" if t.get("prioridade") != "media" else ""))
        if not itens:
            print("(nenhuma)")
    elif args.cmd in ("done", "remove"):
        c = lista.resolver(args.ref)
        if len(c) != 1:
            out({"ok": False, "erro": "nenhuma tarefa" if not c else "ambiguo", "candidatas": [x["texto"] for x in c]})
            return 1
        out({"ok": True, "tarefa": (lista.concluir if args.cmd == "done" else lista.remover)(c[0])})
    elif args.cmd == "prazo":
        c = lista.resolver(args.ref)
        if len(c) != 1:
            out({"ok": False, "erro": "nenhuma tarefa" if not c else "ambiguo", "candidatas": [x["texto"] for x in c]})
            return 1
        nova = None if norm(args.data) in ("nenhum", "nenhuma", "sem data", "limpar") else args.data
        out({"ok": True, "tarefa": lista.definir_prazo(c[0]["id"], nova)})
    elif args.cmd == "undo":
        out({"ok": lista.desfazer()})
    elif args.cmd == "md":
        lista.escrever_md(); out({"ok": True, "arquivo": str(lista.md)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
