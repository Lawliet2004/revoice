"""Host Reflow's local UI fragments in non-networked GTK web views."""

import base64
import json
from pathlib import Path

import gi

gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, WebKit2

ASSETS = Path(__file__).with_name("web")
CONTEXT = None


class LocalView(WebKit2.WebView):
    def __init__(self, page, action, transparent=False):
        global CONTEXT
        if CONTEXT is None:
            CONTEXT = WebKit2.WebContext.new_ephemeral()
        manager = WebKit2.UserContentManager()
        super().__init__(web_context=CONTEXT, user_content_manager=manager)
        manager.register_script_message_handler("revoice")
        manager.connect("script-message-received::revoice", self.on_message)
        self.action = action
        self.loaded = False
        self.state = None
        self.get_settings().set_enable_html5_local_storage(False)
        self.get_settings().set_enable_page_cache(False)
        self.get_settings().set_enable_write_console_messages_to_stdout(False)
        if transparent:
            self.set_background_color(Gdk.RGBA(red=0, green=0, blue=0, alpha=0))
        else:
            self.set_background_color(Gdk.RGBA(red=1, green=.9804, blue=.9137, alpha=1))
        self.connect("context-menu", lambda *_: True)
        self.connect("load-changed", self.on_load)
        self.connect("decide-policy", self.on_policy)
        styles = "\n".join((ASSETS / name).read_text() for name in ("reflow.css", "adapter.css"))
        content = (ASSETS / f"{page}.html").read_text()
        if page == "home":
            illustration = base64.b64encode((ASSETS / "manuscript-art.webp").read_bytes()).decode("ascii")
            content = content.replace(
                "<!-- manuscript-illustration -->",
                f'<img class="manuscript-art" src="data:image/webp;base64,{illustration}" alt="">',
            )
        self.load_html(
            "<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta http-equiv='Content-Security-Policy' "
            "content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'\">"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<style>{styles}</style>{content}</html>", None,
        )

    def on_message(self, _manager, result):
        try:
            message = json.loads(result.get_js_value().to_string())
        except ValueError:
            return
        if isinstance(message, dict):
            self.action(message.get("action"), message.get("value"))

    def on_policy(self, _view, decision, kind):
        if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            if decision.get_navigation_action().get_request().get_uri() != "about:blank":
                decision.ignore()
                return True
        return False

    def on_load(self, _view, event):
        if event == WebKit2.LoadEvent.FINISHED:
            self.loaded = True
            if self.state is not None:
                self.render(self.state)

    def render(self, state):
        if self.loaded:
            self.evaluate_javascript(f"window.renderState({json.dumps(state)})", -1)
        self.state = state
