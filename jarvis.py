"""Jarvis de voz: atalho -> microfone -> faster-whisper -> Claude Code (headless) -> voz SAPI.

Uso:
  pythonw jarvis.py            # servico com icone na bandeja (atalho global)
  python jarvis.py --text "pergunta"   # testa Claude + voz, sem microfone
  python jarvis.py --once              # uma rodada completa por voz, sem bandeja
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid
import winsound
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
def load_config() -> dict:
    """config.json (pessoal, fora do git); se nao existir, usa config.example.json."""
    for nome in ("config.json", "config.example.json"):
        f = BASE / nome
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    raise SystemExit("config.json nao encontrado: copie config.example.json para config.json")


CFG = load_config()


def expand_path(p: str) -> str:
    """Aceita %USERPROFILE%, ~ e variaveis de ambiente nos caminhos do config."""
    return os.path.expandvars(os.path.expanduser(p))
STATE_FILE = BASE / "state.json"
LAST_REPLY = BASE / "ultima_resposta.md"

logging.basicConfig(
    filename=str(BASE / "jarvis.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("jarvis")

SAMPLE_RATE = 16000
CHUNK = 1024
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


# ----------------------------------------------------------------- estado/sessao
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


# ----------------------------------------------------------------- audio: dispositivos
_ultimo_disp: dict[str, object] = {}


def _lista_dispositivos(recarregar: bool = False):
    """(dispositivos, apis, padrao_entrada, padrao_saida). `recarregar` relê o hardware: o PortAudio guarda a
    lista do momento em que iniciou e nao percebe fone ligado/desligado sozinho."""
    import sounddevice as sd

    if recarregar:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            log.exception("nao consegui reler os dispositivos de audio")
    devs = [dict(d, index=i) for i, d in enumerate(sd.query_devices())]
    apis = [dict(a) for a in sd.query_hostapis()]
    try:
        pad_in, pad_out = sd.default.device
    except Exception:
        pad_in = pad_out = None
    return devs, apis, (pad_in if isinstance(pad_in, int) and pad_in >= 0 else None), (pad_out if isinstance(pad_out, int) and pad_out >= 0 else None)


def dispositivos_de(tipo: str, recarregar: bool = False) -> list:
    """Ordem de tentativa para entrada/saida: o configurado (mic_device / speaker_device), o do notebook, o padrao."""
    import audio_disp

    devs, apis, pad_in, pad_out = _lista_dispositivos(recarregar)
    pref = CFG.get("mic_device" if tipo == audio_disp.ENTRADA else "speaker_device")
    lista = audio_disp.candidatos(devs, tipo, pref, pad_in if tipo == audio_disp.ENTRADA else pad_out, apis)
    escolhido = lista[0]
    if _ultimo_disp.get(tipo) != escolhido:  # registra so quando muda
        _ultimo_disp[tipo] = escolhido
        nome = next((d["name"] for d in devs if d["index"] == escolhido), "padrao do Windows")
        log.info("%s de audio: %s", "microfone" if tipo == audio_disp.ENTRADA else "alto-falante", nome)
    return lista


def abrir_entrada(**kw):
    """Abre o microfone: tenta o configurado, depois o do notebook, depois o padrao (relendo o hardware na falha)."""
    import sounddevice as sd

    ultimo: Exception | None = None
    for tentativa in (False, True):
        for dev in dispositivos_de("entrada", recarregar=tentativa):
            try:
                return sd.InputStream(device=dev, **kw)
            except Exception as e:  # PortAudioError: dispositivo sumiu, ocupado, sem permissao...
                ultimo = e
                log.warning("microfone %s indisponivel: %s", dev, e)
    raise ultimo if ultimo else RuntimeError("nenhum microfone disponivel")


def tocar(audio, sr: int) -> None:
    """Toca nao-bloqueante no alto-falante escolhido (com reserva); levanta se nenhum funcionar."""
    import sounddevice as sd

    ultimo: Exception | None = None
    for tentativa in (False, True):
        for dev in dispositivos_de("saida", recarregar=tentativa):
            try:
                sd.play(audio, sr, device=dev)
                return
            except Exception as e:
                ultimo = e
                log.warning("alto-falante %s indisponivel: %s", dev, e)
    raise ultimo if ultimo else RuntimeError("nenhum alto-falante disponivel")


# ----------------------------------------------------------------- audio: STT
_whisper = None
_whisper_lock = threading.Lock()


def get_whisper():
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel

            log.info("carregando modelo STT %s", CFG["stt_model"])
            _whisper = WhisperModel(CFG["stt_model"], device="cpu", compute_type="int8")
        return _whisper


def record_until_silence() -> np.ndarray | None:
    silence_after = 1.3
    give_up_if_no_speech = 6.0
    max_seconds = 30.0
    per_sec = SAMPLE_RATE / CHUNK

    frames: list[np.ndarray] = []
    has_speech = False
    silent_chunks = 0
    noise_samples: list[float] = []
    threshold = 400.0

    with abrir_entrada(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK,
    ) as stream:
        for i in range(int(max_seconds * per_sec)):
            data, _ = stream.read(CHUNK)
            chunk = data[:, 0].copy()
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            CURRENT["level"] = min(1.0, (rms / 2000.0) ** 0.6)  # alimenta a esfera (curva sensivel)
            if i < int(0.4 * per_sec):  # calibra ruido de fundo
                noise_samples.append(rms)
                if i == int(0.4 * per_sec) - 1:
                    threshold = max(350.0, float(np.mean(noise_samples)) * 3.0)
                continue
            if rms > threshold:
                has_speech = True
                silent_chunks = 0
            elif has_speech:
                silent_chunks += 1
                if silent_chunks >= int(silence_after * per_sec):
                    break
            elif i >= int(give_up_if_no_speech * per_sec):
                break
    CURRENT["level"] = 0.0
    if not has_speech:
        return None
    return np.concatenate(frames)


def transcribe(audio: np.ndarray) -> str:
    model = get_whisper()
    samples = audio.astype(np.float32) / 32768.0
    segments, _ = model.transcribe(
        samples, language=CFG["stt_language"], vad_filter=True, beam_size=5
    )
    return " ".join(s.text.strip() for s in segments).strip()


# ----------------------------------------------------------------- audio: TTS
_tts_proc: subprocess.Popen | None = None
_tts_lock = threading.Lock()


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[`*_#>|~]+", " ", text)
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    limit = int(CFG.get("max_spoken_chars", 700))
    if len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = (cut[: end + 1] if end > 200 else cut) + " O restante esta salvo no arquivo."
    return text


def speak_sapi(text: str) -> None:
    global _tts_proc
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        tmp = f.name
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"try{{$s.SelectVoice('{CFG['tts_voice']}')}}catch{{}};"
        f"$s.Rate={int(CFG.get('tts_rate', 0))};"
        f"$s.Speak([IO.File]::ReadAllText('{tmp}',[Text.Encoding]::UTF8))"
    )
    try:
        with _tts_lock:
            _tts_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                creationflags=NO_WINDOW,
            )
            proc = _tts_proc
        proc.wait()
    finally:
        with _tts_lock:
            _tts_proc = None
        try:
            os.unlink(tmp)
        except OSError:
            pass


_kokoro = None
_kokoro_lock = threading.Lock()
_speaking = threading.Event()
_stop = threading.Event()


def get_kokoro():
    global _kokoro
    with _kokoro_lock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro

            d = BASE / CFG.get("kokoro_dir", "models")
            log.info("carregando Kokoro (%s)", CFG.get("kokoro_voice"))
            _kokoro = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
        return _kokoro


def kokoro_style(k, spec: str):
    """'pm_alex' ou mistura 'pm_alex:0.6,pm_santa:0.4' (pesos somando ~1)."""
    if ":" not in spec and "," not in spec:
        return spec
    style = None
    for part in spec.split(","):
        name, _, w = part.partition(":")
        v = k.get_voice_style(name.strip()) * float(w or 1)
        style = v if style is None else style + v
    return style


def shape_voice(audio: np.ndarray, sr: int, pitch: float, warmth: float,
                reverb: float, pause_ms: int) -> np.ndarray:
    """Tratamento leve: tom mais grave, calor nos graves, ambiencia curta e pausa final."""
    a = audio.astype(np.float32)
    if pitch != 1.0:  # lê com passo < 1 => mais grave (e mais longo; compensado no speed)
        a = np.interp(np.arange(0, len(a), pitch), np.arange(len(a)), a).astype(np.float32)
    if warmth > 0:
        w = 10
        lp = np.convolve(a, np.ones(w, dtype=np.float32) / w, mode="same")
        a = a + warmth * lp
    if reverb > 0:
        out = a.copy()
        for ms, g in ((23, 0.35), (47, 0.22), (71, 0.13), (113, 0.07), (167, 0.04)):
            d = int(sr * ms / 1000)
            out[d:] += reverb * g * a[: len(a) - d]
        a = out
    peak = float(np.max(np.abs(a))) or 1.0
    a = a * (0.92 / peak) if peak > 0.92 else a
    if pause_ms > 0:
        a = np.concatenate([a, np.zeros(int(sr * pause_ms / 1000), dtype=np.float32)])
    return a


ENV_FPS = 25


def frame_envelope(audio: np.ndarray, sr: int) -> np.ndarray:
    """Envelope de volume (0..1) a 25 quadros/s, normalizado por trecho, para a esfera."""
    n = max(1, sr // ENV_FPS)
    frames = len(audio) // n
    if frames == 0:
        return np.zeros(1, dtype=np.float32)
    rms = np.sqrt(np.mean(audio[: frames * n].astype(np.float32).reshape(frames, n) ** 2, axis=1))
    ref = float(np.percentile(rms, 95)) or 1.0
    return np.clip(np.sqrt(rms / ref), 0.0, 1.0).astype(np.float32)


def _split_long(p: str, limit: int = 130) -> list[str]:
    """Quebra trechos longos em ; : e , para o Kokoro comecar a falar mais cedo."""
    if len(p) <= limit:
        return [p]
    for sep in (r"(?<=[;:])\s+", r"(?<=,)\s+"):
        bits = re.split(sep, p)
        if len(bits) > 1:
            out: list[str] = []
            cur = ""
            for b in bits:
                if cur and len(cur) + 1 + len(b) > limit:
                    out.append(cur)
                    cur = b
                else:
                    cur = (cur + " " + b).strip()
            if cur:
                out.append(cur)
            if len(out) > 1:
                return [x for part in out for x in _split_long(part, limit)]
    return [p]


def split_sentences(text: str) -> list[str]:
    parts = [x for p in re.split(r"(?<=[.!?])\s+", text) for x in _split_long(p)]
    if parts:  # primeiro trecho curto = a fala comeca mais cedo
        parts = _split_long(parts[0], 70) + parts[1:]
    out: list[str] = []
    for p in parts:
        if out and len(out[-1]) < 25:
            out[-1] += " " + p
        else:
            out.append(p)
    return [p for p in out if p.strip()]


def speak_kokoro(text: str) -> None:
    """Gera a proxima frase enquanto toca a atual; toque no atalho interrompe."""
    import queue
    import time

    import sounddevice as sd

    k = get_kokoro()
    voice = kokoro_style(k, CFG.get("kokoro_voice", "pm_alex"))
    pitch = float(CFG.get("kokoro_pitch", 1.0))
    speed = float(CFG.get("kokoro_speed", 0.95)) / pitch  # compensa o alongamento do pitch
    warmth = float(CFG.get("kokoro_warmth", 0.0))
    reverb = float(CFG.get("kokoro_reverb", 0.0))
    pause_ms = int(CFG.get("kokoro_pause_ms", 0))
    q: queue.Queue = queue.Queue(maxsize=2)

    def producer() -> None:
        try:
            for s in split_sentences(text):
                if _stop.is_set():
                    break
                audio, sr = k.create(s, voice=voice, speed=speed, lang="pt-br")
                audio = shape_voice(audio, sr, pitch, warmth, reverb, pause_ms)
                q.put((audio, sr))
        except Exception:
            log.exception("falha ao gerar voz Kokoro")
        finally:
            q.put(None)

    _stop.clear()
    _speaking.set()
    threading.Thread(target=producer, daemon=True).start()
    try:
        while True:
            item = q.get()
            if item is None:
                break
            if _stop.is_set():
                continue  # esvazia a fila para o produtor terminar
            audio, sr = item
            env = frame_envelope(audio, sr)
            tocar(audio, sr)
            t0 = time.time()
            end = t0 + len(audio) / sr + 0.05
            while time.time() < end and not _stop.is_set():
                i = int((time.time() - t0) * ENV_FPS)
                CURRENT["level"] = float(env[i]) if i < len(env) else 0.0  # esfera segue a voz
                time.sleep(0.03)
            if _stop.is_set():
                sd.stop()
    finally:
        CURRENT["level"] = 0.0
        _speaking.clear()


def speak(text: str) -> None:
    text = clean_for_speech(text)
    if not text:
        return
    if CFG.get("tts_engine", "sapi") == "kokoro":
        try:
            speak_kokoro(text)
            return
        except Exception:
            log.exception("Kokoro falhou; usando voz do Windows")
    speak_sapi(text)


def stop_speaking() -> bool:
    if _speaking.is_set():
        _stop.set()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        return True
    with _tts_lock:
        proc = _tts_proc
    if proc and proc.poll() is None:
        proc.kill()
        return True
    return False


# ----------------------------------------------------------------- Claude Code
def deny_list() -> list[str]:
    deny = list(CFG["deny_always"])
    # Com a confirmacao por voz, as acoes "para fora" nao somem: a trava (trava.py) as barra
    # ate o usuario confirmar. Sem ela, continuam bloqueadas de vez.
    if not CFG.get("allow_outward_actions", False) and not CFG.get("confirm_by_voice", False):
        deny += CFG["deny_outward"]
    return deny


ESTADO_DIR = BASE / ".estado"
TOKEN = ESTADO_DIR / "confirmado"


def hook_settings() -> str | None:
    """Config extra do Claude Code: roda a trava antes de cada ferramenta."""
    if CFG.get("allow_outward_actions") or not CFG.get("confirm_by_voice"):
        return None
    py = (BASE / ".venv" / "Scripts" / "python.exe").as_posix()
    trava = (BASE / "trava.py").as_posix()
    cmd = f'"{py}" "{trava}"'
    return json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}}
    )


_TOOL_LABELS = {
    "Read": "Lendo arquivo", "Glob": "Procurando arquivos", "Grep": "Procurando no conteúdo",
    "Write": "Gravando arquivo", "Edit": "Editando arquivo", "Bash": "Executando comando",
    "PowerShell": "Executando comando", "WebSearch": "Pesquisando na web", "WebFetch": "Lendo página da web",
    "Skill": "Usando uma skill", "Agent": "Delegando tarefa", "ToolSearch": "Procurando ferramenta",
    "TodoWrite": "Planejando etapas",
    "outlook_email_search": "Buscando e-mails", "outlook_calendar_search": "Consultando a agenda",
    "outlook_find_available_time": "Procurando horário livre", "outlook_create_draft": "Criando rascunho",
    "sharepoint_search": "Buscando no SharePoint", "sharepoint_folder_search": "Buscando pastas",
    "teams_list_chats": "Lendo conversas do Teams", "teams_list_channel_messages": "Lendo canal do Teams",
    "teams_list_teams": "Listando equipes", "search_people": "Buscando pessoas",
}


def tool_label(name: str) -> str:
    """Nome amigavel (em portugues) da ferramenta em uso, para a janela do Jarvis."""
    base = name.split("__")[-1]
    if base in _TOOL_LABELS:
        return _TOOL_LABELS[base]
    for key, label in (("outlook", "Outlook"), ("teams", "Teams"), ("sharepoint", "SharePoint")):
        if key in base:
            return f"{label}: {base.split('_', 1)[-1].replace('_', ' ')}"
    return "Usando " + base.replace("_", " ")


def ask_claude(text: str, confirmed: bool = False) -> str:
    state = load_state()
    sid = state.get("session_id")
    args = [
        expand_path(CFG["claude_exe"]),
        "-p",
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", CFG["permission_mode"],
        "--append-system-prompt",
        CFG["persona"].replace("{dono}", CFG.get("owner_name", "o usuario")) + tarefas_prompt(),
        "--disallowedTools", ",".join(deny_list()),
    ]
    for d in CFG.get("add_dirs", []):
        args += ["--add-dir", expand_path(d)]
    settings = hook_settings()
    if settings:
        args += ["--settings", settings]
    if sid and state.get("started"):
        args += ["--resume", sid]
    else:
        sid = sid or str(uuid.uuid4())
        args += ["--session-id", sid]

    # Usa so o login gravado do CLI: remove variaveis herdadas do app/sessao pai
    # (ex.: ANTHROPIC_BASE_URL, CLAUDE_CODE_*), mantendo um token explicito, se houver.
    keep = {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"}
    env = {
        k: v
        for k, v in os.environ.items()
        if k in keep or not re.match(r"^(CLAUDE|ANTHROPIC)", k, re.I)
    }
    log.info("pergunta: %s", text)
    from datetime import datetime

    agora = datetime.now().strftime("%A, %d/%m/%Y, %H:%M")
    # Confirmacao por voz vale so para ESTE pedido: o token e criado agora e apagado ao final.
    try:
        ESTADO_DIR.mkdir(exist_ok=True)
        if confirmed:
            TOKEN.write_text(str(time.time() + int(CFG.get("confirm_ttl_seconds", 120))))
        else:
            TOKEN.unlink(missing_ok=True)  # nunca herda token de um pedido anterior
    except OSError:
        log.exception("nao consegui preparar o token de confirmacao")
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=expand_path(CFG["workdir"]),
        env=env,
        creationflags=NO_WINDOW,
    )
    err_chunks: list[bytes] = []
    threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True).start()
    timer = threading.Timer(int(CFG.get("timeout_seconds", 300)), proc.kill)
    timer.start()
    data = None
    try:
        try:
            proc.stdin.write(f"[Hora local: {agora}]\n{text}".encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        for raw in proc.stdout:  # eventos em tempo real: ferramentas em uso + resultado final
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "assistant":
                for blk in (ev.get("message") or {}).get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "tool_use":
                        CURRENT["tools"].append(
                            {"id": blk.get("id"), "label": tool_label(blk.get("name", "")), "done": False}
                        )
            elif kind == "user":
                for blk in (ev.get("message") or {}).get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "tool_result":
                        for t in CURRENT["tools"]:
                            if t["id"] == blk.get("tool_use_id"):
                                t["done"] = True
            elif kind == "result":
                data = ev
    finally:
        timer.cancel()
        proc.wait()
        try:
            TOKEN.unlink(missing_ok=True)
        except OSError:
            pass
    err = b"".join(err_chunks).decode("utf-8", errors="replace").strip()
    if data is None:
        log.error("claude falhou (%s): %s", proc.returncode, err[:500])
        return "Nao consegui falar com o Claude. Veja o arquivo de log."
    state.update(session_id=data.get("session_id", sid), started=True)
    save_state(state)
    result = (data.get("result") or "").strip()
    log.info("resposta: %s", result[:500])
    if not result:
        result = "Terminei, mas nao tenho nada para dizer."
    try:
        LAST_REPLY.write_text(f"## {text}\n\n{result}\n", encoding="utf-8")
    except OSError:
        pass
    return result


# ----------------------------------------------------------------- fluxo
_busy = threading.Lock()
_status_cb = lambda s: None  # noqa: E731  (trocado pela bandeja)


def beep(freq: int, ms: int = 110) -> None:
    """Bip pelo alto-falante escolhido (o winsound usa so o padrao do Windows, que pode ser um dispositivo virtual)."""
    try:
        sr = 24000
        t = np.arange(int(sr * ms / 1000)) / sr
        env = np.minimum(1.0, np.minimum(t, t[-1] - t) / 0.008)  # entrada/saida suaves: sem estalo
        tocar((0.25 * np.sin(2 * np.pi * freq * t) * env).astype(np.float32), sr)
        time.sleep(ms / 1000)
    except Exception:
        try:
            winsound.Beep(freq, ms)
        except RuntimeError:
            pass


_lista_tarefas = None


def tarefas_lista():
    """Lista de tarefas (tarefas.py); criada uma vez, o arquivo e relido a cada uso."""
    global _lista_tarefas
    if _lista_tarefas is None:
        import tarefas

        _lista_tarefas = tarefas.lista_padrao()
    return _lista_tarefas


def tarefas_prompt() -> str:
    """Ensina o Claude a usar a MESMA lista (pedidos que a fala imediata nao entende)."""
    py = (BASE / ".venv" / "Scripts" / "python.exe").as_posix()
    script = (BASE / "tarefas.py").as_posix()
    return (
        f' LISTA DE TAREFAS: a lista de tarefas do usuario e gerenciada pelo comando "{py}" "{script}" com as acoes '
        'add "texto" [--prazo AAAA-MM-DD] [--prio alta|media|baixa], prazo REF AAAA-MM-DD|nenhum, list, done REF, '
        "remove REF e undo (REF = numero na lista de abertas ou um trecho do texto). Use SEMPRE esse comando para ler "
        "ou alterar tarefas e nunca edite os arquivos de tarefas diretamente. Converta datas faladas para AAAA-MM-DD "
        "usando a hora local informada e confirme em uma frase o que foi feito. Ao criar uma tarefa SEM data, termine "
        "a resposta perguntando 'Para quando?' (responder e opcional: se o usuario disser a data, use o comando prazo; "
        "se disser 'sem data', nao faca nada)."
    )


def responder_prazo_pendente(texto: str) -> str | None:
    """Resposta a "Para quando?" (perguntado ao anotar uma tarefa sem data). None = nao era resposta."""
    try:
        import tarefas

        return tarefas.responder_prazo(texto, tarefas_lista())
    except Exception:
        log.exception("erro ao tratar a data da tarefa")
        return None


def responder_tarefas(texto: str) -> str | None:
    """Comando de tarefas por voz tratado na hora, sem o Claude. None = nao e comando de tarefas."""
    try:
        import tarefas

        return tarefas.responder(texto, tarefas_lista())
    except Exception:
        log.exception("erro na lista de tarefas")
        return None


_pending_until = 0.0  # ate quando o Jarvis aguarda um "confirma" do usuario

_AFIRMA = {"sim", "confirma", "confirmo", "confirmado", "pode", "manda", "mande", "envia", "envie", "faz",
           "faca", "execute", "executa", "autorizo", "positivo", "isso", "ok", "okay", "claro", "vai", "certo"}
_NEGA = {"nao", "cancela", "cancelar", "cancele", "negativo", "pare", "para", "espera", "aguarde", "deixa",
         "esquece", "nunca", "jamais"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def classify_confirmation(text: str) -> str | None:
    """'sim', 'nao' ou None. So frases curtas; qualquer negacao vence (lado seguro)."""
    words = _norm(text).split()
    if not words or len(words) > 6:
        return None
    if any(w in _NEGA for w in words):
        return "nao"
    if any(w in _AFIRMA for w in words):
        return "sim"
    return None


def asks_confirmation(reply: str) -> bool:
    return "confirma" in _norm(reply[-120:])


def handle_text(text: str) -> None:
    global _pending_until
    low = text.lower().strip(" .!?")
    if low in {"cancelar", "cancela", "esquece", "deixa pra la", "deixa pra lá"}:
        _pending_until = 0.0
        tarefas_lista().pendente_prazo = None
        speak("Cancelado, senhor.")
        return
    if low in {"nova conversa", "reiniciar conversa", "limpar conversa"}:
        _pending_until = 0.0
        save_state({})
        add_history(marker="Nova conversa")
        speak("Conversa reiniciada, senhor.")
        return
    # Se o Jarvis acabou de pedir "Confirma, senhor?", "sim/confirma" libera so aquela acao
    confirm = classify_confirmation(text) if time.time() < _pending_until else None
    _pending_until = 0.0
    if confirm == "nao":
        add_history(pergunta=text, resposta="Cancelado, senhor.")
        speak("Cancelado, senhor.")
        return
    if confirm is None:  # comandos de tarefas: resposta imediata, sem gastar uma chamada ao Claude
        local, rotulo = responder_prazo_pendente(text), "Lista de tarefas"  # "Para quando?" acabou de ser perguntado?
        if local is None:
            local = responder_tarefas(text)
        if local is None:
            local, rotulo = responder_musica(text), "Música"
        if local is not None:
            CURRENT.update(heard=text, reply=local, tools=[{"id": "local", "label": rotulo, "done": True}])
            add_history(pergunta=text, resposta=local)
            _status_cb("speaking")
            log.info("tarefa (local): %s -> %s", text, local)
            speak(local)
            return
    prompt, confirmed = text, False
    if confirm == "sim":
        prompt = ("[CONFIRMADO pelo senhor por voz: execute agora a acao que voce acabou de propor, "
                  "e somente ela.] " + text)
        confirmed = True
        log.info("confirmacao por voz recebida: %s", text)
    CURRENT.update(heard=text, reply="", tools=[])
    _status_cb("thinking")
    # tique sonoro enquanto o Claude trabalha, para saber que ele ouviu e esta processando
    done = threading.Event()
    interval = float(CFG.get("thinking_beep_seconds", 5))

    def ticker() -> None:
        beep(520, 70)
        while not done.wait(interval):
            beep(520, 70)

    threading.Thread(target=ticker, daemon=True).start()
    try:
        reply = ask_claude(prompt, confirmed=confirmed)
    finally:
        done.set()
    add_history(pergunta=text, resposta=reply)
    if asks_confirmation(reply):  # aguarda o "confirma" no proximo pedido
        _pending_until = time.time() + int(CFG.get("confirm_ttl_seconds", 120))
        log.info("aguardando confirmacao por voz")
    CURRENT["reply"] = reply[:900]
    _status_cb("speaking")
    log.info("falando resposta (%d chars)", len(reply))
    speak(reply)
    log.info("fala concluida")


def voice_round() -> None:
    if not _busy.acquire(blocking=False):
        return
    try:
        _status_cb("listening")
        beep(880)
        audio = record_until_silence()
        beep(660)
        if audio is None:
            return
        _status_cb("transcribing")
        CURRENT.update(heard="", reply="", tools=[])
        text = transcribe(audio)
        log.info("ouvi: %s", text)
        if len(text) < 2:
            return
        handle_text(text)
    except Exception:
        log.exception("erro na rodada de voz")
        try:
            speak("Tive um erro. Veja o log.")
        except Exception:
            pass
    finally:
        _status_cb("idle")
        _busy.release()


def painel_hotkey() -> None:
    """Abre/fecha o painel rapido. Sem o app flutuante (overlay), abre a mesma pagina no navegador."""
    if overlay_running():
        painel_alternar()
    else:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{HISTORY_PORT}/painel")


def on_hotkey() -> None:
    if stop_speaking():  # segundo toque interrompe a fala
        return
    threading.Thread(target=voice_round, daemon=True).start()


# ----------------------------------------------------------------- historico + janela local
HISTORY = BASE / "historico.jsonl"
VIEWER = BASE / "historico.html"
HISTORY_PORT = int(CFG.get("history_port", 8765))
CURRENT: dict = {"state": "idle", "level": 0.0, "tools": [], "heard": "", "reply": "", "rev": 0,
                 "painel": False, "esfera_visivel": True, "painel_reset": 0}
_hist_lock = threading.Lock()


def add_history(pergunta: str = "", resposta: str = "", marker: str = "") -> None:
    from datetime import datetime

    entry = {"ts": datetime.now().isoformat(timespec="seconds")}
    if marker:
        entry["marker"] = marker
    else:
        entry.update(pergunta=pergunta, resposta=resposta)
    try:
        with _hist_lock, HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        CURRENT["rev"] += 1  # avisa a janela que o historico mudou
    except OSError:
        log.exception("nao consegui gravar o historico")


def read_history(limit: int = 500) -> list[dict]:
    try:
        lines = HISTORY.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


# ----------------------------------------------------------------- painel rapido (widgets flutuantes)
def painel_cfg() -> dict:
    return CFG.get("painel", {})


def musica_cfg() -> dict:
    return painel_cfg().get("musica", {})


def musica_ligada() -> bool:
    return bool(musica_cfg().get("enabled", True))


def responder_musica(texto: str) -> str | None:
    """Comando de musica por voz tratado na hora ("pausa a musica", "proxima musica", "o que esta tocando")."""
    if not musica_ligada():
        return None
    try:
        import musica

        return musica.responder(texto)
    except Exception:
        log.exception("erro no controle de musica")
        return None


PAINEL_GEOM = ESTADO_DIR / "painel_geometria.json"


def painel_geom_ler() -> dict | None:
    """Onde o usuario deixou o painel (x, y, largura, altura em pixels fisicos). None = posicao padrao."""
    try:
        g = json.loads(PAINEL_GEOM.read_text(encoding="utf-8"))
        return g if painel_geom_valida(g) else None
    except (OSError, ValueError):
        return None


def painel_geom_valida(g) -> bool:
    try:
        x, y, w, h = (g[k] for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError):
        return False
    return (all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y, w, h))
            and -20000 <= x <= 20000 and -20000 <= y <= 20000 and 300 <= w <= 10000 and 300 <= h <= 10000)


def painel_geom_salvar(g: dict) -> bool:
    if not painel_geom_valida(g):
        return False
    try:
        ESTADO_DIR.mkdir(exist_ok=True)
        PAINEL_GEOM.write_text(json.dumps({k: g[k] for k in ("x", "y", "w", "h")}), encoding="utf-8")
        return True
    except OSError:
        log.exception("nao consegui salvar a posicao do painel")
        return False


def painel_geom_resetar() -> None:
    """Volta o painel ao canto e ao tamanho padrao (o app Tauri percebe pelo contador 'reset')."""
    PAINEL_GEOM.unlink(missing_ok=True)
    CURRENT["painel_reset"] = CURRENT.get("painel_reset", 0) + 1


def painel_alternar(mostrar: bool | None = None) -> bool:
    CURRENT["painel"] = (not CURRENT.get("painel")) if mostrar is None else bool(mostrar)
    if CURRENT["painel"]:
        try:  # o Windows so deixa o painel (outro processo) pegar o foco se este processo autorizar
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
        except Exception:
            pass
    return bool(CURRENT["painel"])


def atalhos_painel() -> list[dict]:
    """Atalhos do painel: acoes internas + apps/links do config. O navegador so recebe id/nome, nunca o alvo."""
    internos = [
        {"id": "falar", "nome": "Falar", "icone": "mic"},
        {"id": "nova_conversa", "nome": "Nova conversa", "icone": "chat"},
        {"id": "janela", "nome": "Janela", "icone": "window"},
        {"id": "esfera", "nome": "Esfera", "icone": "orb"},
    ]
    extras = [{"id": a["id"], "nome": a.get("nome", a["id"]), "icone": a.get("icone", "app")}
              for a in painel_cfg().get("atalhos", []) if a.get("id")]
    return internos + extras


def abrir_atalho(item: dict) -> dict:
    tipo, alvo = item.get("tipo"), str(item.get("alvo", ""))
    if tipo == "url":
        if not re.match(r"^https?://", alvo, re.I):
            return {"ok": False, "erro": "so http(s)"}
        import webbrowser

        webbrowser.open(alvo)
    elif tipo == "app":
        if alvo.lower().startswith("shell:"):
            subprocess.Popen(["explorer.exe", alvo], creationflags=NO_WINDOW)
        else:
            os.startfile(expand_path(alvo))
    else:
        return {"ok": False, "erro": "tipo desconhecido"}
    return {"ok": True}


_esfera_demo_ate = 0.0


def esfera_alternar() -> bool:
    """Liga/desliga a esfera flutuante. Ao ligar, ela aparece alguns segundos para voce ver que funcionou
    (fora isso ela so surge quando o Jarvis esta ouvindo, pensando ou falando)."""
    global _esfera_demo_ate
    ligada = not CURRENT.get("esfera_visivel", True)
    CURRENT["esfera_visivel"] = ligada
    _esfera_demo_ate = time.time() + 3.5 if ligada else 0.0
    return ligada


def executar_acao(acao: str) -> dict:
    """Acoes do painel. So aceita ids conhecidos (internos ou definidos no config): nunca um alvo vindo do navegador."""
    if acao == "falar":
        painel_alternar(False)
        threading.Timer(0.4, on_hotkey).start()  # deixa o painel sumir antes de abrir o microfone
    elif acao == "nova_conversa":
        save_state({})
        add_history(marker="Nova conversa")
    elif acao == "janela":
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{HISTORY_PORT}")
    elif acao == "esfera":
        ligada = esfera_alternar()
        return {"ok": True, "mensagem": "Esfera ligada: aparece quando o Jarvis estiver em ação." if ligada else "Esfera desligada."}
    elif acao == "configurar":  # tile "Adicionar" do painel: abre o config.json para editar os atalhos
        alvo = BASE / "config.json"
        os.startfile(str(alvo if alvo.exists() else BASE / "config.example.json"))
    else:
        item = next((a for a in painel_cfg().get("atalhos", []) if a.get("id") == acao), None)
        if not item:
            return {"ok": False, "erro": "atalho desconhecido"}
        return abrir_atalho(item)
    return {"ok": True}


_cpu_prev: tuple | None = None


def sistema_info() -> dict:
    """CPU, memoria e tempo ligado, sem dependencias (API do Windows)."""
    import ctypes
    import ctypes.wintypes as wt

    global _cpu_prev

    class FT(ctypes.Structure):
        _fields_ = [("lo", wt.DWORD), ("hi", wt.DWORD)]

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    k32 = ctypes.windll.kernel32
    idle, kern, user = FT(), FT(), FT()
    k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    cur = tuple((f.hi << 32) | f.lo for f in (idle, kern, user))
    cpu = 0.0
    if _cpu_prev:
        di, dk, du = (cur[i] - _cpu_prev[i] for i in range(3))
        total = dk + du  # o tempo de "kernel" ja inclui o ocioso
        cpu = max(0.0, min(100.0, (total - di) * 100.0 / total)) if total else 0.0
    _cpu_prev = cur
    ms = MS()
    ms.dwLength = ctypes.sizeof(MS)
    k32.GlobalMemoryStatusEx(ctypes.byref(ms))
    k32.GetTickCount64.restype = ctypes.c_ulonglong
    return {"cpu": round(cpu), "mem": int(ms.dwMemoryLoad), "uptime_s": int(k32.GetTickCount64() // 1000)}


def start_history_server() -> None:
    """Janela de historico em http://127.0.0.1:PORT (somente local)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    allowed_hosts = {f"127.0.0.1:{HISTORY_PORT}", f"localhost:{HISTORY_PORT}"}

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            # bloqueia DNS rebinding: so aceita Host local
            if self.headers.get("Host", "") not in allowed_hosts:
                return self._send(403, b"forbidden", "text/plain")
            path = self.path.split("?")[0]
            if path == "/":
                try:
                    return self._send(200, VIEWER.read_bytes(), "text/html; charset=utf-8")
                except OSError:
                    return self._send(404, b"historico.html ausente", "text/plain")
            if path == "/overlay":  # so a esfera, transparente, para a janela flutuante (Tauri)
                try:
                    return self._send(200, (BASE / "overlay.html").read_bytes(), "text/html; charset=utf-8")
                except OSError:
                    return self._send(404, b"overlay.html ausente", "text/plain")
            if path == "/api/history":
                data = json.dumps(read_history(), ensure_ascii=False).encode("utf-8")
                return self._send(200, data, "application/json; charset=utf-8")
            if path == "/painel":  # painel de widgets (janela flutuante do overlay Tauri ou navegador)
                try:
                    return self._send(200, (BASE / "painel.html").read_bytes(), "text/html; charset=utf-8")
                except OSError:
                    return self._send(404, b"painel.html ausente", "text/plain")
            if path == "/api/painel":
                dados = {"show": bool(CURRENT.get("painel")), "corner": painel_cfg().get("corner", "tr"),
                         "geom": painel_geom_ler(), "reset": CURRENT.get("painel_reset", 0)}
                return self._send(200, json.dumps(dados).encode(), "application/json")
            if path == "/api/musica":
                if not musica_ligada():
                    dados = {"disponivel": False, "ativo": False, "motivo": "desligado no config"}
                else:
                    import musica

                    dados = musica.snapshot(musica_cfg().get("app", "Spotify"))
                return self._send(200, json.dumps(dados, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            if path == "/api/musica/capa":
                import musica

                capa = musica.capa_bytes() if musica_ligada() else None
                if not capa:
                    return self._send(404, b"sem capa", "text/plain")
                return self._send(200, capa[0], capa[1])
            if path == "/api/sistema":
                return self._send(200, json.dumps(sistema_info()).encode(), "application/json")
            if path == "/api/atalhos":
                return self._send(200, json.dumps(atalhos_painel(), ensure_ascii=False).encode("utf-8"),
                                  "application/json; charset=utf-8")
            if path == "/api/tarefas":
                lista = tarefas_lista()
                ab = [{"n": i, "id": t["id"], "texto": t["texto"], "prazo": t.get("prazo"),
                       "prioridade": t.get("prioridade", "media")} for i, t in enumerate(lista.abertas(), 1)]
                conc = [{"id": t["id"], "texto": t["texto"], "concluida": t.get("concluida")}
                        for t in lista.recentes_concluidas(8)]
                return self._send(200, json.dumps({"abertas": ab, "concluidas": conc}, ensure_ascii=False).encode("utf-8"),
                                  "application/json; charset=utf-8")
            if path == "/api/status":
                CURRENT["pending"] = time.time() < _pending_until  # aguardando "confirma"?
                CURRENT["esfera_demo"] = time.time() < _esfera_demo_ate  # acabou de ligar a esfera: mostra um instante
                return self._send(200, json.dumps(CURRENT).encode(), "application/json")
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("Host", "") not in allowed_hosts:
                return self._send(403, b"forbidden", "text/plain")
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self._send(415, b"json only", "text/plain")  # forca preflight CORS
            corpo: dict = {}
            try:  # sempre le o corpo (senao o cliente recebe a conexao anulada); aceita so JSON pequeno
                bruto = self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 4096))
                corpo = json.loads(bruto or b"{}")
            except (ValueError, OSError):
                corpo = {}
            path = self.path.split("?")[0]
            if path == "/api/hotkey":  # clicar na esfera = apertar o atalho
                threading.Thread(target=on_hotkey, daemon=True).start()
                return self._send(200, b'{"ok":true}', "application/json")
            if path == "/api/tarefas/concluir":  # marcar na janela = "conclua a tarefa"
                try:
                    lista = tarefas_lista()
                    alvo = next(t for t in lista.abertas() if t["id"] == int(corpo.get("id")))
                    lista.concluir(alvo)
                    CURRENT["rev"] += 1
                    return self._send(200, b'{"ok":true}', "application/json")
                except (StopIteration, TypeError, ValueError):
                    return self._send(404, b'{"ok":false}', "application/json")
            if path == "/api/painel/geometria":  # o app Tauri avisa quando voce move/redimensiona
                ok = painel_geom_salvar(corpo)
                return self._send(200 if ok else 400, json.dumps({"ok": ok}).encode(), "application/json")
            if path == "/api/painel/resetar":
                painel_geom_resetar()
                return self._send(200, b'{"ok":true}', "application/json")
            if path in ("/api/painel/alternar", "/api/painel/fechar"):
                painel_alternar(None if path.endswith("alternar") else False)
                return self._send(200, b'{"ok":true}', "application/json")
            if path == "/api/musica/acao":
                if not musica_ligada():
                    return self._send(404, b'{"ok":false}', "application/json")
                import musica

                r = musica.acao(str(corpo.get("acao", ""))[:20], musica_cfg().get("app", "Spotify"))
                return self._send(200 if r.get("ok") else 404, json.dumps(r).encode(), "application/json")
            if path == "/api/acao":
                r = executar_acao(str(corpo.get("acao", ""))[:40])
                return self._send(200 if r.get("ok") else 404, json.dumps(r).encode(), "application/json")
            if path == "/api/tarefas/adicionar":
                import tarefas

                lista = tarefas_lista()
                prazo, aviso = None, None  # prazo: None = ainda nao escolheu; "" = sem data; AAAA-MM-DD = essa data
                if "quando" in corpo:  # resposta de "Para quando?": "amanha", "sexta", "25/12", "" (= sem data)...
                    quando = str(corpo.get("quando") or "")[:40].strip()
                    r = tarefas.interpretar_prazo(quando, lista.agora().date()) if quando else ("sem", None)
                    if r is None:
                        aviso = "Não entendi a data. Tente: amanhã, sexta, 25/12 ou sem data."
                    else:
                        prazo = r[1] or ""
                if aviso:
                    return self._send(200, json.dumps({"ok": True, "mensagem": aviso, "pergunta": True, "erro": True}, ensure_ascii=False).encode("utf-8"),
                                      "application/json; charset=utf-8")
                msg, mudou, pergunta = tarefas.entrada_do_painel(lista, str(corpo.get("texto", ""))[:300], prazo)
                if mudou:
                    CURRENT["rev"] += 1
                return self._send(200, json.dumps({"ok": True, "mensagem": msg, "pergunta": pergunta}, ensure_ascii=False).encode("utf-8"),
                                  "application/json; charset=utf-8")
            if path == "/api/tarefas/remover":
                try:
                    lista = tarefas_lista()
                    alvo = next(t for t in lista.abertas() if t["id"] == int(corpo.get("id")))
                    lista.remover(alvo)
                    CURRENT["rev"] += 1
                    return self._send(200, b'{"ok":true}', "application/json")
                except (StopIteration, TypeError, ValueError):
                    return self._send(404, b'{"ok":false}', "application/json")
            if path == "/api/tarefas/desfazer":
                ok = tarefas_lista().desfazer()
                CURRENT["rev"] += 1
                return self._send(200, json.dumps({"ok": ok}).encode(), "application/json")
            self._send(404, b"not found", "text/plain")

        def log_message(self, *a) -> None:  # silencia o log do http.server
            pass

    try:
        class Servidor(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):  # navegador/WebView que fecha a aba nao e erro
                import sys

                if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                    return
                log.exception("erro no servidor local")

        srv = Servidor(("127.0.0.1", HISTORY_PORT), H)
    except OSError:
        log.exception("porta %s indisponivel para o historico", HISTORY_PORT)
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("historico em http://127.0.0.1:%s", HISTORY_PORT)


