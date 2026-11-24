"""Desk appearance: paper tone, ink accent, type size, corners, density, and reading face.

The GTK shell and the home page both read these choices. Audio and sign-in
state are not part of appearance.
"""

import re
from pathlib import Path

THEME = Path(__file__).with_name("theme.css")

TONES = ("warm", "neutral", "cool")
ACCENTS = ("copper", "ink", "sea", "forest", "plum")
TEXT_SIZES = ("compact", "regular", "large")
CORNERS = ("sharp", "soft", "round")
WAVEFORMS = ("bars", "ribbon", "ink", "dots")
PILL_SIZES = ("compact", "regular", "large")
PILL_SURFACES = ("charcoal", "paper")
DENSITIES = ("compact", "regular", "roomy")
READING_FACES = ("book", "sans", "mono")

DENSITY_SCALE = {"compact": "0.88", "regular": "1", "roomy": "1.14"}
FONT_SERIF = {
    "book": '"Iowan Old Style", "Sitka Text", Charter, "Bitstream Charter", Cambria, Georgia, ui-serif, serif',
    "sans": '"Segoe UI Variable Text", "Segoe UI", ui-sans-serif, system-ui, sans-serif',
    "mono": '"Cascadia Mono", "Cascadia Code", "Source Code Pro", ui-monospace, monospace',
}
PREVIEW_FAMILY = {
    "book": 'Charter, "Bitstream Charter", "Noto Serif", serif',
    "sans": "sans-serif",
    "mono": "monospace",
}
PREVIEW_PX = {"compact": 24, "regular": 28, "large": 34}

PAPER = {
    "warm": {
        "base": "#f5e7ba", "base2": "#ecd694", "surface": "#fffae9", "surface3": "#f7e8b9",
        "line": "#e6d29f", "line_soft": "#efe0b8", "well": "#faf0d3",
        "ink": "#29231e", "ink2": "#4a4038", "muted": "#675b51",
        "titlebar": "#f2d98d", "titlebar_top": "#f7e4a8", "titlebar_bottom": "#f1d78e",
        "selection": "#ead089", "scrollbar": "#cdc0ad", "ink_rgb": "41, 35, 30",
        "web_surface": "#fffae9", "web_surface_3": "#f6e8b8", "web_line": "#e6d29f",
        "web_line_soft": "#f0e2bc", "web_muted": "#6d583c", "web_faint": "#756348",
        "web_glow": "#f8e9b7", "web_sheet": "#fffdf2",
        "web_head_a": "#fbf0ca", "web_head_b": "#f7e5af", "web_head_c": "#fbefcc",
        "web_foot": "#fffae8",
    },
    "neutral": {
        "base": "#f4efe6", "base2": "#ebe4d8", "surface": "#fbf8f2", "surface3": "#efe8dc",
        "line": "#e2d8c8", "line_soft": "#ebe3d6", "well": "#f7f2e9",
        "ink": "#29231e", "ink2": "#4a4038", "muted": "#675b51",
        "titlebar": "#ebe4d8", "titlebar_top": "#f7f2e9", "titlebar_bottom": "#e7dfd2",
        "selection": "#e4d9c8", "scrollbar": "#cdc0ad", "ink_rgb": "41, 35, 30",
        "web_surface": "#fbf8f2", "web_surface_3": "#efe8dc", "web_line": "#e2d8c8",
        "web_line_soft": "#ebe3d6", "web_muted": "#675b51", "web_faint": "#6f6358",
        "web_glow": "#efe6d6", "web_sheet": "#fffcf7",
        "web_head_a": "#f7f2e9", "web_head_b": "#efe8dc", "web_head_c": "#f7f2e9",
        "web_foot": "#fbf8f2",
    },
    "cool": {
        "base": "#e7eef2", "base2": "#d5e2ea", "surface": "#f7fafc", "surface3": "#e4eef3",
        "line": "#c9d7e0", "line_soft": "#dce7ee", "well": "#eef4f7",
        "ink": "#1c2830", "ink2": "#3d4d58", "muted": "#5c6b76",
        "titlebar": "#d5e2ea", "titlebar_top": "#e7eef2", "titlebar_bottom": "#d0dee6",
        "selection": "#d5e4ec", "scrollbar": "#b7c8d2", "ink_rgb": "28, 40, 48",
        "web_surface": "#f4f8fb", "web_surface_3": "#e4eef3", "web_line": "#c9d7e0",
        "web_line_soft": "#dce7ee", "web_muted": "#5c6b76", "web_faint": "#6a7a84",
        "web_glow": "#e4eef4", "web_sheet": "#fbfcfe",
        "web_head_a": "#eef5f8", "web_head_b": "#e3eef3", "web_head_c": "#f3f8fa",
        "web_foot": "#f7fafc",
    },
}

