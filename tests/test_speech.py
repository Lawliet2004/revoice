import base64
import io
import json
import queue
import threading
import unittest
from urllib.error import HTTPError
from collections import deque
from unittest.mock import patch

from revoice_app import speech


def audio_queue(*chunks):
    audio = queue.Queue()
    for chunk in (*chunks, None):
        audio.put(chunk)
    return audio


class DictationSocket:
    def __init__(self, transcript):
        self.transcript = transcript
        self.events = deque()
        self.chunks = []
        self.flushed = False

    def __enter__(self):
        return self

    def __exit__(self, *_failure):
        pass

    def send(self, message):
        event = json.loads(message)
        kind = event["type"]
        if kind == "session.start":
            self.events.append({"type": "session.started"})
        elif kind == "audio.append":
            self.chunks.append(base64.b64decode(event["audio"]))
        elif kind == "audio.flush":
            self.flushed = True
        elif kind == "session.close":
            self.events.append({"type": "transcript.final", "utterance_id": "1", "text": self.transcript})
            self.events.append({"type": "session.updated", "status": "closed"})

    def recv(self, timeout):
        if not self.events:
            raise TimeoutError
        return json.dumps(self.events.popleft())


class ContinuousDictationTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [bytes((value, 0)) * (speech.CHUNK // 2) for value in range(1, 6)]
        self.cancelled = threading.Event()

    def test_codex_rollover_keeps_all_audio_and_final_text_in_order(self):
        sockets = [DictationSocket("First part."), DictationSocket("Second part."), DictationSocket("Last part.")]
        with patch.object(speech, "SEGMENT_BYTES", 2 * speech.CHUNK), patch.object(
            speech, "connect", side_effect=sockets,
        ):
            text = speech.codex_dictate(audio_queue(*self.chunks), "test", "", self.cancelled, lambda _: None)
        self.assertEqual(text, "First part. Second part. Last part.")
        self.assertEqual([socket.chunks for socket in sockets],
                         [self.chunks[:2], self.chunks[2:4], self.chunks[4:]])
        self.assertTrue(all(socket.flushed for socket in sockets))

    def test_codex_release_on_a_boundary_finishes_without_an_empty_session(self):
        with patch.object(speech, "SEGMENT_BYTES", 2 * speech.CHUNK), patch.object(
            speech, "connect", return_value=DictationSocket("Finished."),
        ) as connect:
            self.assertEqual(
                speech.codex_dictate(audio_queue(*self.chunks[:2]), "test", "", self.cancelled, lambda _: None),
                "Finished.",
            )
            connect.assert_called_once()

    def test_api_batches_long_audio_and_includes_the_final_short_segment(self):
        submitted = []

        def transcribe(pcm, _key, _language):
            submitted.append(bytes(pcm))
            return f"Part {len(submitted)}."

        with patch.object(speech, "SEGMENT_BYTES", 2 * speech.CHUNK), patch.object(
            speech, "api_dictate", side_effect=transcribe,
        ):
            text = speech.api_segments(audio_queue(*self.chunks), "test", "en", self.cancelled)
        self.assertEqual(text, "Part 1. Part 2. Part 3.")
        self.assertEqual(submitted, [b"".join(self.chunks[:2]), b"".join(self.chunks[2:4]), self.chunks[4]])

    def test_cancelled_recordings_do_not_open_a_connection(self):
        self.cancelled.set()
        with patch.object(speech, "connect") as connect, patch.object(speech, "api_dictate") as transcribe:
            with self.assertRaises(speech.Cancelled):
                speech.codex_dictate(audio_queue(*self.chunks), "test", "", self.cancelled, lambda _: None)
            with self.assertRaises(speech.Cancelled):
                speech.api_segments(audio_queue(*self.chunks), "test", "", self.cancelled)
            connect.assert_not_called()
            transcribe.assert_not_called()

    def test_api_later_failure_reports_completed_text(self):
        recording, events = self.recording("openai")
        unavailable = HTTPError("https://example.invalid", 503, "Unavailable", {}, None)
        with patch.object(speech, "SEGMENT_BYTES", speech.CHUNK), patch.object(
            speech, "api_dictate", side_effect=["Completed text.", unavailable],
        ):
            recording.transcribe()
        self.assertEqual(events, [("error", "The transcription service returned HTTP 503.", "Completed text.", .2)])

    def test_api_malformed_response_reports_an_error(self):
        for body in (b'{"text": null}', b'[]', b'{"text": 123}', b'invalid', b'{}', b'{"text": "\\ud800"}'):
            recording, events = self.recording("openai")
            with self.subTest(body=body), patch.object(speech.urllib.request, "urlopen", return_value=io.BytesIO(body)):
                recording.transcribe()
                self.assertEqual(events, [("error", "OpenAI returned an invalid transcription response.")])

    def test_codex_session_error_preserves_finalized_utterances(self):
        recording, events = self.recording("codex")
        socket = DictationSocket("Completed text.")
        send = socket.send

        def fail_after_final(message):
            send(message)
            if json.loads(message)["type"] == "session.close":
                socket.events.pop()
                socket.events.append({"type": "transcript.failed", "error": None})

        with patch.object(speech, "connect", return_value=socket), patch.object(socket, "send", fail_after_final):
            recording.transcribe()
        self.assertEqual(events[0][0], "error")
        self.assertEqual(events[0][2:], ("Completed text.", .2))

    def test_codex_later_connection_failure_preserves_completed_session(self):
        recording, events = self.recording("codex")
        with patch.object(speech, "SEGMENT_BYTES", speech.CHUNK), patch.object(
            speech, "connect", side_effect=[DictationSocket("Completed session."), OSError()],
        ):
            recording.transcribe()
        self.assertEqual(events[0][0], "error")
        self.assertEqual(events[0][2:], ("Completed session.", .2))

    def recording(self, provider):
        events = []
        recording = speech.Recording({"provider": provider, "language": ""}, "test", lambda *event: events.append(event))
        recording.audio = audio_queue(*self.chunks[:2])
        recording.byte_count = len(self.chunks[:2]) * speech.CHUNK
        return recording, events


if __name__ == "__main__":
    unittest.main()
