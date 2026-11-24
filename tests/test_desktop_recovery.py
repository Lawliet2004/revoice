import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from revoice_app import __main__ as revoice
from revoice_app import config, desktop


class DesktopRecoveryTests(unittest.TestCase):
    def test_bad_history_entries_and_settings_keep_valid_saved_data(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.json"
            history = Path(folder) / "history.json"
            settings.write_text(json.dumps({"language": 123, "hold": False, "provider": "unknown", "auto_paste": 1}))
            history.write_text(json.dumps([
                None, {"text": 123}, {"text": "\ud800"}, {"text": "Preserved", "duration": "invalid"},
                {"text": "Also preserved", "duration": 1.75},
            ]))
            with patch.multiple(config, SETTINGS=settings, HISTORY=history):
                store = config.Store()
            saved = json.loads(history.read_text())
        self.assertEqual(store.settings["language"], "")
        self.assertEqual(store.settings["provider"], "codex")
        self.assertIs(store.settings["hold"], False)
        self.assertIs(store.settings["auto_paste"], True)
        self.assertEqual([row["text"] for row in store.history], ["Preserved", "Also preserved"])
        self.assertEqual([row["duration"] for row in store.history], [0, 1.75])
        self.assertTrue(all(row.get("at") for row in store.history))
        self.assertEqual([row["text"] for row in saved], ["Preserved", "Also preserved"])
        self.assertTrue(all(set(row) <= {"text", "duration", "at"} for row in saved))

    def test_fresh_library_file_drops_audio_and_junk_without_waiting_for_expiry(self):
        fresh = (datetime.now() - timedelta(days=1)).replace(microsecond=0).isoformat(timespec="seconds")
        with tempfile.TemporaryDirectory() as folder:
            history = Path(folder) / "history.json"
            settings = Path(folder) / "settings.json"
            history.write_text(json.dumps([
                {"text": "keep me", "duration": 1, "at": fresh, "audio": "must-not-persist"},
                None,
                {"text": 5},
            ]))
            with patch.multiple(config, SETTINGS=settings, HISTORY=history):
                store = config.Store()
            saved = json.loads(history.read_text())
        self.assertEqual(store.history, [{"text": "keep me", "duration": 1, "at": fresh}])
        self.assertEqual(saved, store.history)

    def test_text_library_keeps_three_days_and_drops_the_recording(self):
        now = datetime(2026, 11, 23, 12, 0, 0)
        old = (now - timedelta(days=3, minutes=1)).isoformat(timespec="seconds")
        fresh = (now - timedelta(days=2)).isoformat(timespec="seconds")
        with tempfile.TemporaryDirectory() as folder:
            history = Path(folder) / "history.json"
            settings = Path(folder) / "settings.json"
            history.write_text(json.dumps([
                {"text": "old words", "duration": 2, "at": old, "audio": "must-not-persist"},
                {"text": "fresh words", "duration": 1, "at": fresh},
            ]))
            with patch.multiple(config, SETTINGS=settings, HISTORY=history):
                store = config.Store()
                store.add("newer words", 0.5)
                saved = json.loads(history.read_text())
        self.assertEqual([row["text"] for row in saved], ["newer words", "fresh words"])
        self.assertTrue(all(set(row) <= {"text", "duration", "at"} for row in saved))
        self.assertEqual(config.connection_label("claude", True), "Connected via Claude")
        self.assertEqual(config.connection_label("codex", False), "Sign in to Codex")
        self.assertEqual(config.kept_until(fresh, now), "Removed tomorrow")

    def test_claude_login_refreshes_without_leaking_the_new_token_into_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".credentials.json"
            path.write_text(json.dumps({
                "claudeAiOauth": {"accessToken": "old-access", "refreshToken": "old-refresh", "expiresAt": 1},
                "other": {"kept": True},
            }))

            def opener(request, timeout=20):
                body = json.loads(request.data.decode())
                self.assertEqual(body["refresh_token"], "old-refresh")
                self.assertEqual(body["client_id"], config.CLAUDE_CLIENT_ID)
                payload = json.dumps({
                    "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600,
                }).encode()
                return io.BytesIO(payload)

            self.assertEqual(config.claude_token(str(path), opener=opener), "new-access")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["other"], {"kept": True})
            self.assertEqual(saved["claudeAiOauth"]["accessToken"], "new-access")
            self.assertEqual(saved["claudeAiOauth"]["refreshToken"], "new-refresh")
            self.assertGreater(saved["claudeAiOauth"]["expiresAt"], 1_000_000_000_000)

            def reject(request, timeout=20):
                raise urllib.error.HTTPError(config.CLAUDE_TOKEN_URL, 401, "no", {}, io.BytesIO(b"secret-body"))

            path.write_text(json.dumps({
                "claudeAiOauth": {"accessToken": "old-access", "refreshToken": "old-refresh", "expiresAt": 1},
            }))
            with self.assertRaises(ValueError) as failure:
                config.claude_token(str(path), opener=reject)
            self.assertNotIn("secret-body", str(failure.exception))
            self.assertNotIn("new-access", str(failure.exception))

    def test_fresh_claude_token_is_reused_and_env_token_is_a_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".credentials.json"
            expires = int(datetime.now().timestamp() * 1000) + 3_600_000
            path.write_text(json.dumps({
                "claudeAiOauth": {"accessToken": "still-good", "refreshToken": "refresh", "expiresAt": expires},
            }))

            def opener(*_args, **_kwargs):
                raise AssertionError("A current Claude sign-in should not be refreshed")

            self.assertEqual(config.claude_token(str(path), opener=opener), "still-good")
            self.assertTrue(config.claude_available(str(path)))
            with patch.object(config, "candidate_claude_logins", return_value=[Path(folder) / "missing.json"]):
                with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "env-token"}, clear=False):
                    self.assertEqual(config.claude_token(""), "env-token")
                with patch.dict("os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": ""}, clear=False):
                    with self.assertRaisesRegex(ValueError, "Connect your Claude"):
                        config.claude_token("")

    def test_browser_forms_keep_the_transcript_on_the_clipboard_longer(self):
        self.assertGreater(desktop.clipboard_grace("google-chrome"), desktop.clipboard_grace("org.kde.kate"))
        self.assertEqual(desktop.clipboard_grace("firefox"), desktop.BROWSER_PASTE_GRACE)
        self.assertEqual(desktop.clipboard_grace("konsole"), desktop.PASTE_CLIPBOARD_GRACE)

    def test_partial_transcript_updates_the_open_field(self):
        window = Mock()
        app = SimpleNamespace(
            generation=1, recording=Mock(), state="recording", live_text="", draft_timer=0, window=window,
        )
        revoice.App.handle(app, 1, "partial", ("Hello from voice",))
        self.assertEqual(app.live_text, "Hello from voice")
        window.refresh_home.assert_called_once()
        revoice.App.clear_draft_timer(app)
        app.state = "idle"
        revoice.App.handle(app, 1, "partial", ("ignored",))
        self.assertEqual(app.live_text, "Hello from voice")

    def test_unverified_target_blocks_paste_regardless_of_desktop(self):
        focus = SimpleNamespace(window=("", ""), locked=False)
        paste = desktop.Paste(focus)
        with patch.object(desktop, "KDE", False):
            with self.assertRaisesRegex(desktop.ClipboardError, "couldn’t verify"):
                paste.check_target(focus.window, lambda: True)
        with patch.object(desktop, "KDE", True):
            focus.window = ("active", "example")
            paste.check_target(focus.window, lambda: True)

    def test_external_kde_shortcut_can_change_after_an_unrecognized_binding(self):
        shortcut = object.__new__(desktop.KdeShortcut)
        shortcut.action = [desktop.APP_ID, "dictate", "Revoice", "Start"]
        shortcut.report = Mock()
        shortcut.external = Mock()
        shortcut.modifier_mask = None
        shortcut.validation_timer = 0
        shortcut.chord_down = False
        shortcut._set_binding("Ctrl+Super", True, desktop.qt_key("Ctrl+Super")[0])
        ctrl = desktop.MODIFIERS["Ctrl"]
        shortcut._changed(shortcut.action, [([ctrl | 0x01000010],)])  # Ctrl+Home
        self.assertEqual(shortcut.shortcut, "Desktop binding")
        shortcut._changed(shortcut.action, [([ctrl | ord("J")],)])
        self.assertEqual(shortcut.shortcut, "Ctrl+J")
        shortcut.external.assert_called_once_with("Ctrl+J")

    def test_partial_transcript_is_kept_with_an_error_without_auto_paste(self):
        app = SimpleNamespace(
            generation=1, recording=Mock(), keep_transcript=Mock(), complete=Mock(), paste=Mock(),
        )
        revoice.App.handle(app, 1, "error", ("Connection lost.", "Completed text.", .2))
        app.keep_transcript.assert_called_once_with("Completed text.", .2)
        app.complete.assert_called_once_with("Connection lost. The partial transcript is available to copy.", error=True)
        app.paste.insert.assert_not_called()
        self.assertIsNone(app.recording)
