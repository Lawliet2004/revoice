"""Desktop shortcuts, focused window tracking, and clipboard-safe insertion."""

import os
import re
import select
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from evdev import UInput, ecodes
from evdev.uinput import UInputError
from gi.repository import Gdk, Gio, GLib

from .config import APP_ID

ROOT = Path(__file__).resolve().parent.parent
WAYLAND_CLIPBOARD = ROOT / "build/revoice-clipboard"
KDE = any(part.lower() in ("kde", "plasma")
          for part in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"))
WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY"))
MODIFIERS = {"Ctrl": 0x04000000, "Shift": 0x02000000,
             "Alt": 0x08000000, "Super": 0x10000000}
KWIN_MODIFIERS = {"Alt": 1 << 3, "Ctrl": 1 << 4, "Shift": 1 << 5, "Super": 1 << 6}
MODIFIER_CONFIRMATION_MS = 150
PASTE_CLIPBOARD_GRACE = .9
PASTE_READ_TIMEOUT = 2.0
NAMED_KEYS = {"Space": 0x20, "Tab": 0x01000001, "Enter": 0x01000004,
              "Backspace": 0x01000003, "Escape": 0x01000000,
              **{f"F{index}": 0x0100002F + index for index in range(1, 13)}}
KWIN = "org.kde.KWin"
ACCEL = "org.kde.kglobalaccel"
COMPONENT = ACCEL + ".Component"
SET_PRESENT = 2
NO_AUTOLOAD = 4
MARKER = "application/x-revoice-paste-"
TEXT_MIMES = ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING", "TEXT")
TERMINAL = re.compile(r"terminal|konsole|alacritty|kitty|wezterm|foot|ghostty|xterm|terminator|tilix|ptyxis|yakuake|contour", re.I)


def qt_key(shortcut):
    key = 0
    modifiers = 0
    for part in shortcut.split("+"):
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        elif not key and (part in NAMED_KEYS or (len(part) == 1 and part.isascii() and part.isalnum())):
            key = NAMED_KEYS.get(part) or ord(part.upper())
        else:
            raise ValueError("Use Ctrl, Shift, Alt or Super with a letter, digit, Space or function key.")
    if not modifiers or (not key and modifiers.bit_count() < 2):
        raise ValueError("Choose at least two modifier keys, or a modifier and a regular key.")
    return modifiers | key, not key


class KdeShortcut:
    def __init__(self, bus, press, release, abort, report, external):
        self.bus = bus
        self.press = press
        self.release = release
        self.abort = abort
        self.report = report
        self.external = external
        self.action = [APP_ID, "dictate", "Revoice", "Start or stop dictation"]
        self.accel = dbus.Interface(bus.get_object(ACCEL, "/kglobalaccel"), "org.kde.KGlobalAccel")
        self.matches = []
        self.shortcut = ""
        self.binding_key = 0
        self.modifier_only = False
        self.component_path = ""
        self.modifier_mask = None
        self.modifier_chord = 0
        self.chord_down = False
        self.confirmed_at = 0.0
        self.validation_timer = 0
        self.monitor = None
        self.monitor_cancel = Gio.Cancellable()
        if WAYLAND:
            try:
                self.monitor = Gio.Subprocess.new(
                    [str(ROOT / "build/revoice-modifiers")],
                    Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
                )
                stream = Gio.DataInputStream.new(self.monitor.get_stdout_pipe())
                stream.read_line_async(GLib.PRIORITY_DEFAULT, self.monitor_cancel, self._read_modifiers)
            except GLib.Error:
                pass

    def assign(self, shortcut):
        key, modifier_only = qt_key(shortcut)
        if modifier_only:
            support = str(self.bus.get_object(KWIN, "/KWin").supportInformation(dbus_interface=KWIN))
            version = re.search(r"KWin version:\s*(\d+)\.(\d+)", support)
            if not version or tuple(map(int, version.groups())) < (6, 1):
                raise ValueError("Modifier-only shortcuts require KDE Plasma 6.1 or later.")
        seq = dbus.Struct((dbus.Array([key, 0, 0, 0], signature="i"),))
        if not self.accel.globalShortcutAvailable(seq, APP_ID):
            owners = self.accel.getGlobalShortcutsByKey(dbus.Int32(key))
            if not owners or any(owner[0] != "dictate" or owner[2] != APP_ID for owner in owners):
                raise ValueError("That shortcut is already assigned to another desktop action.")
        if not self.component_path:
            self.accel.doRegister(self.action)
        result = self.accel.setShortcutKeys(
            self.action, dbus.Array([seq], signature="(ai)"), dbus.UInt32(SET_PRESENT | NO_AUTOLOAD),
        )
        if not result or int(result[0][0][0]) != key:
            raise ValueError("KDE couldn’t apply that shortcut.")
        if not self.component_path:
            self.component_path = str(self.accel.getComponent(APP_ID))
            for signal, callback in (("globalShortcutPressed", self._press),
                                     ("globalShortcutReleased", self._release)):
                self.matches.append(self.bus.add_signal_receiver(
                    callback, signal_name=signal, dbus_interface=COMPONENT,
                    bus_name=ACCEL, path=self.component_path,
                ))
            self.matches.append(self.bus.add_signal_receiver(
                self._changed, signal_name="yourShortcutsChanged",
                dbus_interface="org.kde.KGlobalAccel", bus_name=ACCEL, path="/kglobalaccel",
            ))
        self._set_binding(shortcut, modifier_only, key)
        return shortcut

    def _set_binding(self, shortcut, modifier_only, key=0):
        self._reset_chord()
        self.shortcut, self.modifier_only = shortcut, modifier_only
        self.binding_key = key
        self.modifier_chord = 0
        if modifier_only:
            self.modifier_chord = sum(KWIN_MODIFIERS.get(name, 0) for name in set(shortcut.split("+")))
        self._report_binding()

    def _report_binding(self):
        if self.shortcut:
            can_hold = not self.modifier_only or (self.modifier_chord != 0 and self.modifier_mask is not None)
            self.report(self.shortcut, can_hold, "")

    def _read_modifiers(self, stream, result):
        if self.monitor_cancel.is_cancelled():
            return
        try:
            line, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        previous = self.modifier_mask
        if line is None:
            self.modifier_mask = None
            self._reset_chord()
            self._report_binding()
            return
        self.modifier_mask = int(line)
        if previous is None:
            self._report_binding()
        elif self.modifier_chord:
            self._modifier_changed(previous)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, self.monitor_cancel, self._read_modifiers)

    def _modifier_changed(self, previous):
        mask, chord = self.modifier_mask, self.modifier_chord
        if mask == chord:
            if previous & chord != chord:
                if self.validation_timer:
                    self._reset_chord()
                self.chord_down = True
                self.press(provisional=True)
        elif self.chord_down:
            self.chord_down = False
            # KDE's activation on release confirms this was a standalone shortcut.
            # The D-Bus and Wayland notifications can arrive in either order.
            if mask & ~chord:
                self.confirmed_at = 0
                self.abort()
            elif time.monotonic() - self.confirmed_at < MODIFIER_CONFIRMATION_MS / 1000:
                self.confirmed_at = 0
                self.release()
            else:
                self.validation_timer = GLib.timeout_add(MODIFIER_CONFIRMATION_MS, self._unconfirmed)

    def _unconfirmed(self):
        self.validation_timer = 0
        self.abort()
        return False

    def _reset_chord(self):
        if self.validation_timer:
            GLib.source_remove(self.validation_timer)
        active = self.chord_down or self.validation_timer
        self.validation_timer, self.chord_down, self.confirmed_at = 0, False, 0
        if active:
            self.abort()

    def _press(self, component, action, _timestamp):
        if str(component).split("|")[0] == APP_ID and action == "dictate":
            if self.modifier_chord and self.modifier_mask is not None:
                if self.validation_timer:
                    GLib.source_remove(self.validation_timer)
                    self.validation_timer = 0
                    self.release()
                else:
                    self.confirmed_at = time.monotonic()
            else:
                self.press()

    def _release(self, component, action, _timestamp):
        if str(component).split("|")[0] == APP_ID and action == "dictate" and not self.modifier_only:
            self.release()

    def _changed(self, action, keys):
        if list(action)[:2] != self.action[:2]:
            return
        key = int(keys[0][0][0]) if keys and keys[0][0] else 0
        if not key:
            self._set_binding("", False)
            self.report("", False, "The desktop shortcut was cleared.")
            return
        if key == self.binding_key:
            return
        mods = [name for name, mask in MODIFIERS.items() if key & mask]
        base = key & 0x01FFFFFF
        name = next((name for name, code in NAMED_KEYS.items() if code == base), "")
        if not name and (48 <= base <= 57 or 65 <= base <= 90):
            name = chr(base)
        if not mods or (base and not name) or (not base and len(mods) < 2):
            self._set_binding("Desktop binding", not base, key)
            return
        shortcut = "+".join([*mods, name] if name else mods)
        self._set_binding(shortcut, not base, key)
        self.external(shortcut)

    def close(self):
        self.monitor_cancel.cancel()
        if self.monitor:
            self.monitor.force_exit()
        if self.validation_timer:
            GLib.source_remove(self.validation_timer)
        if self.component_path:
            try:
                self.accel.setInactive(self.action)
            except dbus.DBusException:
                pass
        for match in self.matches:
            match.remove()