ACCENT_COLORS = {
    "copper": {"accent": "#79501b", "record": "#684722", "hover": "#8b581e"},
    "ink": {"accent": "#29231e", "record": "#29231e", "hover": "#3d342c"},
    "sea": {"accent": "#1f5275", "record": "#1a4664", "hover": "#1f5275"},
    "forest": {"accent": "#2f6b45", "record": "#245536", "hover": "#2f6b45"},
    "plum": {"accent": "#6b3a5d", "record": "#5a304e", "hover": "#6b3a5d"},
}

FONT_PX = {"compact": 13, "regular": 14, "large": 16}
RADII = {
    "sharp": {"window": 6, "card": 10, "control": 4, "dialog": 12, "panel": 8},
    "soft": {"window": 11, "card": 18, "control": 8, "dialog": 20, "panel": 14},
    "round": {"window": 16, "card": 24, "control": 12, "dialog": 26, "panel": 18},
}

ACCOUNTS = {
    "codex": {
        "title": "Codex",
        "sign": "Sign in with Codex",
        "connected": "Connected via Codex",
        "missing": "Sign in to Codex",
        "ready": "Speech uses the ChatGPT sign-in saved by Codex. Audio is sent to OpenAI and is not saved here.",
        "found": "A Codex sign-in is already on this computer. Use it, or sign in with Codex.",
        "absent": "Sign in with Codex, or choose an auth.json from another profile.",
        "picker": "Choose Codex auth.json",
        "disconnected": "Codex disconnected from Revoice.",
    },
    "claude": {
        "title": "Claude",
        "sign": "Sign in with Claude",
        "connected": "Connected via Claude",
        "missing": "Sign in to Claude",
        "ready": "Speech uses the Claude.ai sign-in saved by Claude Code. Audio is sent to Anthropic and is not saved here.",
        "found": "Claude Code is already signed in on this computer. Use that sign-in, or sign in with Claude.",
        "absent": "Sign in with Claude Code. Revoice uses that Claude.ai sign-in, not an API key.",
        "picker": "Choose Claude credentials",
        "disconnected": "Claude disconnected from Revoice.",
    },
    "openai": {
        "title": "OpenAI API",
        "sign": "Add API key",
        "connected": "Connected via OpenAI",
        "missing": "Sign in to OpenAI",
        "ready": "Speech uses your API key and separate billing. The key stays in your desktop keyring, and audio is not saved here.",
        "found": "",
        "absent": "Add an API key. Revoice stores it in your desktop keyring.",
        "picker": "",
        "disconnected": "OpenAI key removed from Revoice.",
    },
}


def choice(settings, key, allowed, fallback):
    value = settings.get(key) if isinstance(settings, dict) else None
    return value if value in allowed else fallback


def resolved(settings):
    tone = choice(settings, "tone", TONES, "warm")
    accent = choice(settings, "accent", ACCENTS, "copper")
    size = choice(settings, "text_size", TEXT_SIZES, "regular")
    corners = choice(settings, "corners", CORNERS, "soft")
    return tone, accent, size, corners


def reading(settings):
    """Density and the face used for dictated words."""
    density = choice(settings, "density", DENSITIES, "regular")
    face = choice(settings, "reading_face", READING_FACES, "book")
    return density, face


def listening(settings):
    """Waveform, pill size, and pill surface."""
    waveform = choice(settings, "waveform", WAVEFORMS, "ink")
    size = choice(settings, "pill_size", PILL_SIZES, "compact")
    surface = choice(settings, "pill_surface", PILL_SURFACES, "charcoal")
    return waveform, size, surface


def icon_rgb(settings):
    tone, *_rest = resolved(settings)
    hex_color = PAPER[tone]["ink2"]
    return tuple(int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5))


def surface_rgb(settings):
    tone, *_rest = resolved(settings)
    hex_color = PAPER[tone]["web_surface"]
    return tuple(int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5))


def accent_rgb(name):
    hex_color = ACCENT_COLORS[name if name in ACCENT_COLORS else "copper"]["accent"]
    return tuple(int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5))


