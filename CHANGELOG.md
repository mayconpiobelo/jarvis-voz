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
- **Ligação pelo WhatsApp por voz** (`whatsapp.py`): “liga para a Maria no WhatsApp” com **confirmação por voz obrigatória**, contatos listados por você no `config.json`, travas (janela do WhatsApp em primeiro plano, sem jogo em tela cheia) e modo `dry_run`. O teste de privacidade agora barra telefones celulares em arquivos versionados.
- **Testar som**: item na bandeja e ação `testar_som`; o serviço relê os dispositivos de áudio antes de falar/gravar (corrige voz muda depois que o Windows troca a saída padrão).
- **Funciona sem fone**: `mic_device` e `speaker_device` (`"notebook"`, `"auto"`, nome ou índice). A voz, os bips e o microfone usam o som interno do notebook; dispositivos virtuais (Steam Streaming) são pulados no modo automático, e se o escolhido sumir o Jarvis usa o do notebook e relê o hardware. Os bips agora saem pelo mesmo alto-falante da voz.
- **“Para quando?”**: ao criar uma tarefa sem data, o Jarvis pergunta o prazo (opcional) — por voz (“amanhã”, “sexta”, “25/12”, “sem data”…) e no painel (Hoje, Amanhã, Em 1 semana, outra data, Sem data). Novas formas de data nas frases (`25/12`, `25 de dezembro`, `semana que vem`), `tarefas.py prazo` e a opção `tarefas.perguntar_prazo` para desligar.
- **Esfera multi-monitor**: a esfera flutuante aparece no canto da tela da janela em uso e acompanha quando você troca de monitor; o botão Esfera mostra a esfera por alguns segundos ao ligar.
- **Painel móvel e redimensionável**: arraste pela barra de cima para mover e pelas bordas/cantos para mudar o tamanho (mínimo 420×380); o layout se reorganiza (duas colunas viram uma, com rolagem, em janelas estreitas) e o painel reabre onde você o deixou, mesmo em outro monitor. Se a tela guardada sumir, volta ao canto padrão. Duplo clique na barra, o botão ↺ ou o item “Restaurar posição do painel” da bandeja restauram posição e tamanho. Pequena animação de entrada.

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
