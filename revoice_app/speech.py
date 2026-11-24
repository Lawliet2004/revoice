"""PipeWire capture and speech providers. Worker callbacks carry no credentials."""

import base64
import io
import json
import math
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from array import array

from websockets.exceptions import ConnectionClosed, InvalidHandshake, WebSocketException

from .config import valid_text

try:
    from websockets.sync.client import connect
except ImportError:
    from .websocket_compat import connect

RATE = 16_000
BYTES_PER_SECOND = RATE * 2
CHUNK = BYTES_PER_SECOND // 10
SEGMENT_SECONDS = 240
SEGMENT_BYTES = SEGMENT_SECONDS * BYTES_PER_SECOND
PAUSE_SPLIT_BYTES = (SEGMENT_SECONDS - 15) * BYTES_PER_SECOND
BUFFERED_CHUNKS = (SEGMENT_SECONDS + 60) * BYTES_PER_SECOND // CHUNK
STREAM_URL = "wss://chatgpt.com/backend-api/dictation/stream"
API_URL = "https://api.openai.com/v1/audio/transcriptions"
CLAUDE_VOICE = "wss://api.anthropic.com/api/ws/speech_to_text/voice_stream"
CLAUDE_AGENT = "claude-cli/2.1.72 (external, cli)"
CLAUDE_QUIET = 1.5
KEEPALIVE_SECONDS = 8


class SpeechError(Exception):
    pass


class Cancelled(Exception):
    pass


def level(pcm):
    if len(pcm) % 2:
        pcm = pcm[:-1]
    values = array("h", pcm)
    if not values:
        return 0.0
    rms = math.sqrt(sum(sample * sample for sample in values) / len(values))
    return min(1.0, math.sqrt(rms / 3800))


class Recording:
    def __init__(self, settings, credential, emit):
        self.settings = settings.copy()
        self.credential = credential
        self.emit = emit
        self.audio = queue.Queue()
        self.cancelled = threading.Event()
        self.stopping = threading.Event()
        self.process = None
        self.capture_error = None
        self.byte_count = 0
        self.confirmed = False

    def start(self, provisional=False):
        # The "-" destination streams PCM, including on versions without a --raw option.
        args = ["pw-record", "--rate", str(RATE), "--channels", "1",
                "--format", "s16", "--latency", "40ms", "--media-role", "Communication"]
        if self.settings["device"]:
            args.append("--target=" + self.settings["device"])
        args.append("-")
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if not provisional:
            self.confirm()
        threading.Thread(target=self.capture, daemon=True).start()

    def confirm(self):
        # A KDE modifier chord may become another shortcut. Buffer locally until
        # KDE confirms the matching release, then allow audio to reach the provider.
        if self.confirmed or self.cancelled.is_set():
            return
        self.confirmed = True
        threading.Thread(target=self.transcribe, daemon=True).start()

    def capture(self):
        try:
            while not self.stopping.is_set():
                pcm = self.process.stdout.read(CHUNK)
                if not pcm:
                    if not self.stopping.is_set():
                        self.capture_error = "The microphone stopped. Check your input in Settings."
                    break
                if self.audio.qsize() >= BUFFERED_CHUNKS:
                    self.capture_error = ("Transcription couldn’t keep up with the recording." if self.confirmed
                                          else "Double-press your shortcut for longer recordings.")
                    break
                self.byte_count += len(pcm)
                self.audio.put(pcm)
                self.emit("level", level(pcm))
        except OSError:
            self.capture_error = "The microphone stopped. Check your input in Settings."
        finally:
            if self.capture_error and not self.confirmed and not self.cancelled.is_set():
                self.emit("error", self.capture_error)
            self.audio.put(None)
            self.process.stdout.close()
            if self.process.poll() is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass
            self.process.wait()

    def stop(self):
        self.stopping.set()
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass

    def cancel(self):
        self.cancelled.set()
        self.stop()

    def transcribe(self):
        completed = ""

        def finalized(text):
            nonlocal completed
            completed = text

        try:
            provider = self.settings["provider"]
            args = (self.audio, self.credential, self.settings["language"], self.cancelled,
                    lambda text: self.emit("partial", text), finalized)
            if provider == "codex":
                result = codex_dictate(*args)
            elif provider == "claude":
                result = claude_dictate(*args)
            else:
                result = api_segments(self.audio, self.credential, self.settings["language"], self.cancelled, finalized)
            if self.cancelled.is_set():
                raise Cancelled
            if self.capture_error:
                raise SpeechError(self.capture_error)
            if not result.strip():
                raise SpeechError("No speech was detected.")
            self.emit("result", result.strip(), self.byte_count / BYTES_PER_SECOND)
            return
        except Cancelled:
            return
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            message = http_error_message(status)
        except InvalidHandshake as error:
            status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
            message = http_error_message(status) if status else "The provider couldn’t establish a dictation connection."
        except SpeechError as error:
            message = str(error)
        except (OSError, ValueError, RuntimeError, WebSocketException) as error:
            message = f"Couldn’t reach the transcription service ({type(error).__name__})."
        if not self.cancelled.is_set():
            message = self.capture_error or message
            if completed:
                self.emit("error", message, completed, self.byte_count / BYTES_PER_SECOND)
            else:
                self.emit("error", message)