class PortalShortcut:
    """Portal-owned bindings for desktops outside KDE."""

    def __init__(self, bus, press, release, _abort, report, _external):
        self.bus, self.press, self.release, self.report = bus, press, release, report
        self.portal_name = "org.freedesktop.portal.Desktop"
        self.portal_path = "/org/freedesktop/portal/desktop"
        self.interface = "org.freedesktop.portal.GlobalShortcuts"
        self.portal = dbus.Interface(bus.get_object(self.portal_name, self.portal_path), self.interface)
        self.session = None
        self.shortcut = ""
        self.matches = [
            bus.add_signal_receiver(self._activated, signal_name="Activated",
                                    dbus_interface=self.interface, bus_name=self.portal_name),
            bus.add_signal_receiver(self._deactivated, signal_name="Deactivated",
                                    dbus_interface=self.interface, bus_name=self.portal_name),
        ]
        self.request_matches = []

    def request(self, method, args, done):
        token = "revoice" + uuid.uuid4().hex
        sender = self.bus.get_unique_name().lstrip(":").replace(".", "_")
        path = "/org/freedesktop/portal/desktop/request/" + sender + "/" + token

        def response(code, results):
            match.remove()
            self.request_matches.remove(match)
            if code:
                self.report("", False, "The desktop shortcut permission was declined.")
            else:
                done(results)

        match = self.bus.add_signal_receiver(response, signal_name="Response", path=path,
                                              dbus_interface="org.freedesktop.portal.Request",
                                              bus_name=self.portal_name)
        self.request_matches.append(match)
        options = {"handle_token": token}
        if method == "CreateSession":
            options["session_handle_token"] = "revoice" + uuid.uuid4().hex
        try:
            getattr(self.portal, method)(*args, dbus.Dictionary(options, signature="sv"))
        except dbus.DBusException:
            match.remove()
            self.request_matches.remove(match)
            self.report("", False, "This desktop did not offer global shortcuts.")

    def assign(self, shortcut):
        _, modifier = qt_key(shortcut)
        if modifier:
            raise ValueError("Modifier-only shortcuts are available on KDE Plasma. Choose a regular key here.")
        self.shortcut = shortcut
        self._close_session()
        trigger = "+".join({"Ctrl": "CTRL", "Shift": "SHIFT", "Alt": "ALT", "Super": "LOGO",
                            "Space": "space", "Enter": "Return"}.get(k, k.lower() if len(k) == 1 else k)
                           for k in shortcut.split("+"))

        def created(results):
            self.session = dbus.ObjectPath(results["session_handle"])
            properties = dbus.Dictionary({"description": "Revoice dictation", "preferred_trigger": trigger},
                                         signature="sv")
            self.request("BindShortcuts", [self.session, [("dictate", properties)], ""], bound)

        def bound(results):
            actual = next((str(p.get("trigger_description", "")) for name, p in results.get("shortcuts", [])
                           if name == "dictate"), "")
            self.report(actual, bool(actual), "" if actual else "No shortcut was assigned by the desktop.")

        self.request("CreateSession", [], created)
        return shortcut

    def _activated(self, session, key, _timestamp, _options):
        if session == self.session and key == "dictate":
            self.press()

    def _deactivated(self, session, key, _timestamp, _options):
        if session == self.session and key == "dictate":
            self.release()

    def _close_session(self):
        if self.session:
            try:
                self.bus.get_object(self.portal_name, self.session).Close(dbus_interface="org.freedesktop.portal.Session")
            except dbus.DBusException:
                pass
            self.session = None

    def close(self):
        self._close_session()
        for match in [*self.matches, *self.request_matches]:
            match.remove()