def stylesheet(settings):
    """Theme CSS with this desk's colors, type size, and corners filled in."""
    tone_name, accent_name, size_name, corner_name = resolved(settings)
    face = reading(settings)[1]
    tone = PAPER[tone_name]
    accent = ACCENT_COLORS[accent_name]["accent"]
    radii = RADII[corner_name]
    text = THEME.read_text(encoding="utf-8")
    colors = {
        "base": tone["base"], "base2": tone["base2"], "surface": tone["surface"],
        "surface3": tone["surface3"], "line": tone["line"], "line_soft": tone["line_soft"],
        "well": tone["well"], "ink": tone["ink"], "ink2": tone["ink2"], "muted": tone["muted"],
        "accent": accent, "danger": "#b42d24",
    }
    for name, value in colors.items():
        text = re.sub(rf"(@define-color {name} )#[0-9A-Fa-f]+;", rf"\g<1>{value};", text, count=1)
    text = (text.replace("#f2d98d", tone["titlebar"]).replace("#f7e4a8", tone["titlebar_top"])
            .replace("#f1d78e", tone["titlebar_bottom"]).replace("#ead089", tone["selection"])
            .replace("#cdc0ad", tone["scrollbar"]).replace("41, 35, 30", tone["ink_rgb"]))
    text = text.replace("font-size: 14px", f"font-size: {FONT_PX[size_name]}px", 1)
    window = radii["window"]
    control = radii["control"]
    dialog = radii["dialog"]
    text += f"""
window.revoice decoration {{ border-radius: {window}px; }}
#revoice-shell {{ border-radius: 0 0 {window}px {window}px; }}
#revoice-titlebar, #settings-titlebar-backdrop {{ border-radius: {window}px {window}px 0 0; }}
#canvas {{ border-radius: {radii["card"]}px; }}
#settings-dialog {{ border-radius: {dialog}px; }}
#settings-rail {{ border-radius: {dialog - 1}px 0 0 {dialog - 1}px; }}
#settings-panel, #panel, #account-card {{ border-radius: {radii["panel"]}px; }}
button.action, button.secondary, button.minimal, combobox button, entry {{ border-radius: {control}px; }}
#choice-chip {{ border-radius: 999px; }}
#appearance-preview {{ font-family: {PREVIEW_FAMILY[face]}; font-size: {PREVIEW_PX[size_name]}px; }}
"""
    return text


def web_appearance(settings):
    tone_name, accent_name, size_name, corner_name = resolved(settings)
    density, face = reading(settings)
    tone = PAPER[tone_name]
    accent = ACCENT_COLORS[accent_name]
    radii = RADII[corner_name]
    return {
        "tone": tone_name,
        "accent": accent_name,
        "corners": corner_name,
        "fontSize": f"{FONT_PX[size_name]}px",
        "radiusCard": f"{radii['panel']}px",
        "radiusControl": f"{radii['control']}px",
        "vars": {
            "--color-surface": tone["web_surface"],
            "--color-surface-3": tone["web_surface_3"],
            "--color-line": tone["web_line"],
            "--color-line-soft": tone["web_line_soft"],
            "--color-muted": tone["web_muted"],
            "--color-faint": tone["web_faint"],
            "--color-ink": tone["ink"],
            "--color-glow": tone["web_glow"],
            "--color-sheet": tone["web_sheet"],
            "--color-head-a": tone["web_head_a"],
            "--color-head-b": tone["web_head_b"],
            "--color-head-c": tone["web_head_c"],
            "--color-foot": tone["web_foot"],
            "--color-accent": accent["accent"],
            "--color-record": accent["record"],
            "--color-record-hover": accent["hover"],
            "--density": DENSITY_SCALE[density],
            "--font-serif": FONT_SERIF[face],
        },
    }


def short_path(path):
    text = str(path or "")
    if not text:
        return ""
    home = str(Path.home())
    if text == home or text.startswith(home + "/"):
        text = "~" + text[len(home):]
    return text


def account_view(provider, ready, active, saved, found):
    """Text and buttons for one sign-in card. `found` is an existing login file, or None."""
    copy = ACCOUNTS[provider]
    saved_text = str(saved or "")
    found_text = str(found) if found else ""
    if ready:
        detail = copy["ready"]
    elif found_text and found_text != saved_text:
        detail = copy["found"]
    else:
        detail = copy["absent"]
    return {
        "title": copy["title"],
        "sign": copy["sign"],
        "status": copy["connected"] if ready else copy["missing"],
        "detail": detail,
        "path": short_path(saved_text),
        "picker": copy["picker"],
        "disconnected": copy["disconnected"],
        "active": active,
        "show_existing": bool(found_text) and found_text != saved_text,
        "show_disconnect": bool(saved_text) if provider != "openai" else bool(ready),
        "show_use": not active,
        "show_choose": provider != "openai",
    }
