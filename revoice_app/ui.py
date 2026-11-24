"""Revoice's dashboard, transcript history, and settings."""

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from gi.repository import Gdk, Gtk, Pango

from .appearance import (
    ACCOUNTS, account_view, accent_rgb, icon_rgb, listening, stylesheet, surface_rgb, web_appearance,
)
from .config import (
    HISTORY_DAYS, candidate_claude_logins, candidate_logins, claude_available, claude_token, codex_token,
    connection_label, kept_until,
)
from .desktop import KDE, MODIFIERS, NAMED_KEYS, sources
from .visuals import Icon, Swatch
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
        icon = Icon(glyph, 16, PAPER if style == "action" else INK)
        icon.follows_ink = style != "action"
        row.pack_start(icon, False, False, 0)
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
        self.dashboard = Gtk.Overlay()
        self.add(self.dashboard)
        self.shell = box(False, name="revoice-shell")
        self.dashboard.add(self.shell)
        self.sidebar = box(name="navigation")
        self.sidebar.set_size_request(220, -1)
        self.shell.pack_start(self.sidebar, False, False, 0)
        self.pages = Gtk.Stack()
        self.pages.set_name("canvas")
        self.pages.set_margin_end(8)
        self.pages.set_margin_bottom(8)
        self.pages.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.pages.set_transition_duration(145)
        self.shell.pack_start(self.pages, True, True, 0)
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
        toggle = self.icon_button("sidebar", "Collapse sidebar", self.toggle_sidebar)
        self.sidebar_toggle = toggle
        titlebar.pack_start(toggle)
        controls = box(False)
        controls.pack_start(self.icon_button("minimize", "Minimize", self.iconify), False, False, 0)
        maximize = self.icon_button("maximize", "Maximize", self.toggle_maximize)
        controls.pack_start(maximize, False, False, 0)
        close = self.icon_button("close", "Close window", self.close)
        close.get_style_context().add_class("titlebar-close")
        controls.pack_start(close, False, False, 0)
        titlebar.pack_end(controls)
        self.connect("notify::is-maximized", self.update_maximize, maximize)
        self.titlebar = titlebar
        titlebar_layer = Gtk.Overlay()
        titlebar_layer.add(titlebar)
        self.titlebar_backdrop = self.settings_backdrop()
        self.titlebar_backdrop.set_name("settings-titlebar-backdrop")
        self.titlebar_backdrop.set_no_show_all(True)
        titlebar_layer.add_overlay(self.titlebar_backdrop)
        self.set_titlebar(titlebar_layer)

    def icon_button(self, glyph, name, callback):
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
            content.pack_start(Icon(glyph, 20 if key == "settings" else 18, INK), False, False, 0)
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
        self.side_provider = label("Codex", "footer-title")
        self.side_status = label("Sign in to Codex", "footer-desc")
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
        self.home = LocalView("home", self.home_action, appearance=web_appearance(self.store.settings))
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

    def visible_transcript(self):
        if self.app.state == "recording" or (self.app.state == "processing" and self.app.live_text):
            return self.app.live_text
        return self.app.last_text or (self.store.history[0].get("text", "") if self.store.history else "")

    def refresh_home(self):
        provider = self.store.settings["provider"]
        ready = self.app.ready
        names = {"codex": "Codex", "claude": "Claude", "openai": "OpenAI"}
        self.home.render({
            "state": self.app.state,
            "ready": ready,
            "provider": names.get(provider, "Codex"),
            "connection": connection_label(provider, ready),
            "keys": self.app.shortcut_label.split("+") if self.app.shortcut_label else [],
            "hold": self.app.shortcut_can_hold and self.store.settings["hold"],
            "description": self.shortcut_description if ready else "Sign in with Codex or Claude from Settings.",
            "appearance": web_appearance(self.store.settings),
            "language": self.store.settings["language"],
            "languages": self.desktop_languages,
            "text": self.visible_transcript(),
            "recent": [[entry.get("text", ""), small_time(entry.get("at"))] for entry in self.store.history[:3]],
            "feedback": self.feedback_message,
            "error": self.feedback_error,
        })

    def make_history(self):
        page = self.page("history")
        mast = box(False, 12)
        mast.pack_start(header(
            "Library",
            "Dictated text stays on this computer for 3 days, then it is removed. Recordings are not saved.",
        ), True, True, 0)
        clear = button("Clear library", lambda _: self.confirm_clear(), "minimal")
        clear.set_valign(Gtk.Align.START)
        mast.pack_start(clear, False, False, 0)
        page.pack_start(mast, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search transcripts")
        self.search.connect("search-changed", lambda _: self.refresh_history())
        page.pack_start(self.search, False, False, 0)
        self.library_count = label("", "subtle")
        page.pack_start(self.library_count, False, False, 0)
        self.history_list = group()
        page.pack_start(self.history_list, False, False, 0)

    def make_settings(self):
        self.settings_layer = Gtk.Overlay()
        self.dashboard.add_overlay(self.settings_layer)
        self.settings_layer.add(self.settings_backdrop())

        panel = pad(Gtk.EventBox(), 24, 28, 28, 28)
        panel.set_name("settings-dialog")
        self.settings_layer.add_overlay(panel)
        shell = box(False)
        panel.add(shell)
        rail = box(name="settings-rail")
        rail.set_size_request(220, -1)
        rail.pack_start(pad(label("Settings", "settings-title"), 25, 16, 18, 20), False, False, 0)
        shell.pack_start(rail, False, False, 0)
        pane = Gtk.Overlay()
        shell.pack_start(pane, True, True, 0)
        right = box()
        pane.add(right)
        self.settings_close = self.icon_button("close", "Close settings", self.close_settings)
        self.settings_close.set_name("settings-close")
        self.settings_close.set_halign(Gtk.Align.END)
        self.settings_close.set_valign(Gtk.Align.START)
        pane.add_overlay(pad(self.settings_close, 10, 10, 0, 0))
        self.settings_pages = Gtk.Stack()
        right.pack_start(self.settings_pages, True, True, 0)
        self.settings_nav = {}
        groups = (
            ("Dictation", (
                ("speech", "Speech", "mic"),
                ("claude", "Claude sign-in", "keys"),
            )),
            ("App", (
                ("general", "General", "settings"),
                ("appearance", "Appearance", "look"),
                ("history", "Library", "history"),
            )),
        )
        for caption, items in groups:
            rail.pack_start(pad(label(caption, "settings-group"), 14, 18, 2, 20), False, False, 0)
            for key, title, glyph in items:
                item = button(title, lambda _, selected=key: self.navigate_settings(selected), "minimal", glyph)
                item.set_name("nav-button")
                rail.pack_start(pad(item, 0, 10, 3, 10), False, False, 0)
                self.settings_nav[key] = item

        page = self.settings_page(
            "speech", "Speech",
            "Claude sign-in is the first row. Codex and OpenAI are below. The marked card is the one dictation uses.",
        )
        self.accounts = {}
        claude_gate = group()
        row(
            claude_gate,
            "Claude sign-in",
            ACCOUNTS["claude"]["absent"],
            button("Sign in with Claude", lambda _button: self.sign_in_provider("claude"), "action"),
            "keys",
        )
        page.pack_start(claude_gate, False, False, 0)
        cards = box(spacing=12)
        for provider in ("codex", "openai"):
            cards.pack_start(self.account_card(provider), False, False, 0)
        page.pack_start(cards, False, False, 0)
        listening = group()
        self.desktop_languages = [("", "Auto-detect"), ("en", "English"), ("bn", "Bengali"), ("hi", "Hindi"),
                             ("fr", "French"), ("de", "German"), ("es", "Spanish"), ("ta", "Tamil"),
                             ("te", "Telugu"), ("ja", "Japanese"), ("ko", "Korean"), ("zh", "Chinese"),
                             ("ar", "Arabic"), ("pt", "Portuguese"), ("it", "Italian"), ("ur", "Urdu")]
        self.language_combo = self.combo(self.desktop_languages, "language", self.refresh_home)
        row(listening, "Spoken language", "Set a language hint or let the provider detect it.", self.language_combo)
        self.source_combo = self.combo([("", "System default"), *sources()], "device")
        row(listening, "Microphone", "Use the default PipeWire input or select a device.", self.source_combo, "mic")
        page.pack_start(listening, False, False, 0)

        page = self.settings_page(
            "claude", "Claude sign-in",
            "Sign in with Claude Code. Revoice uses that Claude.ai account, not an API key.",
        )
        page.pack_start(self.account_card("claude"), False, False, 0)

        page = self.settings_page("general", "General", "Choose how to start dictation and where text goes.")
        shortcut = group()
        self.settings_shortcut = row(shortcut, "Global shortcut", "", button("Change shortcut", lambda _: self.shortcut_dialog()), "keys")
        row(shortcut, "Hold and double-press", "Turn off to use one tap to start and another to stop.",
            self.switch("hold", self.refresh_shortcut))
        row(shortcut, "Paste into the focused app",
            "Revoice pastes into the field you were typing in and restores your previous clipboard. Live words are turned on under Appearance.",
            self.switch("auto_paste", lambda: self.refresh_status()))
        row(shortcut, "Paste key", "Automatic uses Ctrl+Shift+V in known terminals.",
            self.combo([("auto", "Automatic"), ("regular", "Ctrl+V"), ("terminal", "Ctrl+Shift+V")], "paste_key"))
        page.pack_start(shortcut, False, False, 0)

        page = self.settings_page("history", "Library", "Text from dictation is kept on this computer, then removed.")
        data = group()
        row(data, "Keep a text library",
            f"Saves the words, not the recording, for {HISTORY_DAYS} days. Up to 150 texts.",
            self.switch("save_history"))
        page.pack_start(data, False, False, 0)

        page = self.settings_page(
            "appearance", "Appearance",
            "Warm paper is the manuscript desk. These choices change the desk, the ink, the listening pill, and the size of the words.",
        )
        self.appearance_chips = {}
        desk = group()
        self.choice_row(desk, "Paper", "Warm is the original desk. Neutral is quieter. Cool is stone.",
                        "tone", (("warm", "Warm"), ("neutral", "Neutral"), ("cool", "Cool")))
        self.choice_row(desk, "Ink", "The record button, links, and the listening caret use this colour.",
                        "accent",
                        (("copper", "Copper"), ("ink", "Ink"), ("sea", "Sea"), ("forest", "Forest"), ("plum", "Plum")),
                        swatches=True)
        self.choice_row(desk, "Text size", "Home and Settings grow together.",
                        "text_size", (("compact", "Compact"), ("regular", "Regular"), ("large", "Large")))
        self.choice_row(desk, "Density", "How much air the home sheet keeps around the words.",
                        "density", (("compact", "Tight"), ("regular", "Regular"), ("roomy", "Roomy")))
        self.choice_row(desk, "Corners", "How round the sheets and buttons are.",
                        "corners", (("sharp", "Sharp"), ("soft", "Soft"), ("round", "Round")))
        self.choice_row(desk, "Reading face", "The face used for dictated words.",
                        "reading_face", (("book", "Book"), ("sans", "Sans"), ("mono", "Mono")))
        page.pack_start(self.named_group("Desk", desk), False, False, 0)
        listening_pill = group()
        self.choice_row(listening_pill, "Motion", "Ink is a quill line. Bars is the original equalizer.",
                        "waveform", (("bars", "Bars"), ("ribbon", "Ribbon"), ("ink", "Ink"), ("dots", "Dots")))
        self.choice_row(listening_pill, "Pill size", "The waveform pill. Live words use the wide sheet instead.",
                        "pill_size", (("compact", "Compact"), ("regular", "Regular"), ("large", "Large")))
        self.choice_row(listening_pill, "Surface", "Charcoal sits on any desk. Paper matches the sheet.",
                        "pill_surface", (("charcoal", "Charcoal"), ("paper", "Paper")))
        row(listening_pill, "Live words",
            "The pill grows and shows the words while you speak. When you stop, they paste into the text field you were typing in.",
            self.switch("live_pill", self.sync_listening_pill))
        page.pack_start(self.named_group("Listening pill", listening_pill), False, False, 0)
        preview = box(name="settings-panel")
        preview.pack_start(pad(label("Speak freely.", "appearance-preview"), 18, 18, 2, 18), False, False, 0)
        self.appearance_note = label(self.pill_caption(), "muted", True)
        preview.pack_start(pad(self.appearance_note, 0, 18, 8, 18), False, False, 0)
        preview.pack_start(pad(label("Connected via Codex", "status-attention"), 0, 18, 18, 18), False, False, 0)
        page.pack_start(preview, False, False, 0)

        self.settings_feedback = label("", "status-attention", True)
        right.pack_end(pad(self.settings_feedback, 0, 24, 16, 24), False, False, 0)
        self.settings_layer.show_all()
        self.settings_layer.hide()
        self.settings_layer.set_no_show_all(True)
        self.navigate_settings("speech")
        self.apply_appearance()
        self.refresh_accounts()

    def settings_page(self, key, title, description):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = pad(box(spacing=24), 28, 32, 24, 32)
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

    def settings_backdrop(self):
        backdrop = Gtk.EventBox()
        backdrop.get_style_context().add_class("settings-backdrop")
        backdrop.connect("button-press-event", self.dismiss_settings)
        return backdrop

    def dismiss_settings(self, _backdrop, _event):
        self.close_settings()
        return True

    def close_settings(self):
        if self.settings_layer.get_visible():
            self.settings_layer.hide()
            self.titlebar_backdrop.hide()
            self.shell.set_sensitive(True)
            self.titlebar.set_sensitive(True)
            self.nav["settings"].grab_focus()

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
            self.open_settings("speech")
        else:
            self.app.toggle(dashboard=True)

    def navigate(self, page):
        if page == "settings":
            self.open_settings("speech")
            return
        self.close_settings()
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

    def open_settings(self, page):
        self.refresh_status()
        self.navigate_settings(page)
        self.settings_layer.show()
        self.titlebar_backdrop.show()
        self.shell.set_sensitive(False)
        self.titlebar.set_sensitive(False)
        self.settings_close.grab_focus()

    def refresh_status(self):
        provider = self.store.settings["provider"]
        ready = self.app.ready
        names = {"codex": "Codex", "claude": "Claude", "openai": "OpenAI API"}
        self.side_provider.set_text(names.get(provider, "Codex"))
        self.side_status.set_text(connection_label(provider, ready))
        if getattr(self, "accounts", None):
            self.refresh_accounts()
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
        count = len(self.store.history)
        noun = "text" if count == 1 else "texts"
        self.library_count.set_text(
            "Nothing is saved yet." if not count else f"{count} {noun} on this computer. Audio is not saved.",
        )
        if not records:
            details = "No texts match that search." if query else "Your first dictated text will appear here."
            self.history_list.pack_start(pad(label(details, "muted"), 23, 18, 23, 18), False, False, 0)
        for entry in records:
            outer = pad(box(False, 12, "transcript-row"), 10, 15, 10, 15)
            body = box(spacing=5)
            total = round(entry.get("duration", 0))
            removal = kept_until(entry.get("at"))
            meta = f"{small_time(entry.get('at'))}  ·  {total // 60}:{total % 60:02d}"
            if removal:
                meta += f"  ·  {removal}"
            body.pack_start(label(meta, "subtle"), False, False, 0)
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
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True, destroy_with_parent=True)
        dialog.set_name("revoice-dialog")
        dialog.set_default_size(480, -1)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE).get_style_context().add_class("secondary")
        body = pad(box(spacing=13), 16, 18, 14, 18)
        body.pack_start(label(title, "panel-title-large"), False, False, 0)
        body.pack_start(label(desc, "muted", True), False, False, 0)
        dialog.get_content_area().pack_start(body, True, True, 0)
        return dialog, body

    def account_card(self, provider):
        copy = ACCOUNTS[provider]
        card = box(name="account-card")
        head = pad(box(False, 12), 16, 16, 2, 16)
        titles = box(spacing=3)
        titles.pack_start(label(copy["title"], "account-title"), False, False, 0)
        status = label(copy["missing"], "account-status")
        path = label("", "subtle")
        titles.pack_start(status, False, False, 0)
        titles.pack_start(path, False, False, 0)
        head.pack_start(titles, True, True, 0)
        badge = label("Used for dictation", "account-badge")
        badge.set_valign(Gtk.Align.START)
        head.pack_end(badge, False, False, 0)
        card.pack_start(head, False, False, 0)
        detail = label(copy["absent"], "subtle", True)
        card.pack_start(pad(detail, 2, 16, 0, 16), False, False, 0)
        sign = button(copy["sign"], lambda _button, selected=provider: self.sign_in_provider(selected), "action")
        existing = button("Use existing sign-in", lambda _button, selected=provider: self.use_existing(selected), "secondary")
        use = button("Use for dictation", lambda _button, selected=provider: self.use_provider(selected), "secondary")
        choose = button("Choose profile…", lambda _button, selected=provider: self.choose_login(selected), "secondary")
        disconnect = button(
            "Remove key" if provider == "openai" else "Disconnect",
            lambda _button, selected=provider: self.disconnect_provider(selected), "minimal",
        )
        actions = box(False, 8)
        for control in (sign, existing, use, choose, disconnect):
            control.set_halign(Gtk.Align.CENTER)
            actions.pack_start(control, False, False, 0)
        card.pack_start(pad(actions, 12, 16, 16, 16), False, False, 0)
        self.accounts[provider] = SimpleNamespace(
            card=card, status=status, detail=detail, path=path, badge=badge,
            existing=existing, choose=choose, disconnect=disconnect, use=use, sign=sign,
        )
        return card

    def choice_row(self, parent, title, description, key, choices, swatches=False):
        wrap = box(False, 6)
        chips = {}
        for value, name in choices:
            chip = Gtk.Button()
            chip.set_name("choice-chip")
            content = box(False, 6)
            if swatches:
                dot = Swatch(accent_rgb(value))
                dot.set_valign(Gtk.Align.CENTER)
                content.pack_start(dot, False, False, 0)
            content.pack_start(label(name), False, False, 0)
            chip.add(content)
            chip.connect("clicked", lambda _button, selected=value, setting=key: self.choose_appearance(setting, selected))
            chips[value] = chip
            wrap.pack_start(chip, False, False, 0)
        self.appearance_chips[key] = chips
        row(parent, title, description, wrap)

    def choose_appearance(self, key, value):
        if self.store.settings.get(key) == value:
            self.mark_chips()
            return
        self.store.set(key, value)
        self.apply_appearance()

    def mark_chips(self):
        for key, chips in getattr(self, "appearance_chips", {}).items():
            current = self.store.settings[key]
            for value, chip in chips.items():
                style = chip.get_style_context()
                if value == current:
                    style.add_class("active")
                else:
                    style.remove_class("active")

    def apply_appearance(self):
        provider = getattr(self.app, "css", None)
        if provider is None:
            provider = Gtk.CssProvider()
            self.app.css = provider
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        provider.load_from_data(stylesheet(self.store.settings).encode())
        ink = icon_rgb(self.store.settings)
        for widget in (*self.walk(self), *self.walk(self.get_titlebar())):
            if isinstance(widget, Icon) and widget.follows_ink:
                widget.color = ink
                widget.queue_draw()
        if getattr(self, "home", None):
            red, green, blue = surface_rgb(self.store.settings)
            self.home.set_paper(red, green, blue)
            self.refresh_home()
        self.mark_chips()
        note = getattr(self, "appearance_note", None)
        if note is not None:
            note.set_text(self.pill_caption())
        if getattr(self.app, "pill", None) is not None:
            self.app.update_pill()

    def named_group(self, title, body):
        block = box(spacing=8)
        block.pack_start(label(title, "settings-group"), False, False, 0)
        block.pack_start(body, False, False, 0)
        return block

    def pill_caption(self):
        waveform, _size, surface = listening(self.store.settings)
        motion = {"bars": "Bars", "ribbon": "Ribbon", "ink": "Ink line", "dots": "Dots"}
        pill = {"charcoal": "a charcoal pill", "paper": "a paper pill"}
        return f"{motion[waveform]} on {pill[surface]}. Finished words paste into the field you were typing in."

    def sync_listening_pill(self):
        if hasattr(self.app, "update_pill") and getattr(self.app, "pill", None) is not None:
            self.app.update_pill()

    def walk(self, widget):
        if widget is None:
            return
        yield widget
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                yield from self.walk(child)

    def saved_login(self, provider):
        if provider == "claude":
            return self.store.settings["claude_auth"]
        if provider == "codex":
            return self.store.settings["codex_auth"]
        return ""

    def login_file(self, provider):
        if provider == "openai":
            return None
        candidates = candidate_claude_logins() if provider == "claude" else candidate_logins()
        return next((path for path in candidates if path.is_file()), None)

    def provider_ready(self, provider):
        if provider == "openai":
            return bool(getattr(self.app, "key", ""))
        if provider == "claude":
            return claude_available(self.store.settings["claude_auth"])
        try:
            codex_token(self.store.settings["codex_auth"])
        except ValueError:
            return False
        return True

    def refresh_accounts(self):
        active = self.store.settings["provider"]
        for provider, widgets in self.accounts.items():
            ready = self.provider_ready(provider)
            saved = self.saved_login(provider)
            found = self.login_file(provider)
            view = account_view(provider, ready, provider == active, saved, found)
            widgets.status.set_text(view["status"])
            widgets.detail.set_text(view["detail"])
            widgets.path.set_text(view["path"])
            widgets.path.set_visible(bool(view["path"]))
            widgets.badge.set_visible(view["active"])
            style = widgets.card.get_style_context()
            if view["active"]:
                style.add_class("active")
            else:
                style.remove_class("active")
            self.show_action(widgets.sign, True)
            self.show_action(widgets.existing, view["show_existing"])
            self.show_action(widgets.choose, view["show_choose"])
            self.show_action(widgets.disconnect, view["show_disconnect"])
            self.show_action(widgets.use, view["show_use"])

    def show_action(self, widget, visible):
        widget.set_visible(visible)
        parent = widget.get_parent()
        if isinstance(parent, Gtk.FlowBoxChild):
            parent.set_visible(visible)

    def use_provider(self, provider):
        if self.store.settings["provider"] != provider:
            self.store.set("provider", provider)
        if provider == "openai":
            self.app.load_key()
        self.refresh_status()

    def use_saved_login(self, provider, path):
        reader = claude_token if provider == "claude" else codex_token
        setting = "claude_auth" if provider == "claude" else "codex_auth"
        try:
            reader(str(path))
        except ValueError as error:
            self.feedback(str(error), error=True)
            return
        self.store.set(setting, str(path))
        self.use_provider(provider)
        self.feedback(ACCOUNTS[provider]["connected"] + ".")

    def use_existing(self, provider):
        found = self.login_file(provider)
        if found:
            self.use_saved_login(provider, found)

    def choose_login(self, provider):
        picker = Gtk.FileChooserDialog(
            title=ACCOUNTS[provider]["picker"], transient_for=self, action=Gtk.FileChooserAction.OPEN,
        )
        picker.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Use sign-in", Gtk.ResponseType.OK)
        picker.set_show_hidden(True)
        current = self.saved_login(provider)
        folder = Path(current).parent if current else Path.home()
        picker.set_current_folder(str(folder if folder.is_dir() else Path.home()))
        if picker.run() == Gtk.ResponseType.OK:
            path = picker.get_filename()
            picker.destroy()
            if path:
                self.use_saved_login(provider, path)
        else:
            picker.destroy()

    def sign_in_provider(self, provider):
        self.use_provider(provider)
        if provider == "openai":
            self.api_dialog()
            return
        message = self.app.start_claude_login() if provider == "claude" else self.app.start_login()
        folded = message.casefold()
        failed = folded.startswith("install") or folded.startswith("open a terminal") or "couldn’t" in message
        self.feedback(message, error=failed)

    def disconnect_provider(self, provider):
        if provider == "openai":
            error = self.app.update_key("")
            if error:
                self.feedback(error, error=True)
                return
        else:
            self.store.set("claude_auth" if provider == "claude" else "codex_auth", "")
        self.refresh_status()
        self.feedback(ACCOUNTS[provider]["disconnected"])

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
        dialog, body = self.dialog(
            "Clear the library?",
            f"This removes dictated text from this computer. Text is also removed on its own after {HISTORY_DAYS} days.",
        )
        body.pack_start(button("Clear library", lambda _: dialog.response(Gtk.ResponseType.OK), "action"), False, False, 0)
        dialog.show_all()
        confirmed = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        if confirmed:
            self.store.clear()
            self.app.last_text = ""
            self.refresh_history()
            self.refresh_latest()

    def on_close(self, *_args):
        self.close_settings()
        self.hide()
        return True

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.settings_layer.get_visible():
                self.close_settings()
                return True
            if self.app.state != "idle":
                self.app.cancel()
                return True
        return False