def http_error_message(status):
    if status in (401, 403):
        return "The service declined the connection. Reconnect in Settings."
    if status == 429:
        return "The provider’s usage limit was reached. Try again later."
    return f"The transcription service returned HTTP {status}."


def codex_dictate(audio, token, language, cancelled, partial, finalized=None):
    """Rotate before the provider's session expires and join its confirmed segments."""
    transcripts = []
    finished = False
    while not finished and not cancelled.is_set():
        first = audio.get()
        if first is None:
            break
        def finalize_session(text):
            if finalized:
                finalized(" ".join(part for part in (*transcripts, text) if part))

        text, finished = codex_session(audio, first, token, language, cancelled, partial, finalize_session)
        if text:
            transcripts.append(text)
    if cancelled.is_set():
        raise Cancelled
    return " ".join(transcripts)


def codex_session(audio, pcm, token, language, cancelled, partial, finalized):
    if cancelled.is_set():
        raise Cancelled
    config = {
        "input_audio_format": "pcm16", "sample_rate_hz": RATE, "num_channels": 1,
        "max_buffer_size_bytes": 4 * 1024 * 1024, "max_utterance_duration_ms": 30_000,
        "session_ttl_ms": 300_000, "provider_mode": "streaming_sse",
        "transcript_delivery_mode": "segment", "session_asset_mode": "none",
        "vad": {"type": "server_vad", "threshold": 0.5,
                "prefix_padding_ms": 300, "silence_duration_ms": 500},
    }
    if language:
        config["language"] = language
    agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    with connect(STREAM_URL, subprotocols=["chatgpt-dictation", "openai-bearer." + token],
                 user_agent_header=agent, open_timeout=8, close_timeout=1) as socket:
        def send(event, **fields):
            socket.send(json.dumps({"type": event, **fields}, separators=(",", ":")))

        def receive(timeout):
            try:
                event = json.loads(socket.recv(timeout=timeout))
            except TimeoutError:
                return {}
            except ValueError:
                raise SpeechError("Codex returned an invalid dictation response.") from None
            if not isinstance(event, dict):
                raise SpeechError("Codex returned an invalid dictation response.")
            return event

        send("session.start", config=config)
        order = {}
        finals = {}
        active = {}
        closed = False

        def handle(event):
            nonlocal closed
            kind = event.get("type")
            key = event.get("utterance_id") or ""
            if kind in ("session.error", "transcript.failed", "error"):
                details = event.get("error")
                code = details.get("code") if isinstance(details, dict) else None
                if code in ("unauthorized", "invalid_token", "permission_denied"):
                    raise SpeechError("Codex sign-in expired or was declined. Reconnect in Settings.")
                raise SpeechError("Codex couldn’t finish this dictation. Try a new recording.")
            if kind in ("speech.started", "transcript.segment", "transcript.final"):
                if not isinstance(key, str):
                    raise SpeechError("Codex returned an invalid dictation response.")
                order.setdefault(key, None)
            text = event.get("text")
            if kind in ("transcript.segment", "transcript.final") and not valid_text(text):
                raise SpeechError("Codex returned an invalid transcript.")
            if kind == "transcript.segment" and key not in finals:
                active[key] = text
                partial(" ".join((finals.get(item) or active.get(item, "")).strip() for item in order).strip())
            if kind == "transcript.final":
                finals[key] = text.strip()
                active.pop(key, None)
                finalized(" ".join(finals[item] for item in order if finals.get(item)))
            if kind == "session.updated" and event.get("status") == "closed":
                closed = True

        deadline = time.monotonic() + 8
        while True:
            if cancelled.is_set():
                raise Cancelled
            event = receive(0.1)
            handle(event)
            if event.get("type") == "session.started":
                break
            if time.monotonic() >= deadline:
                raise SpeechError("Codex took too long to start dictation.")

        rotate_at = time.monotonic() + SEGMENT_SECONDS
        finished = False
        session_bytes = bytes_since_flush = 0
        quiet_chunks = 0
        while not cancelled.is_set():
            if pcm is None:
                finished = True
                break
            if pcm:
                send("audio.append", audio=base64.b64encode(pcm).decode("ascii"))
                session_bytes += len(pcm)
                bytes_since_flush += len(pcm)
                quiet_chunks = quiet_chunks + 1 if level(pcm) < 0.26 else 0
                if bytes_since_flush >= BYTES_PER_SECOND * 40 or (
                    bytes_since_flush >= BYTES_PER_SECOND * 22 and quiet_chunks >= 4
                ):
                    send("audio.flush", reason="client")
                    bytes_since_flush = 0
            event = receive(0)
            while event:
                handle(event)
                if closed:
                    raise SpeechError("Codex closed the session while you were recording.")
                event = receive(0)
            if (time.monotonic() >= rotate_at or session_bytes >= SEGMENT_BYTES
                    or (session_bytes >= PAUSE_SPLIT_BYTES and quiet_chunks >= 4)):
                break
            try:
                pcm = audio.get(timeout=.025)
            except queue.Empty:
                pcm = b""
        if cancelled.is_set():
            raise Cancelled
        if bytes_since_flush:
            send("audio.flush", reason="client")
        send("session.close")
        deadline = time.monotonic() + 20
        while not closed and not cancelled.is_set():
            if time.monotonic() > deadline:
                raise SpeechError("Codex timed out while finishing the transcript.")
            try:
                handle(receive(0.1))
            except ConnectionClosed as error:
                if error.rcvd and error.rcvd.code == 1000 and not active:
                    break
                raise SpeechError("The dictation connection closed before the transcript was ready.") from None
        if cancelled.is_set():
            raise Cancelled
        if active:
            raise SpeechError("Codex closed the session before all transcript segments were ready.")
        return " ".join(finals[item] for item in order if finals.get(item)), finished


