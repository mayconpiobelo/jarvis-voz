"""Laboratorio de voz do Jarvis (temporario): http://127.0.0.1:8766

Gera o audio com o MESMO Kokoro e o MESMO tratamento do Jarvis (jarvis.py),
entao o que voce ouve aqui e exatamente o que ele fala. So aceita acesso local.

Uso:  .venv\\Scripts\\python.exe voz_lab.py      (encerra pelo botao da pagina)
"""
from __future__ import annotations

import io
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import jarvis  # noqa: E402

PORT = 8766
PAGE = BASE / "voz_lab.html"
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
VOICE_RE = re.compile(r"^[a-z]{2}_[a-z]+(:[0-9.]+)?(,[a-z]{2}_[a-z]+(:[0-9.]+)?)*$")

_synth_lock = threading.Lock()
_cache: dict[str, bytes] = {}


def clamp(v, lo, hi, default):
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return default


def synth(p: dict) -> bytes:
    k = jarvis.get_kokoro()
    voices = set(k.get_voices())
    spec = str(p.get("voice", "pm_alex"))
    if not VOICE_RE.match(spec) or any(n.split(":")[0] not in voices for n in spec.split(",")):
        raise ValueError("voz invalida")
    lang = p.get("lang", "pt-br")
    if lang not in ("pt-br", "en-gb"):
        raise ValueError("idioma invalido")
    text = str(p.get("text", "")).strip()[:600]
    if not text:
        raise ValueError("texto vazio")
    speed = clamp(p.get("speed"), 0.6, 1.3, 0.9)
    pitch = clamp(p.get("pitch"), 0.8, 1.1, 1.0)
    warmth = clamp(p.get("warmth"), 0.0, 0.8, 0.0)
    reverb = clamp(p.get("reverb"), 0.0, 0.6, 0.0)
    pause = int(clamp(p.get("pause"), 0, 600, 0))

    key = json.dumps([text, spec, lang, speed, pitch, warmth, reverb, pause], sort_keys=True)
    if key in _cache:
        return _cache[key]

    with _synth_lock:
        style = jarvis.kokoro_style(k, spec)
        chunks, sr = [], 24000
        for s in jarvis.split_sentences(text):
            a, sr = k.create(s, voice=style, speed=speed / pitch, lang=lang)
            chunks.append(jarvis.shape_voice(a, sr, pitch, warmth, reverb, pause))
        audio = np.concatenate(chunks)
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    data = buf.getvalue()
    if len(_cache) > 60:
        _cache.pop(next(iter(_cache)))
    _cache[key] = data
    return data


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in ALLOWED_HOSTS  # evita DNS rebinding

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/voices":
            names = sorted(n for n in jarvis.get_kokoro().get_voices() if n[:2] in ("pf", "pm", "bf", "bm"))
            return self._send(200, json.dumps(names).encode(), "application/json")
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        path = self.path.split("?")[0]
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self._send(415, b"json only", "text/plain")  # forca preflight CORS
        if path == "/api/quit":
            self._send(200, b'{"ok":true}', "application/json")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/tts":
            try:
                n = int(self.headers.get("Content-Length", "0"))
                params = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
                wav = synth(params)
            except ValueError as e:
                return self._send(400, json.dumps({"erro": str(e)}).encode(), "application/json")
            except Exception as e:  # noqa: BLE001
                jarvis.log.exception("voz_lab: falha ao sintetizar")
                return self._send(500, json.dumps({"erro": str(e)}).encode(), "application/json")
            return self._send(200, wav, "audio/wav")
        self._send(404, b"not found", "text/plain")

    def log_message(self, *a) -> None:
        pass


def main() -> None:
    threading.Thread(target=jarvis.get_kokoro, daemon=True).start()  # aquece o modelo
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Laboratorio de voz em http://127.0.0.1:{PORT}", flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
