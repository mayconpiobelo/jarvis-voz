# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]
### Adicionado
- **Painel rápido** flutuante (`Ctrl+Alt+T`) com widgets de Tarefas, Hoje, Jarvis, Atalhos e Sistema; segunda janela no app Tauri, posicionada na tela do mouse.
- Atalhos de apps e links configuráveis (`painel.atalhos`), sem expor o alvo ao navegador.
- Entrada de texto livre nas tarefas (prazo e prioridade) e comandos digitados no painel.
- Widget de **Música** (Spotify e outros players): capa, faixa, progresso e controles; o fundo do cartão assume a cor da capa.
- Comandos de voz de música (“pausa a música”, “próxima música”, “o que está tocando”), com resposta imediata.
- **Visual novo do painel**: degradê profundo, cartões em vidro, acento ciano-violeta; o Sistema virou barras dentro do Hoje.
- Segundo atalho global e `esfera` mostrar/ocultar sem encerrar o app.
- **Vigia e registro de quedas**: o Jarvis já sumiu algumas vezes sem deixar rastro. Agora `iniciar-jarvis.cmd` também abre o vigia (`scripts/vigia.ps1`), que reabre o serviço em até ~10 s se ele cair (no máximo 5 vezes em 10 min; respeita o “Sair” da bandeja), e o serviço registra no `jarvis.log` exceções (inclusive de threads), o fim do processo e travamentos nativos (`.estado/jarvis_crash.log`).
- **Respostas mais rápidas**: (1) o Claude Code fica aberto entre os pedidos e é aberto ao apertar o atalho, enquanto você fala (pergunta simples: ~6 s → ~2–3 s; fecha sozinho após 20 min parado e morre junto com o serviço); (2) a trava de segurança passou a rodar dentro do serviço (hook `curl` de ~30 ms, falha fechada) em vez de iniciar o Python a cada ferramenta (~1,7 s cada); (3) “que horas são” e “que dia é hoje” respondem na hora; (4) `claude_model`/`claude_effort` opcionais.
- **Ligação pelo WhatsApp por voz** (`whatsapp.py`): “liga para a Maria no WhatsApp” com **confirmação por voz obrigatória**, contatos listados por você no `config.json`, travas (janela do WhatsApp em primeiro plano, sem jogo em tela cheia) e modo `dry_run`. O teste de privacidade agora barra telefones celulares em arquivos versionados.
- **Testar som**: item na bandeja e ação `testar_som`; o serviço relê os dispositivos de áudio antes de falar/gravar (corrige voz muda depois que o Windows troca a saída padrão).
- **Funciona sem fone**: `mic_device` e `speaker_device` (`"notebook"`, `"auto"`, nome ou índice). A voz, os bips e o microfone usam o som interno do notebook; dispositivos virtuais (Steam Streaming) são pulados no modo automático, e se o escolhido sumir o Jarvis usa o do notebook e relê o hardware. Os bips agora saem pelo mesmo alto-falante da voz.
- **“Para quando?”**: ao criar uma tarefa sem data, o Jarvis pergunta o prazo (opcional) — por voz (“amanhã”, “sexta”, “25/12”, “sem data”…) e no painel (Hoje, Amanhã, Em 1 semana, outra data, Sem data). Novas formas de data nas frases (`25/12`, `25 de dezembro`, `semana que vem`), `tarefas.py prazo` e a opção `tarefas.perguntar_prazo` para desligar.
- **Esfera multi-monitor**: a esfera flutuante aparece no canto da tela da janela em uso e acompanha quando você troca de monitor; o botão Esfera mostra a esfera por alguns segundos ao ligar.
- **Painel móvel e redimensionável**: arraste pela barra de cima para mover e pelas bordas/cantos para mudar o tamanho (mínimo 420×380); o layout se reorganiza (duas colunas viram uma, com rolagem, em janelas estreitas) e o painel reabre onde você o deixou, mesmo em outro monitor. Se a tela guardada sumir, volta ao canto padrão. Duplo clique na barra, o botão ↺ ou o item “Restaurar posição do painel” da bandeja restauram posição e tamanho. Pequena animação de entrada.
- **O painel aberto se atualiza sozinho**: o app flutuante fica dias no ar com a página do painel na memória e não mostrava as novidades depois de uma atualização. Agora `/api/painel` informa a versão do `painel.html` e a página se recarrega ao perceber que mudou (ao abrir o painel ou em até 1 min).
- **Clima no painel**: no cartão Hoje, a temperatura e a condição resumida da sua cidade (“25°C · Parcialmente nublado · Jundiaí”), com ícone de sol, lua, nuvem, chuva etc. Vem do Open-Meteo (grátis, sem chave), é consultado **no máximo 1 vez por hora** e, sem rede, mostra o último dado em vez de sumir. A cidade fica em `painel.clima` (`cidade`, `lat`, `lon`).
- **Consumo do Claude no painel**: novo quadrante “Claude” entre Hoje e Música, igual à tela de uso do claude.ai: **sessão de 5 h** e **semana** (percentual, barra e “reinicia em 4 h 53 min · 12:49”), com a barra da semana dividida por origem (Claude Code, Cowork, Chats…). Verde/amarelo/vermelho a partir de 70% e 90%. Usa o login do próprio Claude Code, sem expô-lo ao navegador nem renová-lo, e guarda a consulta por 2 min (`uso_claude.py`, rota `/api/uso`, `painel.uso_claude.enabled`).

## [0.1.0] — 2026-11-22
### Adicionado
- Serviço de voz: atalho global → Whisper local → Claude Code headless → voz Kokoro local.
- Trava de segurança com **confirmação por voz** (hook `PreToolUse`), falhando fechada; bloqueio permanente de ações destrutivas.
- Janela completa com esfera reativa ao áudio, etapas, ferramentas em uso, legendas e histórico.
- **Overlay** Tauri: esfera flutuante transparente, sem foco, cliques atravessam, posição configurável.
- Atalho pelo Windows (`RegisterHotKey`), instância única, item “Iniciar com o Windows” na bandeja.
- **Lista de tarefas por voz** (`tarefas.py`): adicionar/listar/concluir/remover/desfazer, prazo e prioridade, visão em Markdown e aba na janela.
- Laboratório de voz (`voz_lab`), mistura de vozes e tratamento de áudio.
- Scripts de instalação, testes automatizados e CI.
