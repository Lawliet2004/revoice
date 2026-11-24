"""Appearance choices and the sign-in cards."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from revoice_app import appearance, config


class AppearanceTests(unittest.TestCase):
    def test_unknown_appearance_falls_back_and_known_choices_stick(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.json"
            history = Path(folder) / "history.json"
            settings.write_text(
                '{"tone": "neon", "accent": "sea", "text_size": "large", "corners": "round",'
                ' "waveform": "spark", "pill_size": "huge", "pill_surface": "glass",'
                ' "density": "tight", "reading_face": "script", "live_pill": "yes"}'
            )
            with patch.multiple(config, SETTINGS=settings, HISTORY=history):
                store = config.Store()
        self.assertEqual(store.settings["tone"], "warm")
        self.assertEqual(store.settings["accent"], "sea")
        self.assertEqual(store.settings["text_size"], "large")
        self.assertEqual(store.settings["corners"], "round")
        self.assertEqual(store.settings["waveform"], "ink")
        self.assertEqual(store.settings["pill_size"], "compact")
        self.assertEqual(store.settings["pill_surface"], "charcoal")
        self.assertEqual(store.settings["density"], "regular")
        self.assertEqual(store.settings["reading_face"], "book")
        self.assertIs(store.settings["live_pill"], False)
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.json"
            history = Path(folder) / "history.json"
            settings.write_text(
                '{"waveform": "ribbon", "pill_size": "large", "pill_surface": "paper",'
                ' "density": "roomy", "reading_face": "mono", "live_pill": true}'
            )
            with patch.multiple(config, SETTINGS=settings, HISTORY=history):
                known = config.Store()
        self.assertEqual(known.settings["tone"], "warm")
        self.assertEqual(known.settings["waveform"], "ribbon")
        self.assertEqual(known.settings["pill_size"], "large")
        self.assertEqual(known.settings["pill_surface"], "paper")
        self.assertEqual(known.settings["density"], "roomy")
        self.assertEqual(known.settings["reading_face"], "mono")
        self.assertIs(known.settings["live_pill"], True)

    def test_cool_sea_desk_reaches_the_shell_and_the_home_page(self):
        settings = {"tone": "cool", "accent": "sea", "text_size": "large", "corners": "sharp"}
        css = appearance.stylesheet(settings)
        self.assertIn("@define-color base #e7eef2;", css)
        self.assertIn("@define-color accent #1f5275;", css)
        self.assertIn("font-size: 16px", css)
        self.assertIn("#canvas { border-radius: 10px; }", css)
        home = appearance.web_appearance(settings)
        self.assertEqual(home["vars"]["--color-accent"], "#1f5275")
        self.assertEqual(home["vars"]["--color-record"], "#1a4664")
        self.assertEqual(home["fontSize"], "16px")
        self.assertEqual(appearance.web_appearance({})["vars"]["--color-accent"], "#79501b")

    def test_roomy_mono_sets_density_and_a_monospace_face(self):
        home = appearance.web_appearance({"density": "roomy", "reading_face": "mono"})
        self.assertEqual(home["vars"]["--density"], "1.14")
        self.assertEqual(
            home["vars"]["--font-serif"],
            '"Cascadia Mono", "Cascadia Code", "Source Code Pro", ui-monospace, monospace',
        )

    def test_sans_large_preview_overrides_the_sample_line(self):
        css = appearance.stylesheet({"reading_face": "sans", "text_size": "large"})
        self.assertIn("font-size: 16px", css)
        self.assertIn("#appearance-preview { font-family: sans-serif; font-size: 34px; }", css)

    def test_sign_in_cards_name_codex_and_claude(self):
        missing = appearance.account_view("claude", False, False, "", None)
        self.assertEqual(missing["sign"], "Sign in with Claude")
        self.assertEqual(missing["status"], "Sign in to Claude")
        self.assertTrue(missing["show_use"])
        self.assertFalse(missing["show_disconnect"])
        connected = appearance.account_view("codex", True, True, "/home/me/.codex/auth.json", "/home/me/.codex/auth.json")
        self.assertEqual(connected["status"], "Connected via Codex")
        self.assertEqual(connected["sign"], "Sign in with Codex")
        self.assertFalse(connected["show_use"])
        self.assertTrue(connected["show_disconnect"])
        self.assertFalse(connected["show_existing"])
        found = appearance.account_view("codex", False, False, "", "/home/me/.codex/auth.json")
        self.assertTrue(found["show_existing"])
        self.assertIn("already on this computer", found["detail"])


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "no display")
class SettingsWindowTests(unittest.TestCase):
    def test_speech_page_shows_both_sign_in_buttons(self):
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        from revoice_app import __main__ as revoice

        Gtk.init([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.multiple(config, SETTINGS=Path(folder) / "settings.json", HISTORY=Path(folder) / "history.json"):
                app = revoice.App()
                window = revoice.Window(app)
            window.open_settings("speech")
            labels = []

            def collect(widget):
                if isinstance(widget, Gtk.Label):
                    labels.append(widget.get_text())
                if isinstance(widget, Gtk.Container):
                    for child in widget.get_children():
                        collect(child)

            collect(window)
            self.assertIn("Sign in with Codex", labels)
            self.assertIn("Sign in with Claude", labels)
            self.assertIn("Claude sign-in", labels)
            self.assertIn("Appearance", labels)
            self.assertEqual(window.settings_pages.get_visible_child_name(), "speech")
            codex = window.accounts["codex"]
            claude = window.accounts["claude"]
            self.assertTrue(codex.sign.get_visible())
            self.assertTrue(claude.sign.get_visible())
            self.assertTrue(codex.badge.get_visible())
            window.navigate_settings("claude")
            self.assertEqual(window.settings_pages.get_visible_child_name(), "claude")
            self.assertEqual(window.settings_nav["claude"].get_style_context().has_class("active"), True)
            window.choose_appearance("accent", "sea")
            self.assertEqual(app.store.settings["accent"], "sea")
            self.assertIn("@define-color accent #1f5275;", appearance.stylesheet(app.store.settings))
            window.destroy()
