"""Impede que dados pessoais ou segredos entrem no repositorio. Varre os arquivos versionados."""
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
ESTE = Path(__file__).resolve()

# Padroes que nunca devem aparecer em arquivo versionado (montados para este arquivo nao se auto-acusar).
PADROES = {
    "caminho de usuario do Windows": re.compile(r"[A-Za-z]:\\+Users\\+(?!Public|Default|%|<|seu)[A-Za-z0-9._-]+", re.I),
    "e-mail corporativo": re.compile(r"[\w.+-]+@(?:[\w-]+\.)*" + "dbs" + "tec" + r"\.com\.br", re.I),
    "nome do dono": re.compile("may" + "con|pio" + "belo", re.I),
    "empresa": re.compile("dbs" + r"\s?tec", re.I),
    "chave de API da Anthropic": re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    "token do GitHub": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "chave AWS": re.compile(r"AKIA[0-9A-Z]{16}"),
    "token do Slack": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
}
TEXTO = {".py", ".md", ".json", ".html", ".toml", ".txt", ".yml", ".yaml", ".rs", ".ps1", ".cmd", ".cfg", ".gitignore"}


def arquivos_versionados() -> list[Path]:
    try:
        saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("nao e um repositorio git")
    return [RAIZ / f for f in saida.splitlines() if f]


def test_nenhum_arquivo_versionado_tem_dado_pessoal_ou_segredo():
    achados = []
    for f in arquivos_versionados():
        if f.resolve() == ESTE or not f.is_file() or (f.suffix.lower() not in TEXTO and f.name not in TEXTO):
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        for nome, rx in PADROES.items():
            m = rx.search(txt)
            if m:
                achados.append(f"{f.relative_to(RAIZ)}: {nome} ({m.group(0)[:30]!r})")
    assert not achados, "dados pessoais/segredos versionados:\n" + "\n".join(achados)


def test_arquivos_pessoais_nao_estao_versionados():
    versionados = {f.relative_to(RAIZ).as_posix() for f in arquivos_versionados()}
    for pessoal in ("config.json", "tarefas.json", "TAREFAS.md", "historico.jsonl", "state.json", "jarvis.log"):
        assert pessoal not in versionados, f"{pessoal} nao pode ir para o git"
    assert not any(p.startswith((".estado/", "models/")) for p in versionados)
