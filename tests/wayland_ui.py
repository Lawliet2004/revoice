"""Exercise the KDE Wayland shortcut, pill, clipboard and a real GTK text field."""

import hashlib
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import dbus
from evdev import UInput, ecodes

from revoice_app import __main__ as revoice
from revoice_app.desktop import (
    KDE, WAYLAND, WAYLAND_CLIPBOARD, ClipboardChanged, offer, qt_key, read_wayland_clipboard, wayland_types,
)
from revoice_app.visuals import cairo
from gi.repository import Gdk, GLib, Gtk

TRANSCRIPT = "Revoice wrote this sentence — ✓"
CTRL, SHIFT, SUPER, F8 = (ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_LEFTMETA, ecodes.KEY_F8)
CONTEXT = GLib.MainContext.default()


def wait_for(condition, message, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        while CONTEXT.pending():
            CONTEXT.iteration(False)
        if condition():
            return
        if time.monotonic() >= deadline:
            raise AssertionError(message)
        time.sleep(.01)


def settle(seconds):
    deadline = time.monotonic() + seconds
    wait_for(lambda: time.monotonic() >= deadline, "GTK did not settle", seconds + 1)


def clipboard_digest():
    types = wayland_types()
    for mime in ("image/png", "text/html", "text/plain;charset=utf-8", "text/plain"):
        if mime in types:
            data = subprocess.check_output([str(WAYLAND_CLIPBOARD), "--read", mime], timeout=3)
            return mime, hashlib.sha256(data).digest()
    return None


class TestRecording:
    """Give the live desktop test a fixed transcript without a microphone or account."""

    def __init__(self, _settings, _credential, emit):
        self.emit = emit
        self.confirmed = self.stopped = self.cancelled = False

    def start(self, provisional=False):
        if not provisional:
            self.confirm()
        self.emit("level", .92)

    def confirm(self):
        self.confirmed = True

    def stop(self):
        self.stopped = True
        self.emit("result", TRANSCRIPT, 1.0)

    def cancel(self):
        self.cancelled = True


class DesktopTest(revoice.App):
    def __init__(self, keyboard, original_shortcut="Ctrl+Super"):
        super().__init__()
        self.keyboard = keyboard
        self.original_shortcut = original_shortcut
        self.targets = []
        self.output = Path("build/qa/wayland")
        self.output.mkdir(parents=True, exist_ok=True)
        self.failure = None

    def do_command_line(self, command):
        result = super().do_command_line(command)
        GLib.idle_add(self.test)
        return result

    def credential(self):
        return "local test transcript"

    def capture(self, widget, name, size=None):
        settle(.18)
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        if size:
            assert (width, height) == size, f"{name} is {width} × {height}, expected {size}"
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        widget.draw(cairo.Context(surface))
        surface.write_to_png(str(self.output / f"{name}.png"))

    def target(self):
        previous = self.focus.window[0]
        window = Gtk.Window(title="Revoice UI test field")
        window.set_default_size(510, 128)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Dictation target")
        entry.set_halign(Gtk.Align.FILL)
        entry.set_valign(Gtk.Align.CENTER)
        entry.set_margin_start(24)
        entry.set_margin_end(24)
        window.add(entry)
        self.targets.append(window)
        window.show_all()
        entry.grab_focus()
        window.present()
        wait_for(lambda: window.is_active() and entry.has_focus() and self.focus.window[0] not in ("", previous),
                 "KWin did not report the focused text field")
        return window, entry

    def emit_key(self, code, down):
        assert any(window.is_active() for window in self.targets), "A test field must have focus"
        self.keyboard.write(ecodes.EV_KEY, code, int(down))
        self.keyboard.syn()
        settle(.025)

    def tap(self, modifier=CTRL):
        self.emit_key(modifier, True)
        self.emit_key(SUPER, True)
        self.emit_key(SUPER, False)
        self.emit_key(modifier, False)

    def paste_verified(self, entry, clipboard):
        wait_for(lambda: self.state == "idle", "The paste did not finish")
        assert entry.get_text() == TRANSCRIPT, self.window.feedback_message
        assert self.store.history[0]["text"] == TRANSCRIPT
        assert clipboard_digest() == clipboard, "The previous clipboard was not restored"
        entry.set_text("")

    def verify_concurrent_clipboard_copy(self):
        helper = WAYLAND_CLIPBOARD
        previous = read_wayland_clipboard()
        marker = "application/x-revoice-test-" + uuid.uuid4().hex
        new_copy = [("text/plain", b"Copied while Revoice was taking a snapshot"), (marker, b"")]
        transcript = [("text/plain", TRANSCRIPT.encode())]

        try:
            try:
                offer(helper, transcript, before_publish=lambda: offer(helper, new_copy))
            except ClipboardChanged:
                pass
            else:
                raise AssertionError("Revoice overwrote a copy made during the clipboard snapshot")

            try:
                offer(helper, transcript, expected_marker=marker + "-missing")
            except ClipboardChanged:
                pass
            else:
                raise AssertionError("Revoice restored an old clipboard after a newer copy")
            assert marker in wayland_types()
            assert subprocess.check_output([str(helper), "--read", "text/plain"], timeout=2) == new_copy[0][1]
        finally:
            if marker in wayland_types():
                if previous:
                    offer(helper, previous, expected_marker=marker)
                else:
                    subprocess.run([str(helper), "--clear-if", marker], check=True, timeout=2, capture_output=True)

    def test(self):
        try:
            self.exercise()
        except BaseException as error:
            self.failure = error
        finally:
            self.cancel()
            if self.shortcut_label != self.original_shortcut:
                self.assign_shortcut(self.original_shortcut)
            for window in reversed(self.targets):
                window.destroy()
            self.quit()
        return False

    def exercise(self):
        wait_for(lambda: self.shortcut_can_hold, "KWin's modifier state protocol is unavailable")
        assert self.shortcut_label == "Ctrl+Super", self.shortcut_label
        assert self.pill.layer, "Wayland layer shell is unavailable"
        assert not self.pill.get_visible(), "The idle pill should be hidden by default"
        wait_for(lambda: self.window.home.loaded, "The Reflow home view did not load")
        self.window.sidebar_toggle.clicked()
        assert self.window.sidebar_collapsed
        assert all(not item.get_visible() for item in self.window.sidebar_labels)
        self.capture(self.window, "overview-collapsed")
        self.window.sidebar_toggle.clicked()
        assert all(item.get_visible() for item in self.window.sidebar_labels)
        self.window.toggle_maximize()
        wait_for(self.window.is_maximized, "The title bar did not maximize the window")
        self.window.toggle_maximize()
        wait_for(lambda: not self.window.is_maximized(), "The title bar did not restore the window")
        self.capture(self.window, "overview")
        self.window.nav["settings"].clicked()
        self.window.settings_nav["speech"].clicked()
        assert self.window.settings_pages.get_visible_child_name() == "speech"
        self.capture(self.window, "settings")
        backdrop = self.window.settings_layer.get_child()
        backdrop.emit("button-press-event", Gdk.Event.new(Gdk.EventType.BUTTON_PRESS))
        assert not self.window.settings_layer.get_visible(), "Clicking the backdrop should close Settings"
        assert self.window.current == "overview"
        assert self.window.nav["settings"].has_focus()
        self.store.set("idle_pill", True)
        self.update_pill()
        assert not self.pill.get_visible(), "A saved idle-prompt setting must not show the HUD"

        window, entry = self.target()
        original_clipboard = clipboard_digest()
        key, _ = qt_key("Ctrl+Super+F8")
        sequence = dbus.Struct((dbus.Array([key, 0, 0, 0], signature="i"),))
        assert self.shortcuts.accel.globalShortcutAvailable(sequence, revoice.APP_ID), "The test chord is in use"
        self.emit_key(CTRL, True)
        self.emit_key(SUPER, True)
        wait_for(lambda: self.state == "recording", "Recording did not start on keydown")
        self.capture(self.pill.area, "listening", (108, 40))
        settle(.4)
        assert self.state == "recording" and not self.recording.confirmed
        assert window.is_active() and entry.has_focus(), "The pill took focus from the text field"
        self.emit_key(CTRL, False)
        wait_for(lambda: self.state == "processing", "Recording did not stop on release")
        self.capture(self.pill.area, "pasting", (108, 40))
        assert entry.get_text() == "", "Revoice attempted paste while Super was still held"
        self.emit_key(SUPER, False)
        self.paste_verified(entry, original_clipboard)
        assert not self.pill.get_visible(), "The HUD remained visible after paste"
        print("Hold, release, focused field paste and clipboard restoration passed", flush=True)

        self.tap()
        self.tap()
        wait_for(lambda: self.hands_free, "Double-pressing the full chord did not latch recording")
        self.capture(self.pill.area, "hands-free", (108, 40))
        settle(.6)
        assert self.state == "recording" and not self.recording.stopped
        self.tap()
        self.paste_verified(entry, original_clipboard)

        self.emit_key(CTRL, True)
        for _ in range(2):
            self.emit_key(SUPER, True)
            self.emit_key(SUPER, False)
        wait_for(lambda: self.hands_free, "Double-tapping Super with Ctrl held did not latch recording")
        settle(.6)
        self.emit_key(SUPER, True)
        self.emit_key(SUPER, False)
        wait_for(lambda: self.state == "processing", "The third chord did not stop hands-free recording")
        self.emit_key(CTRL, False)
        self.paste_verified(entry, original_clipboard)
        print("Both hands-free gestures and stop-to-paste passed", flush=True)

        self.emit_key(CTRL, True)
        self.emit_key(SUPER, True)
        unconfirmed = self.recording
        self.emit_key(F8, True)
        self.emit_key(F8, False)
        self.emit_key(SUPER, False)
        self.emit_key(CTRL, False)
        wait_for(lambda: self.state == "idle", "An unrelated chord was accepted")
        assert unconfirmed.cancelled and not unconfirmed.confirmed
        assert entry.get_text() == ""

        self.tap()
        self.tap()
        wait_for(lambda: self.hands_free, "Could not latch recording before the focus test")
        _, other_entry = self.target()
        self.tap()
        wait_for(lambda: self.state == "idle", "Focus change did not end the paste attempt")
        assert "Focus changed" in self.window.feedback_message
        assert not entry.get_text() and not other_entry.get_text()
        assert self.last_text == TRANSCRIPT and clipboard_digest() == original_clipboard
        print("Unrelated shortcut rejection and focus-change protection passed", flush=True)

        assert not self.assign_shortcut("Shift+Super")
        self.tap(SHIFT)
        self.tap(SHIFT)
        wait_for(lambda: self.hands_free, "The alternate modifier binding did not latch")
        self.pill.area.evaluate_javascript("document.querySelector('.hud-stop').click()", -1)
        wait_for(lambda: self.state == "idle", "The pill cancel control did not respond")
        assert self.state == "idle" and not other_entry.get_text()
        assert not self.pill.get_visible(), "The HUD remained visible after cancellation"
        print("Alternate shortcut, cancel and pill sizing passed", flush=True)

        self.store.set("hold", False)
        self.tap(SHIFT)
        assert self.state == "recording" and self.recording.confirmed
        self.tap(SHIFT)
        self.paste_verified(other_entry, original_clipboard)

        self.store.set("hold", True)
        assert not self.assign_shortcut("Ctrl+Super+F8")
        self.emit_key(CTRL, True)
        self.emit_key(SUPER, True)
        assert self.state == "idle", "The regular shortcut started before its final key"
        self.emit_key(F8, True)
        wait_for(lambda: self.state == "recording", "The regular shortcut did not start on keydown")
        settle(.52)
        self.emit_key(F8, False)
        self.emit_key(SUPER, False)
        self.emit_key(CTRL, False)
        self.paste_verified(other_entry, original_clipboard)
        self.window.home.evaluate_javascript("document.querySelector('#record').click()", -1)
        wait_for(lambda: self.state == "recording", "The dashboard record control did not respond")
        assert not self.pill.get_visible(), "The dashboard recording showed an overlay"
        self.cancel()
        print("Tap-to-toggle, regular key bindings and dashboard-only recording passed", flush=True)
        self.verify_concurrent_clipboard_copy()
        assert clipboard_digest() == original_clipboard
        print("Concurrent clipboard copies were preserved before publish and during restoration", flush=True)


def main():
    if not (KDE and WAYLAND):
        raise SystemExit("Run the desktop test from a KDE Wayland session.")
    if revoice.session_bus().name_has_owner(revoice.APP_ID):
        raise SystemExit("Quit the running Revoice instance before running the desktop test.")
    original_shortcut = revoice.Store().settings["shortcut"]
    with tempfile.TemporaryDirectory(prefix="revoice-test-") as folder, patch.multiple(
        "revoice_app.config", SETTINGS=Path(folder) / "settings.json", HISTORY=Path(folder) / "history.json",
    ), patch.object(revoice, "Recording", TestRecording), UInput(
        {ecodes.EV_KEY: [CTRL, SHIFT, SUPER, F8]}, name="Revoice UI test keyboard",
    ) as keyboard:
        app = DesktopTest(keyboard, original_shortcut)
        app.run(["revoice"])
        if app.failure:
            raise app.failure


if __name__ == "__main__":
    sys.exit(main())