# ----------------------------------------------------------------- atalho global (pelo proprio Windows)
_VK = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
       **{f"f{i}": 0x6F + i for i in range(1, 25)}}
_MOD = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8, "windows": 0x8}
_hk_thread_ids: list[int] = []


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+j' -> (modificadores com MOD_NOREPEAT, codigo da tecla virtual)."""
    mods, vk = 0x4000, None
    for p in (x.strip().lower() for x in spec.split("+")):
        if p in _MOD:
            mods |= _MOD[p]
        elif p in _VK:
            vk = _VK[p]
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        else:
            raise ValueError(f"tecla desconhecida no atalho: {p!r}")
    if vk is None or mods == 0x4000:
        raise ValueError("o atalho precisa de ao menos um modificador (ctrl/alt/shift/win) e uma tecla")
    return mods, vk


def start_hotkey(spec: str, callback, hk_id: int = 1) -> bool:
    """Registra o atalho com RegisterHotKey (sem gancho global de teclado). True se registrou."""
    import ctypes
    import ctypes.wintypes as wt

    mods, vk = parse_hotkey(spec)
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    resultado: dict = {}
    pronto = threading.Event()

    def loop() -> None:
        _hk_thread_ids.append(kernel32.GetCurrentThreadId())
        ok = bool(user32.RegisterHotKey(None, hk_id, mods, vk))
        resultado["ok"] = ok
        pronto.set()
        if not ok:
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                try:
                    callback()
                except Exception:
                    log.exception("erro no atalho")
        user32.UnregisterHotKey(None, hk_id)

    threading.Thread(target=loop, daemon=True).start()
    pronto.wait(5)
    return bool(resultado.get("ok"))


