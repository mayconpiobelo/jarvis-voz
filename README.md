# Jarvis de voz

Assistente de voz para **Windows**, no estilo do Jarvis do Homem de Ferro: você aperta um atalho, fala, e ele **age** usando o seu Claude Code (e-mail, agenda, arquivos, web…) e responde em voz alta. Voz e reconhecimento de fala rodam **localmente**.

```
Ctrl+Alt+J → microfone → Whisper (local) → Claude Code (suas ferramentas) → Kokoro (local) → esfera
```

- **Esfera flutuante** (overlay): aparece sozinha no canto da tela enquanto ele ouve, pensa e fala; não rouba o foco e os cliques passam por ela.
- **Janela completa**: esfera, etapas (Microfone → Whisper → Claude → Voz), ferramentas em uso, legendas, histórico e **tarefas**.
- **Painel rápido** (`Ctrl+Alt+T`): painel flutuante de widgets, com **Tarefas** (campo “Nova tarefa”, concluir com um clique), **Hoje** (com a temperatura e o tempo da sua cidade, CPU e memória), **Claude** (quanto você já usou da sessão de 5 h e da semana, e quando cada uma reinicia, como na tela de uso do claude.ai), **Música** (Spotify: capa, progresso e controles), **Jarvis** e **Atalhos** (apps e links seus).
- **Trava de segurança**: o que envia, publica ou mexe fora da sua pasta só acontece depois de você dizer **“confirma”**; apagar e comandos destrutivos ficam bloqueados.
- **Lista de tarefas por voz**: *“Jarvis, insira: atualizar workload geral na lista de tarefas.”*

> **Aviso:** o Jarvis dá ao Claude acesso amplo ao seu computador. Leia [docs/SEGURANCA.md](docs/SEGURANCA.md) antes de usar.

