"""Revoice's dashboard, transcript history, and settings."""

import re
from datetime import datetime
from pathlib import Path

from gi.repository import Gdk, Gtk, Pango

from .config import candidate_logins, codex_token
from .desktop import KDE, MODIFIERS, NAMED_KEYS, sources
from .visuals import Icon
from .webview import LocalView

INK = (.29, .25, .22)
PAPER = (.984, .973, .949)


def box(vertical=True, spacing=0, name=None):
    widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                     spacing=spacing)
    if name:
        widget.set_name(name)
    return widget


def label(text, name=None, wrap=False):
    widget = Gtk.Label(label=text, xalign=0)
    if name:
        widget.set_name(name)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return widget


def pad(widget, top=17, right=18, bottom=17, left=18):
    widget.set_margin_top(top)
    widget.set_margin_end(right)
    widget.set_margin_bottom(bottom)
    widget.set_margin_start(left)
    return widget


def button(text, action, style="secondary", glyph=None):
    widget = Gtk.Button()
    widget.get_style_context().add_class(style)
    row = box(False, 7)
    if glyph:
        row.pack_start(Icon(glyph, 16, PAPER if style == "action" else INK), False, False, 0)
    row.pack_start(label(text), False, False, 0)
    widget.add(row)
    widget.connect("clicked", action)
    return widget


def simple_set_text(widget, text):
    widget.get_child().get_children()[-1].set_text(text)


def header(title, desc):
    area = box(spacing=6)
    area.pack_start(label(title, "page-title"), False, False, 0)
    area.pack_start(label(desc, "page-subtitle", True), False, False, 0)
    return area


def group():
    return box(name="settings-panel")


def row(parent, title, description, control, icon=None):
    outer = box(name="settings-row")
    area = pad(box(False, 14), 13, 16, 13, 16)
    area.set_valign(Gtk.Align.CENTER)
    if icon:
        badge = box(False, name="section-icon")
        badge.set_size_request(40, 40)
        badge.set_valign(Gtk.Align.CENTER)
        badge.pack_start(Icon(icon, 19, INK), True, True, 0)
        area.pack_start(badge, False, False, 0)
    body = box(spacing=4)
    body.pack_start(label(title, "row-title"), False, False, 0)
    body.pack_start(label(description, "subtle", True), False, False, 0)
    area.pack_start(body, True, True, 0)
    if control:
        control.set_valign(Gtk.Align.CENTER)
        area.pack_end(control, False, False, 0)
    outer.pack_start(area, True, True, 0)
    parent.pack_start(outer, False, False, 0)
    return body.get_children()[1]


