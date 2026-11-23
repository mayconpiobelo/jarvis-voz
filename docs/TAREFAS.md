# Lista de tarefas por voz — esquema e decisões

Exemplo central: **“Jarvis, insira: atualizar workload geral na lista de tarefas”** →
*“Anotado, senhor: atualizar workload geral.”* (resposta imediata, sem chamar o Claude).

## Princípios
1. **Voz primeiro, resposta imediata.** Comandos simples e frequentes são interpretados localmente (milissegundos, sem custo, funcionam offline). O Claude só entra no que exige interpretação.
2. **Um único arquivo manda.** `tarefas.json` é a fonte da verdade; tudo (voz, janela, linha de comando, Claude) lê e escreve nele pela mesma API (`tarefas.py`).
3. **Nada se perde.** “Remover” só marca como `removida`; há “desfazer” de um nível. Escrita atômica com cópia de segurança.
4. **Legível por humanos.** Cada alteração regrava `TAREFAS.md` (checklist em Markdown). Aponte `tarefas.md` do `config.json` para o seu cofre do Obsidian, se quiser.
5. **Dados pessoais ficam locais.** `tarefas.json`, `.bak` e `TAREFAS.md` estão no `.gitignore`.

## Fluxo (duas camadas)
```
 você fala ──► Whisper ──► tarefas.responder(frase)
                              │
              reconheceu? ────┴──── não ──► Claude (persona + comando tarefas.py)
                  │ sim                          │ (pedidos complexos: datas, várias tarefas)
                  ▼                              ▼
        altera tarefas.json  ◄───────── python tarefas.py add/done/remove/list/undo
                  │
        TAREFAS.md  +  janela (aba Tarefas)  +  fala da resposta
```

## Modelo de dados (`tarefas.json`)
```json
{"versao": 1, "proximo_id": 4, "tarefas": [
  {"id": 3, "texto": "atualizar workload geral", "status": "aberta",
   "prioridade": "media", "prazo": "2026-11-27", "tags": [],
   "criada": "2026-11-22T21:30:00", "atualizada": "...", "concluida": null, "origem": "voz"}]}
```
- `status`: `aberta` · `concluida` · `removida` (exclusão suave). IDs nunca são reutilizados.
- **Número falado** (“tarefa 2”) = posição na lista de abertas, ordenada por prioridade (alta primeiro), prazo (mais cedo primeiro) e id. É a mesma ordem da fala, da janela e do `TAREFAS.md`.

## Gramática de voz (camada local)
| Intenção | Exemplos |
|---|---|
| **Adicionar** | “insira: *texto* na lista de tarefas” · “anote *texto*” · “adicione *texto* na lista de tarefas” · “crie uma tarefa: *texto*” |
| **Prazo / prioridade** (dentro do texto) | “… para amanhã” · “… para sexta” · “… para o dia 5” · “… para hoje” · “… urgente” · “… prioridade baixa” |
| **Listar** | “quais são as minhas tarefas” · “liste minhas tarefas” · “o que tenho pendente” |
| **Concluir** | “conclua a tarefa 2” · “conclua a tarefa do workload” · “marque como feita a segunda tarefa” |
| **Remover** | “remova a tarefa 1” · “apague a tarefa contrato” |
| **Desfazer** | “desfazer a última alteração” |

Regras de segurança do interpretador, para **não sequestrar outros pedidos**:
- `insira`/`anote` valem sozinhos; `adicione`/`crie`/`registre`/`coloque` só valem se a frase falar de *tarefa* ou *lista* (assim “crie um rascunho de e-mail” e “adicione um evento na agenda” seguem para o Claude).
- `conclua`/`remova` sem a palavra “tarefa” só agem se a referência casar com uma tarefa aberta; senão a frase segue para o Claude.
- Referência ambígua → o Jarvis lista as candidatas e pergunta qual. Texto repetido não duplica (“Já consta na lista”).
- Resolução por trecho: ≥ 60 % das palavras relevantes do que você disse precisam aparecer na tarefa.

## Camada Claude (pedidos complexos)
O Jarvis ensina o Claude a usar a mesma lista (trecho da persona): `python tarefas.py add "…" --prazo AAAA-MM-DD --prio alta`, `list`, `done REF`, `remove REF`, `undo`. Exemplos que ela cobre: *“crie três tarefas: revisar contrato, ligar para o fornecedor e fechar o mês”*, *“passe tudo que vence esta semana para a próxima”*. O Claude nunca edita o arquivo diretamente.

## Painel rápido
`Ctrl+Alt+T` abre um painel flutuante com o widget **Tarefas**: contador, campo “Nova tarefa” (texto livre: *“revisar contrato para sexta urgente”* vira prazo e prioridade; também aceita os comandos de voz digitados, como *“conclua a tarefa 2”*), círculo para concluir, ✕ para remover, desfazer (`Ctrl+Z`) e lista de concluídas. O widget **Hoje** mostra quantas vencem hoje e quantas estão atrasadas.

## Janela
Aba **Tarefas** (tecla `T`): abertas numeradas, prioridade e prazo; clicar em uma conclui. Recentes concluídas abaixo. Atualiza sozinha quando você fala ou muda algo.

## Roadmap (ainda não implementado)
- **Recorrência**: “toda segunda: atualizar workload geral”.
- **Lembretes falados** no horário/prazo (“Senhor, vence hoje: …”) e **resumo da manhã** (“Bom dia, senhor. Hoje: …”).
- **Edição por voz**: renomear, mudar prazo/prioridade, etiquetas (`#obra`).
- **Sincronização**: Markdown no Obsidian (já possível via `tarefas.md`) e, depois, Outlook/Teams (o conector atual não tem ferramentas de tarefas).
- **Várias listas** (por projeto) e “workload” agregado por semana.

## Limites conhecidos
- Reconhecimento de fala errado vira tarefa errada: confira a resposta falada (e a aba Tarefas) e use “desfazer”.
- Datas relativas entendidas: hoje, amanhã, depois de amanhã, dia da semana, “dia N”. Outras (“daqui a duas semanas”) vão pelo Claude.
- Escrita simultânea (voz e Claude no mesmo instante) não tem trava de arquivo; é rara e o `.bak` cobre o pior caso.