## Requisitos
- Windows 10/11 · Python **3.11–3.13** · microfone e caixas de som
- [Claude Code](https://claude.com/claude-code) instalado e logado (`claude auth login`)
- Opcional, só para compilar o overlay: Rust + Build Tools do Visual Studio (C++)

## Instalação
```powershell
git clone <este-repositorio> jarvis
cd jarvis
.\scripts\instalar.ps1 -ComOverlay      # -SemModelos pula o download de voz (~340 MB)
```
O script cria o `.venv`, instala as dependências, copia `config.example.json` → `config.json` (**edite-o**: `owner_name`, atalho, voz, permissões) e baixa os modelos. O modelo de fala (Whisper “small”, ~460 MB) baixa sozinho no primeiro uso.

## Uso
```powershell
.\iniciar-jarvis.cmd        # inicia em segundo plano (ícone na bandeja)
```
| Ação | Como |
|---|---|
| Falar | `Ctrl+Alt+J` (configurável), fale; ele para quando você silencia |
| Interromper a fala | Apertar o atalho de novo |
| Confirmar/cancelar | Dizer “confirma”/“sim” ou “não”/“cancela” depois que ele perguntar |
| Painel rápido | `Ctrl+Alt+T` (configurável em `painel.hotkey`); `Esc` fecha; 📌 fixa na tela; arraste a barra de cima para mover e as bordas para redimensionar (ele lembra o lugar; duplo clique na barra restaura); as setas navegam pelas tarefas, `Espaço` conclui, `Delete` remove, `Ctrl+Z` desfaz |
| Janela completa | Menu da bandeja → *Abrir histórico*, ou `http://127.0.0.1:8765` (`H` detalhes, `L` histórico, `T` tarefas) |
| Nova conversa | Dizer “nova conversa” ou menu da bandeja |
| Iniciar com o Windows | Menu da bandeja → *Iniciar com o Windows* |

### Música por voz
“pausa a música” · “continua a música” · “próxima música” · “música anterior” · “o que está tocando”. Funciona com o Spotify (inclusive o da Microsoft Store) e com qualquer player que apareça no controle de mídia do Windows, **sem login nem chave de API**. Pedidos como “toca uma música do Queen” seguem para o Claude (o Jarvis não busca faixas).

### Ligação pelo WhatsApp
“Jarvis, liga para a Maria no WhatsApp” → o Jarvis pergunta *“Ligar para Maria pelo WhatsApp, senhor. Confirma?”* e **só liga depois do seu “confirma”**. Cadastre os contatos em `whatsapp.contatos` do `config.json` (`"maria": "(11) 90000-0000"`; fica fora do git). Ele abre a conversa pelo número e aperta o atalho de ligação de voz do WhatsApp Desktop (`Ctrl+Shift+C`), só se o WhatsApp estiver em primeiro plano e sem jogo em tela cheia. Com `"dry_run": true` ele faz tudo menos apertar a tecla. Veja [docs/SEGURANCA.md](docs/SEGURANCA.md).

### Se o Jarvis cair
O `iniciar-jarvis.cmd` abre também um vigia que reabre o Jarvis em até ~10 s se ele sumir (até 5 vezes em 10 min). Para encerrar de vez, use **Sair** no menu da bandeja (o vigia respeita). O motivo de uma queda fica no `jarvis.log` e em `.estado/jarvis_crash.log`.

### Velocidade das respostas
- **Claude já aberto**: o Jarvis abre o Claude Code quando você aperta o atalho (enquanto ainda fala) e o mantém aberto entre os pedidos; ele fecha sozinho depois de 20 min sem uso. Uma pergunta simples cai de ~6 s para ~2–3 s. Em `config.json`: `claude_persistente` (padrão `true`), `claude_idle_minutes` (padrão `20`; o Claude aberto usa ~300 MB), e, se quiser, `claude_model` e `claude_effort` (`low`/`medium`/`high`).
- **Trava rápida**: a verificação de segurança antes de cada ferramenta virou uma chamada de ~30 ms ao próprio serviço (antes ~1,7 s por ferramenta).
- **Respostas na hora, sem o Claude**: tarefas, música, “que horas são” e “que dia é hoje”.

### Tarefas por voz
“insira: *texto* na lista de tarefas” · “quais são as minhas tarefas” · “conclua a tarefa 2” · “remova a tarefa do contrato” · “desfazer”. Detalhes em [docs/TAREFAS.md](docs/TAREFAS.md).

## Configuração
**Microfone e caixas de som**: `mic_device` e `speaker_device`. O modo `"auto"` (padrão; também `null`) **acompanha o áudio do sistema**: com um headset conectado e selecionado no Windows, o Jarvis usa o microfone e o fone dele; sem ele, usa o microfone e as caixas do notebook. Ele pula dispositivos virtuais (como o Steam Streaming) e caixas de monitor (HDMI) quando são o padrão, e relê os dispositivos a cada uso, então trocar de fone vale na hora. `"notebook"` usa sempre o som interno do notebook; um trecho do nome (ex.: `"HyperX"`) escolhe um dispositivo específico. Se o escolhido sumir (fone desligado), o Jarvis usa o do notebook sozinho. Para ver os nomes: `.venv\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"`. A escolha aparece no `jarvis.log`.

**Clima**: `painel.clima` guarda `cidade` (só o nome mostrado), `lat` e `lon` (use as coordenadas da cidade; o exemplo é São Paulo). O Jarvis consulta o Open-Meteo no máximo 1 vez por hora e só envia essas coordenadas arredondadas. `enabled: false` desliga.

A música usa `painel.musica` (`enabled` e `app`, o player preferido; padrão `Spotify`). O painel e os seus atalhos (apps, pastas e links) ficam em `painel` no `config.json`: `hotkey`, `corner` (`tr`, `tl`, `br`, `bl`, `c`) e `atalhos` (`{id, nome, tipo: app|url, alvo}`; o botão “Adicionar” do painel abre o arquivo). O navegador nunca recebe o `alvo`, só o `id`.

Tudo está em `config.json` (modelo em `config.example.json`): atalho, voz (`kokoro_*`), persona, bloqueios e confirmação, posição do overlay (`overlay.corner/size/margin`), arquivo de tarefas. Veja [docs/VOZ.md](docs/VOZ.md).

## Desenvolvimento
```powershell
pip install -r requirements-dev.txt
python -m pytest        # sem microfone, modelos ou rede
ruff check .
```
Mais em [CONTRIBUTING.md](CONTRIBUTING.md) e [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Estrutura
```
jarvis.py  trava.py  tarefas.py      serviço, trava de segurança, lista de tarefas
historico.html  overlay.html         janela completa e esfera do overlay
painel.html                          painel rápido (widgets: tarefas, hoje, Jarvis, atalhos, sistema)
voz_lab.py  voz_lab.html             laboratório de voz
overlay/                             app Tauri (Rust) da esfera flutuante
config.example.json                  configuração de exemplo (config.json fica fora do git)
scripts/  tests/  docs/              instalação, testes, documentação
```

## Licença
A definir pelo(s) autor(es) antes da publicação.