def small_time(value):
    try:
        when = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return ""
    now = datetime.now()
    return when.strftime("%I:%M %p").lstrip("0") if when.date() == now.date() else when.strftime("%b %d, %I:%M %p")


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.app = app
        self.store = app.store
        self.current = "overview"
        self.feedback_message = ""
        self.feedback_error = False
        self.shortcut_description = ""
        self.set_title("Revoice")
        self.set_default_size(1112, 735)
        self.set_size_request(850, 610)
        self.set_icon_from_file(str(Path(__file__).with_name("icon.svg")))
        self.get_style_context().add_class("revoice")
        self.connect("delete-event", self.on_close)
        self.connect("key-press-event", self.on_key)
        self.sidebar_collapsed = False
        self.sidebar_labels = []
        self.make_titlebar()
        shell = box(False, name="revoice-shell")
        self.add(shell)
        self.sidebar = box(name="navigation")
        self.sidebar.set_size_request(220, -1)
        shell.pack_start(self.sidebar, False, False, 0)
        self.pages = Gtk.Stack()
        self.pages.set_name("canvas")
        self.pages.set_margin_end(8)
        self.pages.set_margin_bottom(8)
        self.pages.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.pages.set_transition_duration(145)
        shell.pack_start(self.pages, True, True, 0)
        self.nav = {}
        self.make_sidebar()
        self.make_overview()
        self.make_history()
        self.make_settings()
        self.show_all()
        self.navigate("overview")

    def make_titlebar(self):
        titlebar = Gtk.HeaderBar()
        titlebar.set_name("revoice-titlebar")
        titlebar.set_show_close_button(False)
        titlebar.set_has_subtitle(False)
        titlebar.set_custom_title(Gtk.Box())
        toggle = self.titlebar_button("sidebar", "Collapse sidebar", self.toggle_sidebar)
        self.sidebar_toggle = toggle
        titlebar.pack_start(toggle)
        controls = box(False)
        controls.pack_start(self.titlebar_button("minimize", "Minimize", self.iconify), False, False, 0)
        maximize = self.titlebar_button("maximize", "Maximize", self.toggle_maximize)
        controls.pack_start(maximize, False, False, 0)
        close = self.titlebar_button("close", "Close window", self.close)
        close.get_style_context().add_class("titlebar-close")
        controls.pack_start(close, False, False, 0)
        titlebar.pack_end(controls)
        self.connect("notify::is-maximized", self.update_maximize, maximize)
        self.set_titlebar(titlebar)

    def titlebar_button(self, glyph, name, callback):
        control = Gtk.Button()
        control.set_relief(Gtk.ReliefStyle.NONE)
        control.add(Icon(glyph, 16, INK))
        control.set_tooltip_text(name)
        control.get_accessible().set_name(name)
        control.connect("clicked", lambda _: callback())
        return control

    def update_maximize(self, _window, _property, control):
        icon = control.get_child()
        icon.name = "restore" if self.is_maximized() else "maximize"
        icon.queue_draw()
        name = "Restore window" if self.is_maximized() else "Maximize"
        control.set_tooltip_text(name)
        control.get_accessible().set_name(name)

    def toggle_maximize(self):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.sidebar.set_size_request(64 if self.sidebar_collapsed else 220, -1)
        for item in self.sidebar_labels:
            item.set_no_show_all(self.sidebar_collapsed)
            item.set_visible(not self.sidebar_collapsed)
        name = "Expand sidebar" if self.sidebar_collapsed else "Collapse sidebar"
        self.sidebar_toggle.set_tooltip_text(name)
        self.sidebar_toggle.get_accessible().set_name(name)
        if not self.sidebar_collapsed:
            self.animate_home()

    def make_sidebar(self):
        brand = pad(box(False, 10), 12, 15, 14, 18)
        icon = Gtk.Image.new_from_file(str(Path(__file__).with_name("icon.svg")))
        from gi.repository import GdkPixbuf
        icon.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(Path(__file__).with_name("icon.svg")), 22, 22, True))
        brand.pack_start(icon, False, False, 0)
        title = label("Revoice", "brand-name")
        self.sidebar_labels.append(title)
        brand.pack_start(title, False, False, 0)
        self.sidebar.pack_start(brand, False, False, 0)
        nav = pad(box(spacing=4), 0, 10, 0, 10)
        for key, title, glyph in [("overview", "Home", "mic"), ("history", "History", "history"),
                                  ("settings", "Settings", "settings")]:
            control = Gtk.Button()
            control.set_name("nav-button")
            content = box(False, 11)
            content.pack_start(Icon(glyph, 18, INK), False, False, 0)
            item = label(title)
            self.sidebar_labels.append(item)
            content.pack_start(item, False, False, 0)
            control.set_tooltip_text(title)
            control.get_accessible().set_name(title)
            control.add(content)
            control.connect("clicked", lambda _, page=key: self.navigate(page))
            self.nav[key] = control
            if key == "settings":
                self.sidebar.pack_end(pad(control, 0, 10, 10, 10), False, False, 0)
            else:
                nav.pack_start(control, False, False, 0)
        self.sidebar.pack_start(nav, False, False, 0)
        status = pad(box(False, 9, "sidebar-footer"), 10, 15, 16, 15)
        status.pack_start(pad(Icon("wave", 18, INK), 10, 0, 0, 3), False, False, 0)
        detail = pad(box(spacing=1), 10, 0, 0, 0)
        self.sidebar_labels.append(detail)
        self.side_provider = label("Codex dictation", "footer-title")
        self.side_status = label("Set up in Settings", "footer-desc")
        detail.pack_start(self.side_provider, False, False, 0)
        detail.pack_start(self.side_status, False, False, 0)
        status.pack_start(detail, True, True, 0)
        self.sidebar.pack_end(status, False, False, 0)

    def page(self, name):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = pad(box(spacing=19), 28, 29, 25, 29)
        viewport = Gtk.Viewport()
        viewport.set_shadow_type(Gtk.ShadowType.NONE)
        viewport.set_name("content")
        viewport.add(content)
        scroller.add(viewport)
        self.pages.add_named(scroller, name)
        return content

    def make_overview(self):
        self.home = LocalView("home", self.home_action)
        self.home.connect("map", lambda _: self.animate_home())
        self.pages.add_named(self.home, "overview")

    def animate_home(self):
        if self.current == "overview" and self.home.loaded and self.get_settings().props.gtk_enable_animations:
            self.home.evaluate_javascript("window.animateArrival()", -1)

    def update_meter(self, level):
        if self.current == "overview" and self.home.get_mapped() and self.home.loaded:
            self.home.evaluate_javascript(f"window.updateMeter({level:.3f})", -1)

    def home_action(self, action, value):
        if action == "record":
            self.record_action(None)
        elif action == "shortcut":
            self.shortcut_dialog()
        elif action == "history":
            self.navigate("history")
        elif action == "cancel" and self.app.state != "idle":
            self.app.cancel()
        elif action == "copy" and isinstance(value, str) and value.strip():
            if self.app.copy(value):
                self.home.evaluate_javascript("window.copyConfirmed()", -1)
        elif action == "language" and isinstance(value, str):
            self.language_combo.set_active_id(value)

    def refresh_home(self):
        text = self.app.last_text or (self.store.history[0].get("text", "") if self.store.history else "")
        ready = self.app.ready
        self.home.render({
            "state": self.app.state,
            "ready": ready,
            "provider": "Codex" if self.store.settings["provider"] == "codex" else "OpenAI",
            "keys": self.app.shortcut_label.split("+") if self.app.shortcut_label else [],
            "hold": self.app.shortcut_can_hold and self.store.settings["hold"],
            "description": self.shortcut_description if ready else "Connect a speech provider to start dictating.",
            "language": self.store.settings["language"],
            "languages": self.desktop_languages,
            "text": text,
            "recent": [[entry.get("text", ""), small_time(entry.get("at"))] for entry in self.store.history[:3]],
            "feedback": self.feedback_message,
            "error": self.feedback_error,
        })

    def make_history(self):
        page = self.page("history")
        mast = box(False, 12)
        mast.pack_start(header("History", "Search and copy recent transcripts from this computer."), True, True, 0)
        clear = button("Clear history", lambda _: self.confirm_clear(), "minimal")
        clear.set_valign(Gtk.Align.START)
        mast.pack_start(clear, False, False, 0)
        page.pack_start(mast, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search transcripts")
        self.search.connect("search-changed", lambda _: self.refresh_history())
        page.pack_start(self.search, False, False, 0)
        self.history_list = group()
        page.pack_start(self.history_list, False, False, 0)

    def make_settings(self):
        self.settings_window = Gtk.Window(title="Settings", transient_for=self, modal=True, destroy_with_parent=True)
        self.settings_window.set_decorated(False)
        self.settings_window.set_default_size(1000, 652)
        self.settings_window.set_name("settings-dialog")
        self.settings_window.connect("delete-event", lambda *_: self.settings_window.hide_on_delete())
        self.settings_window.connect("key-press-event", self.on_settings_key)
        shell = box(False)
        rail = box(name="settings-rail")
        rail.set_size_request(220, -1)
        rail.pack_start(pad(label("Settings", "panel-title-large"), 24, 16, 18, 22), False, False, 0)
        self.settings_window.add(shell)
        shell.pack_start(rail, False, False, 0)
        right = box()
        close = button("×", lambda _: self.settings_window.hide(), "minimal")
        close.get_accessible().set_name("Close settings")
        close.set_halign(Gtk.Align.END)
        right.pack_start(pad(close, 7, 10, 0, 0), False, False, 0)
        self.settings_pages = Gtk.Stack()
        right.pack_start(self.settings_pages, True, True, 0)
        shell.pack_start(right, True, True, 0)
        self.settings_nav = {}
        for key, title, glyph in (
            ("general", "General", "keys"), ("speech", "Speech", "mic"), ("history", "History", "history"),
        ):
            item = button(title, lambda _, selected=key: self.navigate_settings(selected), "minimal", glyph)
            item.set_name("nav-button")
            rail.pack_start(pad(item, 0, 10, 3, 10), False, False, 0)
            self.settings_nav[key] = item

        page = self.settings_page("speech", "Speech", "Choose a transcription provider, language, and microphone.")
        provider = group()
        self.provider_combo = self.combo([("codex", "Codex sign-in"), ("openai", "OpenAI API")], "provider",
                                         self.change_provider)
        row(provider, "Speech provider", "Audio goes to your selected provider while you dictate.", self.provider_combo, "wave")
        connection = box(False, 5)
        self.secret_button = button("Connect", lambda _: self.connection_dialog())
        self.secret_button.set_size_request(114, -1)
        connection.pack_start(self.secret_button, False, False, 0)
        self.provider_desc = row(provider, "Connection", "", connection)
        self.desktop_languages = [("", "Auto-detect"), ("en", "English"), ("bn", "Bengali"), ("hi", "Hindi"),
                             ("fr", "French"), ("de", "German"), ("es", "Spanish"), ("ta", "Tamil"),
                             ("te", "Telugu"), ("ja", "Japanese"), ("ko", "Korean"), ("zh", "Chinese"),
                             ("ar", "Arabic"), ("pt", "Portuguese"), ("it", "Italian"), ("ur", "Urdu")]
        self.language_combo = self.combo(self.desktop_languages, "language", self.refresh_home)
        row(provider, "Spoken language", "Set a language hint or let the provider detect it.", self.language_combo)
        self.source_combo = self.combo([("", "System default"), *sources()], "device")
        row(provider, "Microphone", "Use the default PipeWire input or select a device.", self.source_combo)
        page.pack_start(provider, False, False, 0)

        page = self.settings_page("general", "General", "Choose how to start dictation and where text goes.")
        shortcut = group()
        self.settings_shortcut = row(shortcut, "Global shortcut", "", button("Change shortcut", lambda _: self.shortcut_dialog()), "keys")
        row(shortcut, "Hold and double-press", "Turn off to use one tap to start and another to stop.",
            self.switch("hold", self.refresh_shortcut))
        row(shortcut, "Paste into the focused app", "Revoice sends a paste keystroke and restores your previous clipboard.",
            self.switch("auto_paste", lambda: self.refresh_status()))
        row(shortcut, "Paste key", "Automatic uses Ctrl+Shift+V in known terminals.",
            self.combo([("auto", "Automatic"), ("regular", "Ctrl+V"), ("terminal", "Ctrl+Shift+V")], "paste_key"))
        page.pack_start(shortcut, False, False, 0)

        page = self.settings_page("history", "History", "Manage transcripts saved on this computer.")
        data = group()
        row(data, "Keep transcript history", "Saves up to 150 transcripts locally. Revoice does not save microphone audio.",
            self.switch("save_history"))
        page.pack_start(data, False, False, 0)
        self.settings_feedback = label("", "status-attention", True)
        right.pack_end(pad(self.settings_feedback, 0, 24, 16, 24), False, False, 0)
        self.navigate_settings("general")

    def settings_page(self, key, title, description):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = pad(box(spacing=20), 2, 38, 32, 38)
        page.pack_start(header(title, description), False, False, 0)
        scroller.add(page)
        self.settings_pages.add_named(scroller, key)
        return page

    def navigate_settings(self, page):
        self.settings_pages.set_visible_child_name(page)
        for key, item in self.settings_nav.items():
            style = item.get_style_context()
            if key == page:
                style.add_class("active")
            else:
                style.remove_class("active")

    def on_settings_key(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.settings_window.hide()
            return True
        return False

    def change_provider(self):
        if self.store.settings["provider"] == "openai":
            self.app.load_key()
        self.refresh_status()

    def combo(self, choices, key, after=None):
        control = Gtk.ComboBoxText()
        control.set_size_request(154, -1)
        for identifier, name in choices:
            control.append(identifier, name)
        if not control.set_active_id(self.store.settings[key]):
            control.set_active(0)

        def changed(widget):
            value = widget.get_active_id()
            if value is not None:
                self.store.set(key, value)
                if after:
                    after()

        control.connect("changed", changed)
        return control

    def switch(self, key, after=None):
        control = Gtk.Switch(active=self.store.settings[key])
        control.set_halign(Gtk.Align.END)
        def changed(widget, _param):
            self.store.set(key, widget.get_active())
            if after:
                after()
        control.connect("notify::active", changed)
        return control

    def record_action(self, _button):
        if self.app.state == "idle" and not self.app.ready:
            self.connection_dialog()
        else:
            self.app.toggle(dashboard=True)

    def navigate(self, page):
        if page == "settings":
            self.refresh_status()
            self.settings_window.show_all()
            self.settings_window.present()
            return
        self.settings_window.hide()
        self.current = page
        self.pages.set_visible_child_name(page)
        for key, control in self.nav.items():
            style = control.get_style_context()
            if key == page:
                style.add_class("active")
            else:
                style.remove_class("active")
        if page == "history":
            self.refresh_history()

    def refresh_status(self):
        provider = self.store.settings["provider"]
        self.side_provider.set_text("Codex dictation" if provider == "codex" else "OpenAI API")
        self.side_status.set_text("Connected" if self.app.ready else "Set up in Settings")
        if provider == "codex":
            self.provider_desc.set_text("Uses your local Codex ChatGPT login through an unofficial connection.")
        else:
            self.provider_desc.set_text("Uses GPT-Transcribe and separate API billing. The key is stored in your keyring.")
        simple_set_text(self.secret_button, "Manage" if self.app.ready else "Connect")
        self.refresh_shortcut()

    def refresh_shortcut(self):
        shortcut = self.app.shortcut_label
        if not shortcut:
            description = self.app.shortcut_error or "Assign a shortcut to dictate from another app."
        elif not self.app.shortcut_can_hold or not self.store.settings["hold"]:
            description = "Tap once to start and again to stop."
        else:
            description = "Hold to speak and release to paste. Double-press for hands-free."
        self.shortcut_description = description
        self.settings_shortcut.set_text(f"{shortcut} · {description}" if shortcut else description)
        self.refresh_home()

    def refresh_history(self):
        for child in self.history_list.get_children():
            child.destroy()
        query = self.search.get_text().strip().casefold()
        records = [entry for entry in self.store.history if query in entry.get("text", "").casefold()]
        if not records:
            details = "No transcripts match that search." if query else "Your first saved dictation will appear here."
            self.history_list.pack_start(pad(label(details, "muted"), 23, 18, 23, 18), False, False, 0)
        for entry in records:
            outer = pad(box(False, 12, "transcript-row"), 10, 15, 10, 15)
            body = box(spacing=5)
            total = round(entry.get("duration", 0))
            body.pack_start(label(f"{small_time(entry.get('at'))}  ·  {total // 60}:{total % 60:02d}", "subtle"), False, False, 0)
            message = label(entry["text"], "manuscript-text", wrap=True)
            message.set_selectable(True)
            message.set_max_width_chars(75)
            body.pack_start(message, False, False, 0)
            outer.pack_start(body, True, True, 0)
            action = button("Copy", lambda control, text=entry["text"]: self.copy(control, text), "minimal", "copy")
            action.set_valign(Gtk.Align.START)
            outer.pack_end(action, False, False, 0)
            self.history_list.pack_start(outer, False, False, 0)
        self.history_list.show_all()

    def refresh_latest(self):
        self.refresh_home()

    def copy(self, click, text):
        if self.app.copy(text):
            simple_set_text(click, "Copied")

    def feedback(self, message, error=False):
        self.feedback_message = message
        self.feedback_error = error
        self.settings_feedback.set_text(message)
        self.settings_feedback.set_name("status-error" if error else "status-attention")
        self.refresh_home()

    def dialog(self, title, desc):
        parent = self.settings_window if self.settings_window.get_visible() else self
        dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True, destroy_with_parent=True)
        dialog.set_name("revoice-dialog")
        dialog.set_default_size(480, -1)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE).get_style_context().add_class("secondary")
        body = pad(box(spacing=13), 16, 18, 14, 18)
        body.pack_start(label(title, "panel-title-large"), False, False, 0)
        body.pack_start(label(desc, "muted", True), False, False, 0)
        dialog.get_content_area().pack_start(body, True, True, 0)
        return dialog, body

    def connection_dialog(self):
        if self.store.settings["provider"] == "openai":
            return self.api_dialog()
        dialog, body = self.dialog(
            "Connect Codex",
            "Revoice uses a Codex ChatGPT sign-in for dictation. "
            "This connection is unofficial and can change.",
        )
        status = label("", "status-attention", True)
        def use(path):
            try:
                codex_token(str(path))
            except ValueError as error:
                status.set_text(str(error))
                return
            self.store.set("codex_auth", str(path))
            self.refresh_status()
            self.feedback("Codex sign-in connected.")
            dialog.response(Gtk.ResponseType.OK)

        def choose(_control):
            picker = Gtk.FileChooserDialog(title="Choose Codex auth.json", transient_for=dialog,
                                           action=Gtk.FileChooserAction.OPEN)
            picker.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Use sign-in", Gtk.ResponseType.OK)
            picker.set_show_hidden(True)
            picker.set_current_folder(str(Path.home()))
            if picker.run() == Gtk.ResponseType.OK:
                path = picker.get_filename()
                picker.destroy()
                use(path)
            else:
                picker.destroy()

        login = next((path for path in candidate_logins() if path.is_file()), None)
        if login:
            body.pack_start(button("Use existing Codex sign-in", lambda _: use(login), "action", "check"), False, False, 0)
        body.pack_start(button("Sign in with Codex", lambda _: status.set_text(self.app.start_login())), False, False, 0)
        body.pack_start(button("Choose another Codex profile…", choose, "minimal"), False, False, 0)
        if self.store.settings["codex_auth"]:
            def disconnect(_control):
                self.store.set("codex_auth", "")
                self.refresh_status()
                self.feedback("Codex disconnected from Revoice.")
                dialog.response(Gtk.ResponseType.OK)
            body.pack_start(button("Disconnect from Revoice", disconnect, "minimal"), False, False, 0)
        body.pack_start(status, False, False, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def api_dialog(self):
        dialog, body = self.dialog("Connect OpenAI API", "Enter an OpenAI Platform API key. Revoice stores it in your desktop keyring.")
        key = Gtk.Entry()
        key.set_visibility(False)
        key.set_placeholder_text("OpenAI API key")
        body.pack_start(key, False, False, 0)
        feedback = label("", "status-attention", True)
        def save(_control, remove=False):
            value = "" if remove else key.get_text().strip()
            if not value and not remove:
                feedback.set_text("Enter your API key.")
                return
            if value and not re.fullmatch(r"sk-[\w-]+", value):
                feedback.set_text("Enter a valid OpenAI Platform key.")
                return
            error = self.app.update_key(value)
            if error:
                feedback.set_text(error)
                return
            self.refresh_status()
            dialog.response(Gtk.ResponseType.OK)
        body.pack_start(button("Save key", save, "action"), False, False, 0)
        if self.app.ready:
            body.pack_start(button("Remove key", lambda control: save(control, True), "minimal"), False, False, 0)
        body.pack_start(feedback, False, False, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def shortcut_dialog(self):
        desc = ("Press the keys together, then release them. Try Ctrl+Super, Shift+Super, "
                "or a regular combo such as Ctrl+Alt+Space.") if KDE else (
                    "Press a modifier and a regular key together, then release them.")
        dialog, body = self.dialog("Change shortcut", desc)
        prompt = label("Press a key combination…", "keyboard-cap")
        status = label("", "status-attention", True)
        body.pack_start(prompt, False, False, 0)
        if KDE:
            examples = box(False, 6)
            for item in ("Ctrl+Super", "Shift+Super", "Ctrl+Alt+Space"):
                examples.pack_start(button(item, lambda _, value=item: apply(value), "minimal"), False, False, 0)
            body.pack_start(examples, False, False, 0)
        body.pack_start(status, False, False, 0)
        pressed = set()
        modifiers = {"Control_L": "Ctrl", "Control_R": "Ctrl", "Shift_L": "Shift", "Shift_R": "Shift",
                     "Alt_L": "Alt", "Alt_R": "Alt", "Super_L": "Super", "Super_R": "Super",
                     "Meta_L": "Super", "Meta_R": "Super"}
        selected = []
        self.app.shortcut_capturing = True

        def apply(value):
            error = self.app.assign_shortcut(value)
            if error:
                status.set_text(error)
            else:
                dialog.response(Gtk.ResponseType.OK)

        def press(_widget, event):
            name = Gdk.keyval_name(event.keyval)
            if name == "Escape":
                dialog.response(Gtk.ResponseType.CANCEL)
                return True
            value = modifiers.get(name, {"space": "Space", "Return": "Enter"}.get(name, name))
            if value is None:
                return True
            if len(value) == 1:
                value = value.upper()
            if value in MODIFIERS or value in NAMED_KEYS or len(value) == 1:
                pressed.add(event.hardware_keycode)
                if value not in selected:
                    selected.append(value)
                prompt.set_text("+".join(selected))
            return True

        def release(_widget, event):
            pressed.discard(event.hardware_keycode)
            if not pressed and selected:
                value = "+".join(selected)
                selected.clear()
                apply(value)
            return True

        dialog.connect("key-press-event", press)
        dialog.connect("key-release-event", release)
        dialog.show_all()
        dialog.run()
        self.app.shortcut_capturing = False
        dialog.destroy()

    def confirm_clear(self):
        dialog, body = self.dialog("Clear transcript history?", "This removes your saved Revoice transcripts from this computer.")
        body.pack_start(button("Clear history", lambda _: dialog.response(Gtk.ResponseType.OK), "action"), False, False, 0)
        dialog.show_all()
        confirmed = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        if confirmed:
            self.store.clear()
            self.app.last_text = ""
            self.refresh_history()
            self.refresh_latest()

    def on_close(self, *_args):
        self.settings_window.hide()
        self.hide()
        return True

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape and self.app.state != "idle":
            self.app.cancel()
            return True
        return False
