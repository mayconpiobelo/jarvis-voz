# Segurança

O Jarvis dá ao Claude acesso amplo ao seu computador e às suas ferramentas (e-mail, agenda, arquivos). O risco central é **injeção de instrução**: texto de um e-mail, página ou arquivo de terceiros tentando mandar o Claude agir. As camadas abaixo reduzem o dano; **não são uma caixa de areia**.

## Camadas
1. **Persona**: conteúdo vindo de ferramentas é *dado*, nunca instrução.
2. **Bloqueio permanente** (`deny_always`): apagar (`rm`, `Remove-Item`, apagar e-mails/itens), `git push`, desligar/formatar. Essas ferramentas nem são oferecidas ao Claude.
3. **Trava com confirmação por voz** (`trava.py`, hook `PreToolUse`):
   - passa direto: ler, buscar, consultar, rascunhos;
   - exige “confirma”: enviar e-mail/Teams, criar/alterar convites, alterar o SharePoint, escrever fora da pasta do usuário ou em `AppData`/`.claude`/`.ssh`, comandos que enviam dados à rede, agendamentos, e **qualquer ferramenta MCP desconhecida**;
   - o “confirma” vale **só para aquele pedido** (token `.estado/confirmado`, expira em 2 min, apagado ao fim);
   - **falha fechada**: entrada ilegível = barrado.
4. **Servidor local endurecido**: só `127.0.0.1`; recusa `Host` diferente (DNS rebinding); POST exige JSON (força preflight CORS).
5. **Painel e atalhos**: `/api/acao` só aceita **ids conhecidos** (ações internas ou atalhos definidos no seu `config.json`); o navegador nunca recebe nem envia o alvo (caminho/URL), e links só abrem se forem `http(s)`.
6. **Overlay**: sem foco, cliques atravessam; não executa nada, só exibe.
7. **Repositório**: `config.json`, histórico, tarefas, tokens e modelos estão no `.gitignore`; um teste (`tests/test_privacidade.py`) falha se dado pessoal ou segredo entrar em arquivo versionado.

## Riscos residuais
- **Confirmação por voz**: ruído que o Whisper entenda como “sim” logo após uma pergunta de confirmação libera a ação *anunciada*. Frases com mais de 6 palavras não valem e qualquer negação vence.
- **Lista de proteção**: um comando de shell fora dos padrões pode passar. Revise `trava.py` ao conectar ferramentas novas.
- **`bypassPermissions`**: o Claude headless roda sem pedir permissão nativa; a segurança vem do `deny_always` e da trava. Não habilite `allow_outward_actions` sem entender o que isso libera.
- **Dados enviados ao Claude** seguem as regras da sua conta Anthropic; o histórico das sessões fica em `~/.claude/projects/`.
- **Whisper erra**: uma tarefa ou pedido mal transcrito é executado como entendido. Ouça a resposta.

## Reportar problemas
Veja [SECURITY.md](../SECURITY.md).
