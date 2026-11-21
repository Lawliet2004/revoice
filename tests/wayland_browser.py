"""Verify delayed Chromium paste in native Wayland and XWayland windows."""

import http.server
import json
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from evdev import UInput, ecodes

from revoice_app import config
from wayland_ui import CTRL, SUPER, TRANSCRIPT, DesktopTest, TestRecording, clipboard_digest, revoice, settle, wait_for

TITLE = "Revoice clipboard test"
HTML = b"""<!doctype html><title>Revoice clipboard test</title>
<textarea autofocus>Replace this text</textarea>
<script>
const field = document.querySelector('textarea');
field.focus();
field.select();
field.addEventListener('keydown', event => {
  if (event.ctrlKey && event.key === 'v') {
    // Model a busy renderer that handles paste after the old clipboard timeout.
    const deadline = performance.now() + 780;
    while (performance.now() < deadline) {}
  }
});
field.addEventListener('input', event => fetch('/', {
  method: 'POST', body: JSON.stringify([event.inputType, field.value]),
}));
</script>"""


class TestPage(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML)

    def do_POST(self):
        content = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.results.append(json.loads(content))
        self.send_response(204)
        self.end_headers()


class BrowserTest(DesktopTest):
    def __init__(self, keyboard, shortcut, server):
        super().__init__(keyboard, shortcut)
        self.server = server

    def browser_focused(self):
        token, app_class = self.focus.window
        if not token or "chrome" not in app_class.lower():
            return False
        info = self.bus.call_blocking(
            "org.kde.KWin", "/KWin", "org.kde.KWin", "getWindowInfo", "s", (token,), timeout=1,
        )
        return info.get("caption") == TITLE

    def emit_key(self, code, down):
        assert self.browser_focused(), "The test browser lost keyboard focus"
        self.keyboard.write(ecodes.EV_KEY, code, int(down))
        self.keyboard.syn()
        settle(.03)

    def exercise(self):
        wait_for(lambda: self.shortcut_can_hold, "KWin's modifier state protocol is unavailable")
        original_clipboard = clipboard_digest()
        for backend in ("wayland", "x11"):
            self.server.results.clear()
            with tempfile.TemporaryDirectory(prefix="revoice-chrome-") as profile:
                address = f"http://127.0.0.1:{self.server.server_port}"
                browser = subprocess.Popen([
                    "google-chrome", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                    f"--user-data-dir={profile}", f"--ozone-platform={backend}", f"--app={address}",
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    wait_for(self.browser_focused, f"{backend}: test browser did not focus", 12)
                    settle(.4)
                    self.emit_key(CTRL, True)
                    self.emit_key(SUPER, True)
                    wait_for(lambda: self.state == "recording", "The shortcut did not start dictation")
                    settle(.58)
                    self.emit_key(CTRL, False)
                    self.emit_key(SUPER, False)
                    wait_for(lambda: self.state == "idle", "The paste did not finish", 8)
                    wait_for(lambda: ["insertFromPaste", TRANSCRIPT] in self.server.results,
                             f"{backend}: {self.window.feedback_message}", 2)
                    assert self.browser_focused() and not self.pill.get_visible()
                    assert clipboard_digest() == original_clipboard
                    print(f"{backend}: selected text replaced, clipboard restored, HUD dismissed", flush=True)
                finally:
                    if browser.poll() is None:
                        browser.terminate()
                    browser.wait(timeout=8)
                    settle(.3)


def main():
    if revoice.session_bus().name_has_owner(revoice.APP_ID):
        raise SystemExit("Quit the running Revoice instance before running the browser test.")
    shortcut = config.Store().settings["shortcut"]
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), TestPage) as server:
        server.results = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix="revoice-browser-test-") as folder, patch.multiple(
            config, SETTINGS=Path(folder) / "settings.json", HISTORY=Path(folder) / "history.json",
        ), patch.object(revoice, "Recording", TestRecording), UInput(
            {ecodes.EV_KEY: [CTRL, SUPER]}, name="Revoice browser test keyboard",
        ) as keyboard:
            app = BrowserTest(keyboard, shortcut, server)
            app.run(["revoice"])
            if app.failure:
                raise app.failure
        server.shutdown()


if __name__ == "__main__":
    main()