class FocusService(dbus.service.Object):
    def __init__(self, bus):
        self.bus = bus
        self.name = dbus.service.BusName(APP_ID + ".Focus", bus=bus, do_not_queue=True)
        super().__init__(self.name, "/io/github/revoice/Revoice/Focus")
        self.window = ("", "")
        self.locked = False
        self.scripting = None
        self.lock_match = None
        if KDE:
            screensaver = "org.freedesktop.ScreenSaver"
            self.lock_match = bus.add_signal_receiver(
                self._lock_changed, signal_name="ActiveChanged", dbus_interface=screensaver,
                bus_name=screensaver, path="/ScreenSaver",
            )
            try:
                self.locked = bool(bus.call_blocking(screensaver, "/ScreenSaver", screensaver,
                                                     "GetActive", "", (), timeout=.5))
            except dbus.DBusException:
                pass
            scripting = dbus.Interface(bus.get_object(KWIN, "/Scripting"), "org.kde.kwin.Scripting")
            try:
                scripting.unloadScript("revoice-focus")
                script_id = bus.call_blocking(
                    KWIN, "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss",
                    (str(Path(__file__).with_name("focus.js")), "revoice-focus"), timeout=3,
                )
                if script_id >= 0:
                    script = bus.get_object(KWIN, f"/Scripting/Script{script_id}")
                    script.run(dbus_interface="org.kde.kwin.Script")
                    self.scripting = scripting
            except dbus.DBusException:
                pass

    @dbus.service.method(APP_ID + ".Focus", in_signature="ss", out_signature="")
    def Changed(self, token, app_class):
        self.window = (str(token), str(app_class))

    def _lock_changed(self, locked):
        self.locked = bool(locked)

    def close(self):
        if self.lock_match:
            self.lock_match.remove()
        if self.scripting:
            try:
                self.scripting.unloadScript("revoice-focus")
            except dbus.DBusException:
                pass
        self.remove_from_connection()


