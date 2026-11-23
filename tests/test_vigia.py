"""O vigia (reabre o Jarvis se cair) e o registro de quedas: consistencia entre os arquivos, sem iniciar nada."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jarvis  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def test_scripts_do_vigia_sao_ascii_puro():
    # O PowerShell 5.1 le .ps1 sem BOM como ANSI: acento viraria lixo. Mantemos ASCII.
    for nome in ("scripts/vigia.ps1", "scripts/vigia.vbs", "iniciar-jarvis.cmd"):
        dados = (RAIZ / nome).read_bytes()
        assert all(b < 128 for b in dados), f"{nome} tem caractere fora do ASCII"


def test_vigia_e_o_jarvis_usam_o_mesmo_arquivo_de_sair():
    assert jarvis.SAIR_FLAG.name == "sair" and jarvis.SAIR_FLAG.parent.name == ".estado"
    ps = (RAIZ / "scripts" / "vigia.ps1").read_text(encoding="ascii")
    cmd = (RAIZ / "iniciar-jarvis.cmd").read_text(encoding="ascii")
    assert r".estado\sair" in ps and r".estado\sair" in cmd                         # o vigia respeita o "Sair"; o cmd limpa a marca


def test_iniciar_abre_o_jarvis_e_o_vigia():
    cmd = (RAIZ / "iniciar-jarvis.cmd").read_text(encoding="ascii")
    assert "jarvis.py" in cmd and "vigia.vbs" in cmd
    vbs = (RAIZ / "scripts" / "vigia.vbs").read_text(encoding="ascii")
    assert "vigia.ps1" in vbs and ", 0, False" in vbs                               # sem janela, sem esperar


def test_vigia_limita_as_reaberturas_e_registra_no_log():
    ps = (RAIZ / "scripts" / "vigia.ps1").read_text(encoding="ascii")
    assert "-ge 5" in ps and "jarvis.log" in ps and "Local\\JarvisVigia" in ps       # 5 quedas/10 min, log e instancia unica
