"""Local settings, history, and opt-in connection storage."""

import json
import math
import os
import subprocess
from datetime import datetime
from pathlib import Path

APP_ID = "io.github.revoice.Revoice"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "revoice"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "revoice"
SETTINGS = CONFIG / "settings.json"
HISTORY = DATA / "history.json"
LOGIN_HOME = DATA / "codex"
DEFAULTS = {
    "shortcut": "Ctrl+Super", "hold": True, "provider": "codex", "codex_auth": "",
    "auto_paste": True, "paste_key": "auto",
    "device": "", "language": "", "save_history": True,
}


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return default


def valid_text(value):
    if not isinstance(value, str) or "\0" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def write_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = path.with_suffix(".new")
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
    pending.replace(path)


class Store:
    def __init__(self, settings_path=None, history_path=None):
        self.settings_path = SETTINGS if settings_path is None else settings_path
        self.history_path = HISTORY if history_path is None else history_path
        saved = read_json(self.settings_path, {})
        self.settings = DEFAULTS.copy()
        if isinstance(saved, dict):
            for key, default in DEFAULTS.items():
                value = saved.get(key)
                if type(value) is type(default) and (not isinstance(value, str) or valid_text(value)):
                    self.settings[key] = value
        for key, choices in (("provider", ("codex", "openai")), ("paste_key", ("auto", "regular", "terminal"))):
            if self.settings[key] not in choices:
                self.settings[key] = DEFAULTS[key]
        rows = read_json(self.history_path, [])
        self.history = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or not valid_text(row.get("text")):
                    continue
                duration = row.get("duration", 0)
                if (type(duration) not in (int, float) or duration < 0
                        or (isinstance(duration, float) and not math.isfinite(duration))):
                    duration = 0
                entry = {"text": row["text"], "duration": duration}
                if valid_text(row.get("at")):
                    entry["at"] = row["at"]
                self.history.append(entry)
                if len(self.history) == 150:
                    break

    def set(self, key, value):
        self.settings[key] = value
        write_json(self.settings_path, self.settings)

    def add(self, text, duration):
        if not self.settings["save_history"]:
            return
        self.history = [{
            "text": text, "duration": duration, "at": datetime.now().isoformat(timespec="seconds"),
        }, *self.history][:150]
        write_json(self.history_path, self.history)

    def clear(self):
        self.history = []
        write_json(self.history_path, [])


def candidate_logins():
    paths = [LOGIN_HOME / "auth.json"]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        paths.append(Path(codex_home).expanduser() / "auth.json")
    paths.append(Path.home() / ".codex/auth.json")
    return list(dict.fromkeys(paths))


def codex_token(path):
    if not path:
        raise ValueError("Connect your Codex sign-in in Settings.")
    data = read_json(Path(path), {})
    tokens = data.get("tokens", {}) if isinstance(data, dict) else {}
    token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("No ChatGPT sign-in was found in that Codex profile.")
    return token


def api_key():
    result = subprocess.run(
        ["secret-tool", "lookup", "application", APP_ID, "provider", "openai"],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip()


def save_api_key(key):
    if not key:
        args = ["secret-tool", "clear", "application", APP_ID, "provider", "openai"]
    else:
        args = ["secret-tool", "store", "--label=Revoice OpenAI API key",
                "application", APP_ID, "provider", "openai"]
    subprocess.run(args, input=key, text=True, check=True, timeout=30, capture_output=True)