def connect_headers(url, headers, **options):
    agent = headers.get("User-Agent")
    extra = [(key, value) for key, value in headers.items() if key.lower() != "user-agent"]
    try:
        return connect(url, additional_headers=extra, user_agent_header=agent, **options)
    except TypeError:
        return connect(url, extra_headers=dict(headers), **options)


def claude_dictate(audio, token, language, cancelled, partial, finalized=None):
    """Stream PCM to Claude Code's speech service and join its finished utterances."""
    transcripts = []
    finished = False
    while not finished and not cancelled.is_set():
        first = audio.get()
        if first is None:
            break

        def finalize_session(text, earlier=tuple(transcripts)):
            if finalized:
                finalized(" ".join(part for part in (*earlier, text) if part))

        text, finished = claude_session(audio, first, token, language, cancelled, partial, finalize_session)
        if text:
            transcripts.append(text)
    if cancelled.is_set():
        raise Cancelled
    return " ".join(transcripts)


def claude_session(audio, pcm, token, language, cancelled, partial, finalized):
    if cancelled.is_set():
        raise Cancelled
    params = {"encoding": "linear16", "sample_rate": RATE, "channels": 1,
              "endpointing_ms": 300, "utterance_end_ms": 1000}
    if language:
        params["language"] = language
    url = CLAUDE_VOICE + "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": "Bearer " + token, "User-Agent": CLAUDE_AGENT, "x-app": "cli"}
    committed = []
    interim = ""
    with connect_headers(url, headers, open_timeout=8, close_timeout=1, ping_interval=None) as socket:
        def send_json(payload):
            socket.send(json.dumps(payload, separators=(",", ":")))

        def receive(timeout):
            try:
                message = socket.recv(timeout=timeout)
            except TimeoutError:
                return {}
            if isinstance(message, (bytes, bytearray)):
                return {}
            try:
                event = json.loads(message)
            except ValueError:
                raise SpeechError("Claude returned an invalid dictation response.") from None
            if not isinstance(event, dict):
                raise SpeechError("Claude returned an invalid dictation response.")
            return event

        def publish():
            partial(" ".join(part for part in (*committed, interim) if part).strip())
            if finalized:
                finalized(" ".join(committed))

        def handle(event):
            nonlocal interim
            kind = event.get("type")
            if kind in ("TranscriptError", "error"):
                details = event.get("error")
                code = event.get("error_code") or (details.get("code") if isinstance(details, dict) else None)
                if code in ("unauthorized", "invalid_token", "permission_denied"):
                    raise SpeechError("Claude sign-in expired or was declined. Reconnect in Settings.")
                raise SpeechError("Claude couldn’t finish this dictation. Try a new recording.")
            if kind == "TranscriptText":
                text = event.get("data") if "data" in event else event.get("text")
                if text in ("", None):
                    interim = ""
                elif not valid_text(text):
                    raise SpeechError("Claude returned an invalid transcript.")
                else:
                    interim = text.strip()
                publish()
            elif kind == "TranscriptEndpoint" and interim:
                committed.append(interim)
                interim = ""
                publish()

        send_json({"type": "KeepAlive"})
        keepalive = rotate_at = time.monotonic()
        rotate_at += SEGMENT_SECONDS
        finished = False
        session_bytes = 0
        quiet_chunks = 0
        while not cancelled.is_set():
            if pcm is None:
                finished = True
                break
            if pcm:
                socket.send(pcm)
                session_bytes += len(pcm)
                quiet_chunks = quiet_chunks + 1 if level(pcm) < 0.26 else 0
            if time.monotonic() - keepalive >= KEEPALIVE_SECONDS:
                send_json({"type": "KeepAlive"})
                keepalive = time.monotonic()
            event = receive(0)
            while event:
                handle(event)
                event = receive(0)
            if (time.monotonic() >= rotate_at or session_bytes >= SEGMENT_BYTES
                    or (session_bytes >= PAUSE_SPLIT_BYTES and quiet_chunks >= 4)):
                break
            try:
                pcm = audio.get(timeout=.025)
            except queue.Empty:
                pcm = b""
        if cancelled.is_set():
            raise Cancelled
        send_json({"type": "CloseStream"})
        deadline = time.monotonic() + 5
        quiet_since = time.monotonic()
        while time.monotonic() < deadline and not cancelled.is_set():
            event = receive(0.1)
            if not event:
                if time.monotonic() - quiet_since >= CLAUDE_QUIET:
                    break
                continue
            quiet_since = time.monotonic()
            handle(event)
        if cancelled.is_set():
            raise Cancelled
        if interim:
            committed.append(interim)
            publish()
        return " ".join(committed), finished