def session_bus():
    DBusGMainLoop(set_as_default=True)
    return dbus.SessionBus()


def sources():
    try:
        result = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True,
                                text=True, check=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and not fields[1].endswith(".monitor"):
            name = fields[1].removeprefix("alsa_input.").split(".")[-1]
            rows.append((fields[1], name.replace("__", " · ").replace("_", " ").removesuffix(" · source")))
    return rows


class ClipboardError(Exception):
    pass


class ClipboardChanged(ClipboardError):
    pass


class Paste:
    def __init__(self, focus, modifiers_down=lambda: False):
        self.focus = focus
        self.modifiers_down = modifiers_down
        self.keyboard = None
        self.lock = threading.Lock()

    @property
    def busy(self):
        return self.lock.locked()

    def check_target(self, original, allowed):
        if not allowed() or self.focus.locked or original[0] != self.focus.window[0]:
            raise ClipboardError("Focus changed. The transcript is available to copy.")
        if not KDE or not original[0]:
            raise ClipboardError("Revoice couldn’t verify the focused window. The transcript is available to copy.")

    def wait_for_release(self, original, allowed):
        deadline = time.monotonic() + 4
        self.check_target(original, allowed)
        while self.modifiers_down():
            if time.monotonic() >= deadline:
                raise ClipboardError("Release the shortcut keys before pasting. The transcript is available to copy.")
            time.sleep(.02)
            self.check_target(original, allowed)

    def wait_for_target(self, original, allowed):
        # A compositor can briefly report another surface while the HUD maps.
        # Only continue if the same window actually regains focus.
        deadline = time.monotonic() + .3
        while (original[0] and original[0] != self.focus.window[0]
               and allowed() and not self.focus.locked and time.monotonic() < deadline):
            time.sleep(.02)
        self.check_target(original, allowed)

    def prepare_keyboard(self):
        if not self.keyboard:
            keys = [ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_V]
            try:
                self.keyboard = UInput({ecodes.EV_KEY: keys}, name="Revoice Paste")
            except (OSError, UInputError) as error:
                raise ClipboardError("Paste needs access to /dev/uinput. The transcript is available to copy.") from error
            self.wait_for_keyboard()

    def wait_for_keyboard(self):
        device = self.keyboard.device
        if KDE and WAYLAND and device:
            device_name = Path(device.path).name
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                try:
                    keyboards = self.focus.bus.call_blocking(
                        KWIN, "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDeviceManager",
                        "ListKeyboards", "", (), timeout=.3,
                    )
                except dbus.DBusException:
                    break
                if device_name in keyboards:
                    return
                time.sleep(.03)
            else:
                self.close()
                raise ClipboardError("KDE didn’t register the paste keyboard. The transcript is available to copy.")
        time.sleep(.3)

    def close(self):
        if self.keyboard:
            self.keyboard.close()
            self.keyboard = None

    def send_keys(self, terminal):
        keys = [ecodes.KEY_LEFTCTRL]
        if terminal:
            keys.append(ecodes.KEY_LEFTSHIFT)
        keys.append(ecodes.KEY_V)
        try:
            for key in keys:
                self.keyboard.write(ecodes.EV_KEY, key, 1)
                self.keyboard.syn()
            time.sleep(.025)
        finally:
            for key in reversed(keys):
                self.keyboard.write(ecodes.EV_KEY, key, 0)
                self.keyboard.syn()

    def insert(self, text, original, paste_key, done, allowed):
        if not self.lock.acquire(blocking=False):
            GLib.idle_add(done, "Another paste is still finishing. Copy the transcript from History.")
            return

        def work():
            detail = ""
            try:
                self.wait_for_target(original, allowed)
                self.wait_for_release(original, allowed)
                self.prepare_keyboard()
                terminal = paste_key == "terminal" or (paste_key == "auto" and TERMINAL.search(original[1]))
                if WAYLAND:
                    self.wayland(text, terminal, original, allowed)
                else:
                    self.x11(text, terminal, original, allowed)
            except (ClipboardError, OSError, subprocess.SubprocessError) as error:
                detail = str(error) if isinstance(error, ClipboardError) else "Automatic paste is unavailable. Copy the transcript manually."
            finally:
                self.lock.release()
            GLib.idle_add(done, detail)

        threading.Thread(target=work, daemon=True).start()

    def wayland(self, text, terminal, original, allowed):
        helper = WAYLAND_CLIPBOARD
        if not helper.is_file():
            raise ClipboardError("Wayland clipboard support needs the built Revoice helper.")
        marker = MARKER + uuid.uuid4().hex
        encoded = text.encode("utf-8")
        temp = [(mime, encoded) for mime in TEXT_MIMES[:3]] + [(marker, b""), ("x-kde-passwordManagerHint", b"secret")]
        previous = []

        def snapshot():
            try:
                previous.extend(read_wayland_clipboard())
            except (OSError, subprocess.SubprocessError) as error:
                raise ClipboardError("The previous clipboard couldn’t be read. The transcript is available to copy.") from error
            self.check_target(original, allowed)

        current = offer(helper, temp, before_publish=snapshot)
        try:
            time.sleep(.08)
            if marker not in wayland_types():
                raise ClipboardError("The clipboard changed before paste. The transcript is available to copy.")
            self.wait_for_release(original, allowed)
            if current.poll() is not None:
                raise ClipboardError("The clipboard changed before paste. The transcript is available to copy.")
            if select.select([current.stdout], [], [], 0)[0]:
                os.read(current.stdout.fileno(), 4096)
            self.check_target(original, allowed)
            self.send_keys(terminal)
            sent_at = time.monotonic()
            readable, _, _ = select.select([current.stdout], [], [], PASTE_READ_TIMEOUT)
            if not readable or b"read" not in os.read(current.stdout.fileno(), 4096):
                raise ClipboardError("Revoice couldn’t confirm that the app read the clipboard. The transcript is available to copy.")
            time.sleep(max(0, sent_at + PASTE_CLIPBOARD_GRACE - time.monotonic()))
        finally:
            try:
                if previous:
                    offer(helper, previous, expected_marker=marker)
                else:
                    result = subprocess.run([str(helper), "--clear-if", marker], timeout=1.5,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if result.returncode != 4:
                        result.check_returncode()
            except ClipboardChanged:
                pass
            except (ClipboardError, OSError, subprocess.SubprocessError) as error:
                raise ClipboardError("The previous clipboard couldn’t be restored.") from error
            finally:
                current.stdout.close()
                if current.poll() is None:
                    current.terminate()
                current.wait(timeout=2)

    def x11(self, text, terminal, original, allowed):
        formats = subprocess.run(["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"], capture_output=True, timeout=1)
        mime_names = formats.stdout.decode(errors="replace").splitlines()
        if any(name not in (*TEXT_MIMES, "TARGETS", "TIMESTAMP", "MULTIPLE", "COMPOUND_TEXT")
               for name in mime_names):
            raise ClipboardError("The clipboard contains richer data. Copy the transcript manually.")
        previous = subprocess.run(["xclip", "-selection", "clipboard", "-o", "-t", "UTF8_STRING"], capture_output=True, timeout=1)
        process = subprocess.Popen(["xclip", "-selection", "clipboard", "-quiet"],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()
        time.sleep(0.07)
        try:
            self.wait_for_release(original, allowed)
            self.send_keys(terminal)
            time.sleep(PASTE_CLIPBOARD_GRACE)
            clip = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                                  capture_output=True, timeout=1)
            if clip.stdout == text.encode("utf-8") and previous.returncode == 0:
                subprocess.run(["xclip", "-selection", "clipboard"], input=previous.stdout,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=1)


def wayland_types():
    # wl-paste falls back to a focused window on some KDE installations.
    result = subprocess.run([str(WAYLAND_CLIPBOARD), "--list-types"],
                            capture_output=True, text=True, timeout=1, check=True)
    return list(dict.fromkeys(result.stdout.splitlines()))


def read_wayland_clipboard():
    types = [mime for mime in wayland_types()
             if mime != "application/x-kde-onlyReplaceEmpty" and not mime.startswith(MARKER)]
    if len(types) > 16 and "image/png" in types:
        # Qt advertises the same image in dozens of interchangeable encodings.
        types = [mime for mime in types if mime == "image/png"
                 or not mime.startswith(("image/", "application/x-qt-image"))]
    if len(types) > 16:
        raise ClipboardError("The clipboard has too many formats to restore safely.")
    def read(mime):
        return subprocess.run([str(WAYLAND_CLIPBOARD), "--read", mime],
                              capture_output=True, timeout=1, check=True).stdout
    with ThreadPoolExecutor(max_workers=4) as workers:
        data = list(workers.map(read, types))
    if sum(map(len, data)) > 16 * 1024 * 1024:
        raise ClipboardError("The clipboard is too large to restore safely.")
    return list(zip(types, data))


def offer(helper, entries, before_publish=None, expected_marker=None):
    directory = Path(tempfile.mkdtemp(prefix="revoice-clip-", dir=os.environ.get("XDG_RUNTIME_DIR")))
    process = None
    try:
        (directory / "manifest").write_text("".join(mime + "\n" for mime, _ in entries))
        for index, (_, content) in enumerate(entries):
            (directory / str(index)).write_bytes(content)
        args = [str(helper), str(directory)]
        if before_publish:
            args.append("--guarded-offer")
        if expected_marker:
            args.extend(("--expect-marker", expected_marker))
        process = subprocess.Popen(args, stdout=subprocess.PIPE, bufsize=0,
                                   stdin=subprocess.PIPE if before_publish else subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        if before_publish:
            if offer_status(process) != b"watching":
                raise ClipboardError("This Wayland session couldn’t watch the clipboard.")
            before_publish()
            process.stdin.write(b"p")
            process.stdin.close()
        status = offer_status(process)
        if status == b"changed":
            raise ClipboardChanged("The clipboard changed before paste. The transcript is available to copy.")
        if status != b"ready":
            raise ClipboardError("This Wayland session couldn’t publish the clipboard.")
    except BaseException:
        if process:
            if process.stdin:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=2)
            process.stdout.close()
        raise
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if not before_publish:
        process.stdout.close()
    threading.Thread(target=process.wait, daemon=True).start()
    return process


def offer_status(process):
    readable, _, _ = select.select([process.stdout], [], [], 1)
    return process.stdout.readline().strip() if readable else b""


def copy_text(text):
    if WAYLAND:
        if KDE and WAYLAND_CLIPBOARD.is_file():
            encoded = text.encode("utf-8")
            try:
                offer(WAYLAND_CLIPBOARD, [(mime, encoded) for mime in TEXT_MIMES[:3]])
                return
            except ClipboardError:
                pass
        subprocess.run(["wl-copy"], input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=2, check=True)
    else:
        from gi.repository import Gtk
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()
