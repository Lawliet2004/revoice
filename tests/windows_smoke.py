"""Exercise the Windows dashboard with synthetic audio and a local provider."""

import json
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from revoice_app import speech
from revoice_app.config import Store
from revoice_app.windows import Dashboard
from revoice_app.windows_desktop import WindowsDesktop, single_instance


class TranscriptionHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        audio = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.received.append(audio)
        body = json.dumps({"text": "Revoice test ✓ नमस्ते"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class InputStream:
    def __init__(self, *, samplerate, channels, dtype, blocksize, callback):
        assert samplerate in (16000, 48000)
        assert (channels, dtype, blocksize) == (1, "int16", samplerate // 10)
        self.callback = callback
        self.blocksize = blocksize
        self.active = False

    def start(self):
        self.active = True
        for _ in range(4):
            self.callback(b"\x00\x05" * self.blocksize, self.blocksize, None, SimpleNamespace(input_overflow=False))

    def close(self):
        self.active = False


def test_single_instance():
    if os.name == "nt":
        with single_instance() as first, single_instance() as second:
            assert first and not second
        with single_instance() as restarted:
            assert restarted


def test_dashboard(native_rate=16000, native_shortcut=False):
    def stream(**options):
        if options["samplerate"] != native_rate:
            raise ValueError("Device only supports its native sample rate")
        return InputStream(**options)

    fake_sounddevice = SimpleNamespace(
        RawInputStream=stream, PortAudioError=Exception, CallbackStop=Exception, CallbackAbort=Exception,
        query_devices=lambda **_options: {"default_samplerate": native_rate},
    )
    with ThreadingHTTPServer(("127.0.0.1", 0), TranscriptionHandler) as server, tempfile.TemporaryDirectory() as folder:
        server.received = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        data = Path(folder)
        store = Store(data / "settings.json", data / "history.json")
        store.set("provider", "openai")
        root = tk.Tk()
        desktop = Mock()
        factory = WindowsDesktop if native_shortcut else lambda _emit: desktop
        with patch.dict(sys.modules, sounddevice=fake_sounddevice), patch.object(
            speech, "API_URL", f"http://127.0.0.1:{server.server_port}/",
        ):
            app = Dashboard(root, store, desktop_factory=factory)
            try:
                app.api_key.set("")
                app.toggle()
                assert app.state == "idle" and "API key" in app.status.get()
                app.api_key.set("synthetic-key")
                app.record_button.invoke()
                assert app.state == "recording"
                app.record_button.invoke()
                assert app.state == "processing"
                deadline = time.monotonic() + 8
                while app.state != "idle" and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.025)
                assert app.state == "idle", "Transcription timed out"
                assert app.transcript.get("1.0", "end-1c") == "Revoice test ✓ नमस्ते", app.status.get()
                assert Store(store.settings_path, store.history_path).history[0]["text"] == "Revoice test ✓ नमस्ते"
                assert b"RIFF" in server.received[0] and b"gpt-transcribe" in server.received[0]
                assert store.history[0]["duration"] > .39
                if native_shortcut:
                    assert app.shortcut.get() == f"{WindowsDesktop.HOTKEY} starts and stops recording.", app.shortcut.get()
                    app.copy()
                    assert root.clipboard_get() == "Revoice test ✓ नमस्ते"
                app.record_button.invoke()
                app.cancel_button.invoke()
                assert app.state == "idle" and "cancelled" in app.status.get()
            finally:
                app.close()
                server.shutdown()
                thread.join(3)


if __name__ == "__main__":
    test_single_instance()
    test_dashboard(native_shortcut=os.name == "nt")
    test_dashboard(native_rate=48000)
    print("Windows dashboard, synthetic recording, transcription, and persistence passed.")
