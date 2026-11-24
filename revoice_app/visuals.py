"""Draw the nonactivating dictation pill and dashboard icons."""

import math
from pathlib import Path

import gi
try:
    import cairo
except ImportError:
    raise SystemExit("Revoice needs the GTK Cairo bindings. Install python3-gi-cairo and try again.") from None

try:
    gi.require_foreign("cairo")
except ImportError:
    local_bridge = Path(__file__).resolve().parents[1] / "build/vendor/usr/lib/python3/dist-packages/gi"
    gi.__path__.append(str(local_bridge))
    try:
        gi.require_foreign("cairo")
    except ImportError:
        raise SystemExit("Revoice needs the GTK Cairo bindings. Install python3-gi-cairo and try again.") from None

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from .webview import LocalView

PEACH = (1.0, 0.69, 0.60)


def round_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    for cx, cy, angle in [(x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                          (x + r, y + h - r, 90), (x + r, y + r, 180)]:
        cr.arc(cx, cy, r, math.radians(angle), math.radians(angle + 90))
    cr.close_path()


def line(cr, points):
    cr.move_to(*points[0])
    for p in points[1:]:
        cr.line_to(*p)
    cr.stroke()


def draw_icon(cr, name, size=20.0):
    cr.save()
    cr.scale(size / 24, size / 24)
    cr.set_line_width(1.7)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    if name == "wave":
        for x, height in zip((4, 8, 12, 16, 20), (3, 10, 17, 10, 3)):
            line(cr, [(x, 12 - height / 2), (x, 12 + height / 2)])
    elif name == "mic":
        round_rect(cr, 9, 3, 6, 12, 3)
        cr.stroke()
        cr.arc(12, 12, 6, 0, math.pi)
        cr.stroke()
        line(cr, [(12, 18), (12, 21)])
        line(cr, [(9, 21), (15, 21)])
    elif name == "home":
        for x in (3, 14):
            for y in (3, 14):
                round_rect(cr, x, y, 7, 7, 1.5)
                cr.stroke()
    elif name == "history":
        cr.arc(12, 12, 8.25, -2.48, 3.60)
        cr.stroke()
        line(cr, [(12, 7), (12, 12), (15, 14)])
    elif name == "settings":
        cr.new_sub_path()
        for tooth in range(6):
            for offset, radius in ((-17, 7.5), (-12, 10), (12, 10), (17, 7.5)):
                angle = math.radians(60 * tooth + offset - 90)
                cr.line_to(12 + radius * math.cos(angle), 12 + radius * math.sin(angle))
        cr.close_path()
        cr.stroke()
        cr.arc(12, 12, 3.1, 0, math.tau)
        cr.stroke()
    elif name == "keys":
        round_rect(cr, 2, 5, 20, 14, 3)
        cr.stroke()
        for y, xs in ((9, (6, 10, 14, 18)), (13, (6, 10, 14, 18))):
            for x in xs:
                line(cr, [(x, y), (x + .3, y)])
        line(cr, [(9, 16), (15, 16)])
    elif name == "arrow":
        line(cr, [(4, 12), (20, 12), (15, 7)])
        line(cr, [(20, 12), (15, 17)])
    elif name == "copy":
        round_rect(cr, 7, 7, 12, 13, 2)
        cr.stroke()
        line(cr, [(15, 4), (4, 4), (4, 16)])
    elif name == "check":
        line(cr, [(5, 12), (10, 17), (20, 7)])
    elif name == "sidebar":
        round_rect(cr, 3, 3, 18, 18, 2)
        cr.stroke()
        line(cr, [(9, 3), (9, 21)])
    elif name == "minimize":
        line(cr, [(5, 12), (19, 12)])
    elif name == "maximize":
        cr.rectangle(6, 6, 12, 12)
        cr.stroke()
    elif name == "restore":
        line(cr, [(9, 5), (19, 5), (19, 15)])
        cr.rectangle(5, 9, 10, 10)
        cr.stroke()
    elif name == "close":
        line(cr, [(7, 7), (17, 17)])
        line(cr, [(17, 7), (7, 17)])
    elif name == "stop":
        round_rect(cr, 7, 7, 10, 10, 2)
        cr.fill()
    elif name == "alert":
        line(cr, [(12, 5), (12, 13)])
        line(cr, [(12, 17), (12, 17.4)])
    elif name == "look":
        cr.arc(12, 12, 7.2, 0, math.tau)
        cr.stroke()
        cr.arc(12, 12, 2.4, 0, math.tau)
        cr.fill()
    cr.restore()


class Swatch(Gtk.DrawingArea):
    def __init__(self, color):
        super().__init__()
        self.color = color
        self.set_size_request(12, 12)
        self.connect("draw", self.paint)

    def paint(self, _area, cr):
        cr.set_source_rgb(*self.color)
        cr.arc(6, 6, 4.5, 0, math.tau)
        cr.fill()
        return False


class Icon(Gtk.DrawingArea):
    def __init__(self, name, size=18, color=PEACH):
        super().__init__()
        self.name, self.size, self.color = name, size, color
        self.follows_ink = True
        self.set_size_request(size, size)
        self.connect("draw", self.paint)

    def paint(self, _area, cr):
        rect = self.get_allocation()
        cr.translate((rect.width - self.size) / 2, (rect.height - self.size) / 2)
        cr.set_source_rgb(*self.color)
        draw_icon(cr, self.name, self.size)
        return False


PILL_WINDOWS = {
    "compact": (108, 40),  # HUD 100×32, today's pill. Do not change these two numbers.
    "regular": (164, 52),  # HUD 156×44
    "large": (220, 68),    # HUD 212×60
}
LIVE_PILL_WINDOW = (640, 196)  # HUD 632×188


def pill_window(pill_size, live):
    if live:
        return LIVE_PILL_WINDOW
    return PILL_WINDOWS.get(pill_size, PILL_WINDOWS["compact"])


class Pill(Gtk.Window):
    BOTTOM_MARGIN = 14

    def __init__(self, toggle, cancel):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_name("window-pill")
        self.set_title("Revoice dictation indicator")
        self.set_resizable(False)
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.layer = None
        try:
            gi.require_version("GtkLayerShell", "0.1")
            from gi.repository import GtkLayerShell
            if GtkLayerShell.is_supported():
                self.layer = GtkLayerShell
                self.layer.init_for_window(self)
                self.layer.set_namespace(self, "revoice")
                self.layer.set_layer(self, self.layer.Layer.OVERLAY)
                self.layer.set_keyboard_mode(self, self.layer.KeyboardMode.NONE)
                self.layer.set_anchor(self, self.layer.Edge.BOTTOM, True)
                self.layer.set_margin(self, self.layer.Edge.BOTTOM, self.BOTTOM_MARGIN)
        except (ValueError, AttributeError):
            pass
        self.state = "idle"
        self.energy = self.smoothed = 0.0
        self.hands_free = False
        self.look = {}
        self._size = pill_window("compact", False)
        self.toggle, self.cancel = toggle, cancel
        self.area = LocalView("pill", self.on_action, transparent=True)
        self.area.set_can_focus(False)
        self.area.set_size_request(*self._size)
        self.set_size_request(*self._size)
        self.set_default_size(*self._size)
        self.area.connect("size-allocate", lambda *_: self.set_shape())
        self.add(self.area)
        self.connect("realize", self.realized)
        self.connect("delete-event", lambda *_: True)
        GLib.timeout_add(45, self.animate)

    def realized(self, *_args):
        self._deny_focus()
        GLib.idle_add(self.position)

    def _deny_focus(self):
        self.set_accept_focus(False)
        self.area.set_can_focus(False)
        native = self.get_window()
        if native is not None:
            native.set_accept_focus(False)

    def _use_size(self, size):
        self._size = size
        self.area.set_size_request(*size)
        self.set_size_request(*size)
        self.set_default_size(*size)
        self.resize(*size)
        self._deny_focus()

    def position(self):
        display = self.get_display()
        seat = display.get_default_seat()
        if not seat:
            return False
        pointer = seat.get_pointer()
        if not pointer:
            return False
        _, x, y = pointer.get_position()
        monitor = display.get_monitor_at_point(x, y)
        if self.layer and monitor:
            self.layer.set_monitor(self, monitor)
        elif monitor:
            geometry = monitor.get_workarea()
            width, height = self._size
            self.move(geometry.x + (geometry.width - width) // 2,
                      geometry.y + geometry.height - height - self.BOTTOM_MARGIN)
        self.set_shape()
        return False

    def set_shape(self):
        native = self.get_window()
        if not native:
            return
        region = cairo.Region()
        if self.state == "recording":
            width, height = self._size
            if self.look.get("live"):
                # Rounded rectangle, inset 4px. Not a stadium: a 196px window must not grab the desktop.
                hud_w, hud_h = width - 8, height - 8
                radius = 22
                for row in range(hud_h):
                    if row < radius:
                        dy = radius - row - .5
                    elif row >= hud_h - radius:
                        dy = row + .5 - (hud_h - radius)
                    else:
                        dy = None
                    inset = 0 if dy is None else round(radius - math.sqrt(radius ** 2 - dy ** 2))
                    region.union(cairo.RectangleInt(4 + inset, 4 + row, hud_w - 2 * inset, 1))
            elif (width, height) == PILL_WINDOWS["compact"]:
                # Reflow reserves four transparent pixels around the 100 × 32 CSS capsule.
                radius = 16
                for row in range(32):
                    inset = round(radius - math.sqrt(radius ** 2 - (radius - row - .5) ** 2))
                    region.union(cairo.RectangleInt(4 + inset, 4 + row, 100 - 2 * inset, 1))
            else:
                hud_w, hud_h = width - 8, height - 8
                radius = hud_h / 2
                for row in range(hud_h):
                    inset = round(radius - math.sqrt(radius ** 2 - (radius - row - .5) ** 2))
                    region.union(cairo.RectangleInt(4 + inset, 4 + row, hud_w - 2 * inset, 1))
        native.input_shape_combine_region(region, 0, 0)

    def update(self, state, hands_free=False, **look):
        changed = state != self.state
        self.state = state
        self.hands_free = hands_free
        for key in ("waveform", "live", "text", "paper", "accent", "ink", "sheet", "pill_size"):
            if key in look:
                self.look[key] = look[key]
        size = pill_window(self.look.get("pill_size", "compact"), bool(self.look.get("live")))
        resized = size != self._size
        if state == "idle":
            self.render()
            self.hide()
            if resized:
                self._use_size(size)
                self.position()
                self.set_shape()
            return
        if resized:
            self._use_size(size)
        if changed:
            self.energy = self.smoothed = 0.0
            self.show_all()
            self._deny_focus()
        if resized or changed:
            self.position()
            self.set_shape()
        self.render()

    def on_action(self, action, _value):
        if self.state == "recording":
            if action == "cancel":
                self.cancel()
            elif action == "stop":
                self.toggle()

    def render(self):
        self.area.render({
            "listening": self.state == "recording",
            "active": self.state != "idle",
            "handsFree": self.hands_free,
            "level": self.smoothed,
            "reducedMotion": not self.get_settings().props.gtk_enable_animations,
            "waveform": self.look.get("waveform", "ink"),
            "live": self.look.get("live", False),
            "text": self.look.get("text", ""),
            "paper": self.look.get("paper", False),
            "accent": self.look.get("accent", "#79501b"),
            "ink": self.look.get("ink", "#29231e"),
            "sheet": self.look.get("sheet", "#fffdf2"),
            "pillSize": self.look.get("pill_size", "compact"),
        })

    def animate(self):
        if self.get_visible() and self.state == "recording":
            self.smoothed = self.smoothed * .62 + self.energy * .38
            self.render()
        return True