def stop_hotkey() -> None:
    import ctypes

    for tid in _hk_thread_ids:
        ctypes.windll.user32.PostThreadMessageW(tid, 0x0012, 0, 0)  # WM_QUIT


# ----------------------------------------------------------------- overlay flutuante (Tauri)
OVERLAY_EXE_NAME = "jarvis-overlay.exe"
_overlay_started_by_us = False


def overlay_exe() -> Path:
    rel = CFG.get("overlay", {}).get("exe", "overlay/src-tauri/target/release/jarvis-overlay.exe")
    return BASE / rel


def overlay_running() -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {OVERLAY_EXE_NAME}", "/NH"], capture_output=True, creationflags=NO_WINDOW
    ).stdout.decode("utf-8", errors="replace")
    return OVERLAY_EXE_NAME.lower() in out.lower()


def overlay_start() -> bool:
    global _overlay_started_by_us
    exe = overlay_exe()
    if not exe.exists():
        log.warning("overlay nao encontrado: %s", exe)
        return False
    if overlay_running():
        return True
    c = CFG.get("overlay", {})
    args = [str(exe), "--corner", str(c.get("corner", "br")), "--size", str(c.get("size", 420)),
            "--margin", str(c.get("margin", 24))]
    env = {k: v for k, v in os.environ.items() if not re.match(r"^(CLAUDE|ANTHROPIC)", k, re.I)}
    subprocess.Popen(args, cwd=str(exe.parent), env=env, creationflags=NO_WINDOW)
    _overlay_started_by_us = True
    log.info("overlay iniciado: %s", " ".join(args[1:]))
    return True


