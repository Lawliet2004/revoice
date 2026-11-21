import json
import tempfile
import unittest
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
        self.assertEqual(store.settings["language"], "")
        self.assertEqual(store.settings["provider"], "codex")
        self.assertIs(store.settings["hold"], False)
        self.assertIs(store.settings["auto_paste"], True)
        self.assertEqual(store.history, [
            {"text": "Preserved", "duration": 0}, {"text": "Also preserved", "duration": 1.75},
        ])

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