def api_segments(audio, key, language, cancelled, finalized=None):
    transcripts = []
    block = bytearray()
    quiet_chunks = 0
    while not cancelled.is_set():
        pcm = audio.get()
        if cancelled.is_set():
            break
        if pcm is not None:
            block.extend(pcm)
            if len(block) >= PAUSE_SPLIT_BYTES:
                quiet_chunks = quiet_chunks + 1 if level(pcm) < 0.26 else 0
            if len(block) < SEGMENT_BYTES and quiet_chunks < 4:
                continue
        if block:
            text = api_dictate(block, key, language).strip()
            if text:
                transcripts.append(text)
                if finalized:
                    finalized(" ".join(transcripts))
            block.clear()
            quiet_chunks = 0
        if pcm is None:
            return " ".join(transcripts)
    raise Cancelled


def api_dictate(pcm, key, language):
    if len(pcm) < RATE // 3:
        return ""
    recording = io.BytesIO()
    with wave.open(recording, "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    boundary = uuid.uuid4().hex
    body = bytearray()
    fields = {"model": "gpt-transcribe"}
    if language:
        fields["language"] = language
    for name, value in fields.items():
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="dictation.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
    body.extend(recording.getvalue())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(API_URL, data=bytes(body), headers={
        "Authorization": "Bearer " + key, "Content-Type": "multipart/form-data; boundary=" + boundary,
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        try:
            payload = json.load(response)
        except ValueError:
            raise SpeechError("OpenAI returned an invalid transcription response.") from None
    if not isinstance(payload, dict) or not valid_text(payload.get("text")):
        raise SpeechError("OpenAI returned an invalid transcription response.")
    return payload["text"]
