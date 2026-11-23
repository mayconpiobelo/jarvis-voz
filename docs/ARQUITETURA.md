# Arquitetura

```
 Ctrl+Alt+J (RegisterHotKey)
        │
        ▼
 ┌──────────── jarvis.py (serviço, ícone na bandeja) ─────────────┐
 │ microfone ─► Whisper (local) ─► handle_text                     │
 │                                   ├─ comandos de tarefas ─► tarefas.py (resposta imediata)
 │                                   ├─ "confirma"/"cancela" ─► libera/cancela a ação pendente
 │                                   └─ demais pedidos ─► claude -p (headless, stream-json)
 │                                              │  hook PreToolUse ─► trava.py
 │ resposta ─► limpeza de texto ─► Kokoro (local) ─► alto-falante
 │ servidor HTTP local 127.0.0.1:8765 ─► janela (historico.html) e overlay.html
 └──────────────────────────────────────────────────────────────────┘
        ▲                                   │ /api/status (estado, nível de voz, ferramentas)
        │                                   ▼
 overlay (Tauri, jarvis-overlay.exe): janela transparente com a esfera
```

## Peças
| Arquivo | Papel |
|---|---|
| `jarvis.py` | Serviço: atalho, gravação, STT, chamada ao Claude, TTS, bandeja, servidor local, controle do overlay |
| `trava.py` | Hook de segurança do Claude Code (ver [SEGURANCA.md](SEGURANCA.md)) |
| `tarefas.py` | Lista de tarefas (ver [TAREFAS.md](TAREFAS.md)) |
| `historico.html` | Janela completa: esfera, fluxo Microfone→Whisper→Claude→Voz, ferramentas em uso, legendas, histórico e tarefas |
| `musica.py` | Lê e controla o que está tocando (Spotify e outros) pelo controle de mídia do Windows (SMTC); sem login nem chave |
| `painel.html` | Painel rápido de widgets (Tarefas, Hoje, Jarvis, Atalhos, Sistema); servido em `/painel` |
| `overlay.html` + `overlay/` | Esfera flutuante (página transparente + casca Tauri sem foco e com cliques atravessando) |
| `voz_lab.py` + `voz_lab.html` | Laboratório para ouvir e escolher a voz (porta 8766, só quando iniciado) |
| `config.example.json` | Todas as opções, com padrões seguros |

## Painel rápido
O app Tauri tem **duas janelas**: a esfera (transparente, sem foco, cliques atravessam) e o **painel** (oculto até ser chamado). O Jarvis decide quando o painel aparece: o atalho global (`painel.hotkey`) ou o item da bandeja liga `CURRENT["painel"]`; a casca Rust consulta `GET /api/painel` (~150 ms), mostra/esconde a janela, a posiciona no canto configurado **na tela onde está o mouse** e a focaliza (o Jarvis autoriza a troca de foco com `AllowSetForegroundWindow`). O painel fecha com `Esc`, ao perder o foco (a menos que esteja fixado) ou pelo X. Sem o app (overlay desligado), o atalho abre a mesma página no navegador.

Rotas locais usadas pelo painel: `/api/tarefas` (+ `/adicionar`, `/concluir`, `/remover`, `/desfazer`), `/api/sistema` (CPU, memória, tempo ligado, via API do Windows), `/api/musica` (+ `/capa`, `/acao`), `/api/atalhos`, `/api/acao`, `/api/painel`.

## Estados e sinais
`idle → listening → transcribing → thinking → speaking → idle`. O serviço publica em `/api/status`: estado, **nível de áudio** (microfone ao ouvir; envelope da voz ao falar), ferramentas em uso (do stream do Claude) e se aguarda confirmação.

## Decisões de projeto
- **Claude via CLI oficial** (`claude -p`), com o login do próprio usuário: o Jarvis não guarda credenciais. (A documentação do Agent SDK pede chave de API para produtos de terceiros; para uso pessoal o CLI é o caminho documentado.)
- **Voz e fala locais** (Kokoro e faster-whisper): nada do áudio nem do texto falado sai da máquina, exceto o que é enviado ao Claude.
- **Atalho pelo Windows** (`RegisterHotKey`), não por gancho global de teclado (menos suspeito para antivírus).
- **Sem foco**: o overlay nunca rouba o foco nem bloqueia cliques.
- **Instância única** por mutex; a inicialização com o Windows é um atalho em *Inicializar* (item do menu da bandeja).

## Portas e arquivos locais
`127.0.0.1:8765` (janela/API) · `8766` (laboratório de voz). Estado e dados pessoais, todos fora do git: `config.json`, `historico.jsonl`, `state.json` (sessão do Claude), `tarefas.json`, `.estado/` (token de confirmação e log da trava), `jarvis.log`.