def overlay_stop() -> None:
    subprocess.run(["taskkill", "/IM", OVERLAY_EXE_NAME, "/F"], capture_output=True, creationflags=NO_WINDOW)
    log.info("overlay encerrado")


# ----------------------------------------------------------------- iniciar com o Windows (atalho em Inicializar)
def startup_lnk() -> Path:
    """Atalho na pasta Inicializar do usuario (o mesmo que o Jarvis ja criou por voz)."""
    custom = CFG.get("autostart_lnk")
    if custom:
        return Path(custom)
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Jarvis.lnk"


def autostart_enabled() -> bool:
    return startup_lnk().exists()


def autostart_enable() -> bool:
    lnk = startup_lnk()
    alvo = BASE / "iniciar-jarvis.cmd"
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.WindowStyle=7;"
        "$s.Description='Jarvis (assistente de voz)';$s.Save()" % (lnk, alvo, BASE)
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        log.error("falha ao criar o atalho de inicializacao: %s", r.stderr.decode("utf-8", errors="replace")[:300])
    return r.returncode == 0 and lnk.exists()


def autostart_disable() -> bool:
    try:
        startup_lnk().unlink(missing_ok=True)
        return True
    except OSError:
        log.exception("falha ao remover o atalho de inicializacao")
        return False


