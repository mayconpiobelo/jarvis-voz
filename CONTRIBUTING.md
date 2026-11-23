# Contribuindo

## Ambiente
```powershell
.\scripts\instalar.ps1 -SemModelos
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```
Os testes não usam microfone, modelos nem rede. O projeto é **somente Windows** (usa `winsound` e `RegisterHotKey`).

## Regras
- **Nada pessoal no git.** `config.json`, histórico, tarefas, logs e modelos ficam no `.gitignore`. Se uma opção nova precisar de valor pessoal, ponha um valor genérico em `config.example.json` e use variáveis (`%USERPROFILE%`, `{dono}`). O teste `tests/test_privacidade.py` falha se nome, e-mail, caminho de usuário ou segredo entrarem em arquivo versionado.
- **Segurança primeiro.** Mudanças em `trava.py` ou nos bloqueios exigem teste novo em `tests/test_trava.py` (o que passa, o que barra, falha fechada).
- **Padrão seguro.** Novas opções nascem desligadas ou no modo mais restritivo.
- **Verifique, não suponha.** Para comportamento de janelas, áudio ou Claude, teste de verdade e registre no PR o que foi e o que não foi verificado.

## Commits
Mensagens em português, no formato `tipo: resumo` (`feat`, `fix`, `docs`, `test`, `chore`, `refactor`). Ex.: `feat: aba de tarefas na janela`.

## Overlay (Rust/Tauri)
`.\scripts\compilar-overlay.ps1`. Alterações no `Cargo.toml` devem manter o `Cargo.lock` atualizado (a CI usa `--locked`).
