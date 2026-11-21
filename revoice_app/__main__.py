"""Revoice Linux desktop entry point."""

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSION = "0.1.0"

if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: revoice [--background | --settings | --quit | --version]")
        raise SystemExit(0)
    if "--version" in sys.argv:
        print(f"Revoice {VERSION}")
        raise SystemExit(0)

import dbus
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from .config import APP_ID, LOGIN_HOME, Store, api_key, codex_token, save_api_key
from .desktop import ClipboardError, KDE, WAYLAND, FocusService, KdeShortcut, Paste, PortalShortcut, copy_text, session_bus
from .speech import Recording
from .ui import Window
from .visuals import Pill

DOUBLE_PRESS_SECONDS = .5
LOG = logging.getLogger("revoice")


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.store = Store()
        self.window = None
        self.pill = None
        self.bus = self.focus = self.paste = self.shortcuts = self.tray = None
        self.shortcut_label = self.shortcut_error = ""
        self.shortcut_can_hold = False
        self.shortcut_capturing = False
        self.shortcut_intent = ""
        self.shortcut_started = 0.0
        self.shortcut_timer = 0
        self.state = "idle"
        self.generation = 0
        self.recording = None
        self.last_text = ""
        self.key = ""
        self.original = ("", "")
        self.dashboard_recording = False
        self.hands_free = False
        self.login_process = None
        self.quitting = False

    @property
    def ready(self):
        try:
            return bool(self.credential())
        except ValueError:
            return False

    def credential(self):
        if self.store.settings["provider"] == "codex":
            return codex_token(self.store.settings["codex_auth"])
        if not self.key:
            raise ValueError("Add an OpenAI API key in Settings.")
        return self.key

    def do_startup(self):
        Gtk.Application.do_startup(self)
        theme = Gtk.CssProvider()
        theme.load_from_path(str(Path(__file__).with_name("theme.css")))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), theme,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for name, callback in [
            ("show", lambda: self.show_window()),
            ("settings", lambda: self.show_window("settings")),
            ("history", lambda: self.show_window("history")),
            ("cancel", self.cancel),
            ("quit", self.quit),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _value, handler=callback: handler())
            self.add_action(action)
        self.hold()

    def do_command_line(self, command):
        args = command.get_arguments()[1:]
        if "--quit" in args:
            self.quit()
            return 0
        self.initialize()
        if "--background" not in args:
            self.show_window("settings" if "--settings" in args else "overview")
        return 0

    def initialize(self):
        if self.pill:
            return
        try:
            self.bus = session_bus()
            self.focus = FocusService(self.bus)
            shortcuts = KdeShortcut if KDE else PortalShortcut
            self.shortcuts = shortcuts(self.bus, self.shortcut_press, self.shortcut_release, self.shortcut_abort,
                                      self.report_shortcut, self.shortcut_changed)
            self.paste = Paste(self.focus, lambda: bool(getattr(self.shortcuts, "modifier_mask", None)))
            self.register_shortcut()
        except dbus.DBusException:
            self.shortcut_error = "The desktop shortcut service is unavailable."
        self.pill = Pill(self.toggle, self.cancel)
        self.window = Window(self)
        self.window.hide()
        if self.store.settings["provider"] == "openai":
            self.load_key()
        self.create_tray()
        self.window.refresh_status()
        self.window.refresh_latest()
        self.update_pill()

    def show_window(self, page=None):
        self.initialize()
        self.window.show_all()
        self.window.refresh_latest()
        self.window.present()
        if page:
            self.window.navigate(page)

    def create_tray(self):
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as Indicator
        except ValueError:
            return
        tray = Indicator.Indicator.new(APP_ID, str(Path(__file__).with_name("icon.svg")),
                                       Indicator.IndicatorCategory.APPLICATION_STATUS)
        tray.set_title("Revoice")
        tray.set_status(Indicator.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        for title, handler in [("Open Revoice", self.show_window), ("Start or stop dictation", self.toggle),
                               ("Cancel dictation", self.cancel), ("Quit Revoice", self.quit)]:
            item = Gtk.MenuItem(label=title)
            item.connect("activate", lambda _, run=handler: run())
            menu.append(item)
        tray.set_menu(menu)
        menu.show_all()
        self.tray = tray

    def register_shortcut(self):
        preferred = self.store.settings["shortcut"]
        if not KDE and preferred in ("Ctrl+Super", "Shift+Super"):
            preferred = "Ctrl+Alt+Space"
        choices = list(dict.fromkeys([preferred, "Shift+Super", "Ctrl+Alt+Space", "Ctrl+Shift+Space"])) if KDE else [preferred]
        for shortcut in choices:
            error = self.assign_shortcut(shortcut)
            if not error:
                return
        self.report_shortcut("", False, error)

    def assign_shortcut(self, shortcut):
        if not self.shortcuts:
            return "The desktop shortcut service is unavailable."
        try:
            self.shortcuts.assign(shortcut)
            self.store.set("shortcut", shortcut)
        except ValueError as error:
            return str(error)
        except dbus.DBusException:
            return "The desktop couldn’t register that shortcut."
        except OSError:
            return "Couldn’t save the shortcut setting."
        return ""

    def report_shortcut(self, label, can_hold, error):
        if (label, can_hold) != (self.shortcut_label, self.shortcut_can_hold):
            self.shortcut_abort()
        self.shortcut_label, self.shortcut_can_hold, self.shortcut_error = label, can_hold, error
        if self.window:
            self.window.refresh_shortcut()

    def shortcut_changed(self, shortcut):
        self.store.set("shortcut", shortcut)

    def shortcut_press(self, provisional=False):
        if self.shortcut_capturing or self.quitting or self.shortcut_intent:
            return
        if not self.shortcut_can_hold or not self.store.settings["hold"]:
            if provisional:
                self.shortcut_intent = "toggle"
            else:
                self.toggle()
        elif self.state == "idle":
            self.shortcut_started = time.monotonic()
            if self.start(provisional=provisional):
                self.shortcut_intent = "start"
        elif self.state == "recording":
            if self.shortcut_timer:
                self.clear_shortcut_gesture()
                if time.monotonic() - self.shortcut_started <= DOUBLE_PRESS_SECONDS:
                    self.shortcut_intent = "lock"
                    return
            if provisional:
                self.shortcut_intent = "stop"
            else:
                self.stop()

    def shortcut_release(self):
        intent, self.shortcut_intent = self.shortcut_intent, ""
        if intent == "toggle":
            self.toggle()
        elif self.state == "recording" and intent == "start":
            self.recording.confirm()
            remaining = DOUBLE_PRESS_SECONDS - (time.monotonic() - self.shortcut_started)
            if remaining > 0:
                self.shortcut_timer = GLib.timeout_add(max(1, round(remaining * 1000)), self.finish_shortcut_tap)
            else:
                self.stop()
        elif self.state == "recording" and intent == "lock":
            self.hands_free = True
            self.update_pill()
            self.window.feedback("Hands-free recording. Tap your shortcut to stop.")
        elif self.state == "recording" and intent == "stop":
            self.stop()

    def finish_shortcut_tap(self):
        self.shortcut_timer = 0
        self.stop()
        return False

    def clear_shortcut_gesture(self):
        if self.shortcut_timer:
            GLib.source_remove(self.shortcut_timer)
            self.shortcut_timer = 0
        self.shortcut_intent = ""

    def shortcut_abort(self):
        discard = self.shortcut_intent in ("start", "lock") or self.shortcut_timer
        self.clear_shortcut_gesture()
        if discard:
            self.cancel()

    def load_key(self):
        try:
            self.key = api_key()
        except (OSError, subprocess.SubprocessError):
            self.key = ""

    def update_key(self, key):
        try:
            save_api_key(key)
        except (OSError, subprocess.SubprocessError):
            return "The desktop keyring couldn’t save the key. Unlock your keyring and retry."
        self.key = key
        return ""

    def start_login(self):
        codex = shutil.which("codex")
        if not codex:
            for folder in (Path.home() / ".local/bin", Path.home() / ".npm-global/bin"):
                candidate = folder / "codex"
                if candidate.is_file():
                    codex = str(candidate)
                    break
        if not codex:
            return "Install the Codex CLI, then use Sign in with Codex."
        terminal = next((program for program in ("konsole", "kgx", "gnome-terminal", "x-terminal-emulator")
                         if shutil.which(program)), None)
        if not terminal:
            return "Open a terminal, run codex login and connect the existing sign-in here."
        if self.login_process and self.login_process.poll() is None:
            return "Finish signing in from the open terminal or browser."
        LOGIN_HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
        prefix = [terminal, "--"] if terminal in {"kgx", "gnome-terminal"} else [terminal, "-e"]
        if terminal == "konsole":
            prefix.insert(1, "--separate")
        previous = LOGIN_HOME / "auth.json"
        before = previous.stat().st_mtime_ns if previous.exists() else None
        try:
            self.login_process = subprocess.Popen([*prefix, "env", f"CODEX_HOME={LOGIN_HOME}", codex, "login"],
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return "Revoice couldn’t open the Codex login terminal."
        deadline = time.monotonic() + 300

        def refresh():
            if previous.exists() and previous.stat().st_mtime_ns != before:
                try:
                    codex_token(str(previous))
                except ValueError:
                    return time.monotonic() < deadline
                self.store.set("codex_auth", str(previous))
                self.window.refresh_status()
                self.window.feedback("Codex sign-in connected.")
                return False
            return time.monotonic() < deadline

        GLib.timeout_add_seconds(1, refresh)
        return "Finish signing in in the terminal or browser. Revoice updates automatically."

    def start(self, dashboard=False, provisional=False):
        if self.quitting or (self.focus and self.focus.locked):
            return False
        try:
            credential = self.credential()
        except ValueError as error:
            self.complete(str(error), error=True)
            return False
        self.original = self.focus.window if self.focus else ("", "")
        self.dashboard_recording = dashboard
        self.generation += 1
        generation = self.generation
        def emit(kind, *values):
            GLib.idle_add(self.handle, generation, kind, values)
        self.recording = Recording(self.store.settings, credential, emit)
        try:
            self.recording.start(provisional=provisional)
        except OSError:
            self.recording = None
            self.complete("PipeWire couldn’t open the microphone.", error=True)
            return False
        self.state = "recording"
        self.update_pill()
        self.window.feedback("Listening…")
        self.window.refresh_status()
        return True

    def stop(self):
        if not self.recording or self.state != "recording":
            return
        self.clear_shortcut_gesture()
        self.hands_free = False
        self.state = "processing"
        self.recording.stop()
        self.recording.confirm()
        self.update_pill()
        self.window.feedback("Finishing your dictation…")
        self.window.refresh_status()

    def toggle(self, dashboard=False):
        if self.state == "idle":
            self.start(dashboard)
        elif self.state == "recording":
            self.stop()
        elif dashboard:
            self.cancel()

    def cancel(self):
        self.generation += 1
        if self.recording:
            self.recording.cancel()
        self.recording = None
        self.clear_shortcut_gesture()
        self.hands_free = False
        self.state = "idle"
        if self.pill:
            self.update_pill()
        if self.window:
            self.window.feedback("Dictation cancelled.")
            self.window.refresh_status()

    def handle(self, generation, kind, values):
        if generation != self.generation or not self.recording:
            return False
        if kind == "level" and self.state == "recording":
            self.pill.energy = values[0]
            if self.dashboard_recording:
                self.window.update_meter(values[0])
        elif kind == "error":
            self.recording.cancel()
            self.recording = None
            message = values[0]
            if len(values) == 3:
                self.keep_transcript(values[1], values[2])
                message += " The partial transcript is available to copy."
            self.complete(message, error=True)
        elif kind == "result":
            self.recording = None
            text, duration = values
            self.keep_transcript(text, duration)
            if self.dashboard_recording or not self.store.settings["auto_paste"]:
                self.complete("Transcript ready")
            elif not self.paste:
                self.paste_complete(generation, "Automatic paste unavailable. Transcript ready to copy.")
            else:
                self.state = "processing"
                self.update_pill()
                self.paste.insert(text, self.original, self.store.settings["paste_key"],
                                  lambda error: self.paste_complete(generation, error),
                                  lambda: generation == self.generation)
        return False

    def keep_transcript(self, text, duration):
        self.last_text = text
        try:
            self.store.add(text, duration)
        except OSError:
            LOG.warning("Could not write the transcript history.")
        self.window.refresh_latest()
        if self.window.current == "history":
            self.window.refresh_history()

    def paste_complete(self, generation, error):
        if generation == self.generation:
            self.complete(error or "Paste sent", error=bool(error))
        return False

    def complete(self, message, error=False):
        self.state = "idle"
        self.clear_shortcut_gesture()
        self.hands_free = False
        self.update_pill()
        self.window.feedback(message, error)
        self.window.refresh_status()
        if error:
            LOG.warning("Dictation: %s", message)
            if not self.window.get_visible():
                notice = Gio.Notification.new("Revoice dictation")
                notice.set_body(message)
                notice.set_default_action("app.show")
                self.send_notification("dictation-error", notice)
        else:
            self.withdraw_notification("dictation-error")

    def update_pill(self):
        self.pill.update("idle" if self.dashboard_recording else self.state, self.hands_free)

    def copy(self, text):
        try:
            copy_text(text)
        except (ClipboardError, OSError, subprocess.SubprocessError):
            self.window.feedback("The desktop clipboard couldn’t be reached.", error=True)
            return False
        return True

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        if self.recording or (self.paste and self.paste.busy):
            self.cancel()
        if self.paste and self.paste.busy:
            def finish():
                if self.paste.busy:
                    return True
                super(App, self).quit()
                return False
            GLib.timeout_add(60, finish)
        else:
            super().quit()

    def do_shutdown(self):
        if self.recording:
            self.recording.cancel()
        if self.shortcuts:
            self.shortcuts.close()
        if self.focus:
            self.focus.close()
        if self.paste:
            self.paste.close()
        if self.pill:
            self.pill.destroy()
        Gtk.Application.do_shutdown(self)


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Revoice")
    return App().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