_mutex_handle = None


def single_instance() -> bool:
    """False se ja existe outro Jarvis rodando (evita dois servicos, dois atalhos, dois overlays)."""
    global _mutex_handle
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = k32.CreateMutexW(None, False, "Local\\JarvisVozAssistente")
    return k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


# ----------------------------------------------------------------- bandeja
def run_tray() -> None:
    import pystray
    from PIL import Image, ImageDraw

    colors = {
        "idle": (30, 120, 220),
        "listening": (40, 200, 90),
        "thinking": (240, 190, 40),
        "speaking": (0, 210, 230),
    }

    def make_icon(state: str) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        color = colors.get(state, colors["thinking"])  # "transcribing" usa a cor de "pensando"
        d.ellipse((6, 6, 58, 58), fill=color + (255,), outline=(255, 255, 255, 255), width=3)
        d.ellipse((24, 24, 40, 40), fill=(255, 255, 255, 255))
        return img

    icon = pystray.Icon("jarvis", make_icon("idle"), f"Jarvis ({CFG['hotkey']})")

    def set_status(s: str) -> None:
        CURRENT["state"] = s
        icon.icon = make_icon(s)

    global _status_cb
    _status_cb = set_status

    def falar(_i=None, _it=None):
        on_hotkey()

    def nova(_i=None, _it=None):
        save_state({})
        add_history(marker="Nova conversa")

    def abrir_log(_i=None, _it=None):
        os.startfile(str(BASE / "jarvis.log"))

    def abrir_historico(_i=None, _it=None):
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{HISTORY_PORT}")

    def alternar_overlay(_i=None, _it=None):
        esfera_alternar()

    def abrir_painel(_i=None, _it=None):
        painel_hotkey()

    def restaurar_painel(_i=None, _it=None):
        painel_geom_resetar()

    def alternar_inicio(_i=None, _it=None):
        autostart_disable() if autostart_enabled() else autostart_enable()

    def sair(i, _it=None):
        stop_hotkey()
        if _overlay_started_by_us:
            overlay_stop()
        i.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(f"Falar agora ({CFG['hotkey']})", falar),
        pystray.MenuItem(f"Painel rápido ({painel_cfg().get('hotkey', 'ctrl+alt+t')})", abrir_painel),
        pystray.MenuItem("Restaurar posição do painel", restaurar_painel),
        pystray.MenuItem("Mostrar esfera", alternar_overlay, checked=lambda _it: CURRENT.get("esfera_visivel", True)),
        pystray.MenuItem("Abrir histórico", abrir_historico),
        pystray.MenuItem("Nova conversa", nova),
        pystray.MenuItem("Iniciar com o Windows", alternar_inicio, checked=lambda _it: autostart_enabled()),
        pystray.MenuItem("Abrir log", abrir_log),
        pystray.MenuItem("Sair", sair),
    )

    start_history_server()
    try:
        if not start_hotkey(CFG["hotkey"], on_hotkey):
            log.error("nao consegui registrar o atalho %s (ja usado por outro programa?)", CFG["hotkey"])
            icon.title = f"Jarvis - ATALHO {CFG['hotkey']} INDISPONIVEL"
    except ValueError:
        log.exception("atalho invalido: %s", CFG["hotkey"])
    if CFG.get("overlay", {}).get("enabled", True):
        overlay_start()
    if painel_cfg().get("enabled", True):
        try:
            if start_hotkey(painel_cfg().get("hotkey", "ctrl+alt+t"), painel_hotkey, hk_id=2):
                log.info("atalho do painel registrado: %s", painel_cfg().get("hotkey", "ctrl+alt+t"))
            else:
                log.error("nao consegui registrar o atalho do painel %s (ja usado por outro programa?)",
                          painel_cfg().get("hotkey", "ctrl+alt+t"))
        except ValueError:
            log.exception("atalho do painel invalido")
    threading.Thread(target=get_whisper, daemon=True).start()  # aquece o STT
    if CFG.get("tts_engine") == "kokoro":
        threading.Thread(target=get_kokoro, daemon=True).start()  # aquece a voz
    if CFG.get("greet_on_start"):
        threading.Thread(target=lambda: speak("Jarvis online."), daemon=True).start()
    log.info("Jarvis ativo. Atalho: %s", CFG["hotkey"])
    icon.run()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="envia texto direto ao Claude e fala a resposta")
    ap.add_argument("--no-speak", action="store_true")
    ap.add_argument("--once", action="store_true", help="uma rodada por voz, sem bandeja")
    args = ap.parse_args()

    if args.text:
        reply = ask_claude(args.text)
        print(reply)
        if not args.no_speak:
            speak(reply)
        return
    if args.once:
        voice_round()
        return
    if not single_instance():
        log.info("ja existe outro Jarvis em execucao; encerrando este")
        return
    run_tray()


if __name__ == "__main__":
    main()
