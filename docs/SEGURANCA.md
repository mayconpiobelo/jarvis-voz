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
   - a trava roda **dentro do serviço** (o hook é um `curl` de ~30 ms para `127.0.0.1:8765/api/trava`, em vez de iniciar o Python a cada ferramenta, que levava ~1,7 s): `--fail` + `|| exit 2` garantem que, se o serviço não responder, responder erro ou receber algo ilegível/grande demais, a ferramenta é **barrada**. `"trava_via_servico": false` volta ao script `trava.py`.
4. **Servidor local endurecido**: só `127.0.0.1`; recusa `Host` diferente (DNS rebinding); POST exige JSON (força preflight CORS).
5. **Painel e atalhos**: `/api/acao` só aceita **ids conhecidos** (ações internas ou atalhos definidos no seu `config.json`); o navegador nunca recebe nem envia o alvo (caminho/URL), e links só abrem se forem `http(s)`.
6. **Música**: usa só o controle de mídia do Windows (nada de credenciais do Spotify). `/api/musica/acao` aceita apenas `play_pause`, `proxima` e `anterior`; pode ser desligada em `painel.musica.enabled`.
7. **Ligação pelo WhatsApp** (`whatsapp.py`): é uma ação que sai para fora, então **só acontece depois do seu “confirma” por voz** (vale 30 s e uma única vez; qualquer outra fala cancela). Só liga para nomes que **você mesmo listou** em `whatsapp.contatos` do `config.json` (que fica fora do git). Antes de enviar a tecla de ligar, confere que a janela em primeiro plano é o WhatsApp e que não há jogo/apresentação em tela cheia; se algo estiver errado, desiste sem ligar. Não há rota HTTP que dispare ligações; `whatsapp.enabled: false` desliga tudo e `dry_run: true` faz tudo menos apertar o botão.
8. **Overlay**: sem foco, cliques atravessam; não executa nada, só exibe. O painel tem apenas duas permissões do Tauri (mover e redimensionar a própria janela), concedidas só a páginas de `127.0.0.1:8765`; a posição guardada (`/api/painel/geometria`) é validada (inteiros e limites) e nunca contém dados pessoais.
9. **Repositório**: `config.json`, histórico, tarefas, tokens e modelos estão no `.gitignore`; um teste (`tests/test_privacidade.py`) falha se dado pessoal, telefone ou segredo entrar em arquivo versionado.

## Riscos residuais
- **Confirmação por voz**: ruído que o Whisper entenda como “sim” logo após uma pergunta de confirmação libera a ação *anunciada*. Frases com mais de 6 palavras não valem e qualquer negação vence.
- **Lista de proteção**: um comando de shell fora dos padrões pode passar. Revise `trava.py` ao conectar ferramentas novas.
- **`bypassPermissions`**: o Claude headless roda sem pedir permissão nativa; a segurança vem do `deny_always` e da trava. Não habilite `allow_outward_actions` sem entender o que isso libera.
- **Dados enviados ao Claude** seguem as regras da sua conta Anthropic; o histórico das sessões fica em `~/.claude/projects/`.
- **Whisper erra**: uma tarefa ou pedido mal transcrito é executado como entendido. Ouça a resposta.

## Reportar problemas
Veja [SECURITY.md](../SECURITY.md).
