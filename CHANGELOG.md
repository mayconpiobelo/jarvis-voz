# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]
### Adicionado
- **Painel rápido** flutuante (`Ctrl+Alt+T`) com widgets de Tarefas, Hoje, Jarvis, Atalhos e Sistema; segunda janela no app Tauri, posicionada na tela do mouse.
- Atalhos de apps e links configuráveis (`painel.atalhos`), sem expor o alvo ao navegador.
- Entrada de texto livre nas tarefas (prazo e prioridade) e comandos digitados no painel.
- Segundo atalho global e `esfera` mostrar/ocultar sem encerrar o app.

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
