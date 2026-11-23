# Jarvis de voz

Assistente de voz para **Windows**, no estilo do Jarvis do Homem de Ferro: você aperta um atalho, fala, e ele **age** usando o seu Claude Code (e-mail, agenda, arquivos, web…) e responde em voz alta. Voz e reconhecimento de fala rodam **localmente**.

```
Ctrl+Alt+J → microfone → Whisper (local) → Claude Code (suas ferramentas) → Kokoro (local) → esfera
```

- **Esfera flutuante** (overlay): aparece sozinha no canto da tela enquanto ele ouve, pensa e fala; não rouba o foco e os cliques passam por ela.
- **Janela completa**: esfera, etapas (Microfone → Whisper → Claude → Voz), ferramentas em uso, legendas, histórico e **tarefas**.
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
| Janela completa | Menu da bandeja → *Abrir histórico*, ou `http://127.0.0.1:8765` (`H` detalhes, `L` histórico, `T` tarefas) |
| Nova conversa | Dizer “nova conversa” ou menu da bandeja |
| Iniciar com o Windows | Menu da bandeja → *Iniciar com o Windows* |

### Tarefas por voz
“insira: *texto* na lista de tarefas” · “quais são as minhas tarefas” · “conclua a tarefa 2” · “remova a tarefa do contrato” · “desfazer”. Detalhes em [docs/TAREFAS.md](docs/TAREFAS.md).

## Configuração
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
voz_lab.py  voz_lab.html             laboratório de voz
overlay/                             app Tauri (Rust) da esfera flutuante
config.example.json                  configuração de exemplo (config.json fica fora do git)
scripts/  tests/  docs/              instalação, testes, documentação
```

## Licença
A definir pelo(s) autor(es) antes da publicação.
