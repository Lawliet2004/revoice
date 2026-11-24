"""Local settings, history, and opt-in connection storage."""

import json
import math
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

APP_ID = "io.github.revoice.Revoice"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "revoice"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "revoice"
SETTINGS = CONFIG / "settings.json"
HISTORY = DATA / "history.json"
LOGIN_HOME = DATA / "codex"
CLAUDE_LOGIN_HOME = DATA / "claude"
HISTORY_DAYS = 3
PROVIDERS = ("codex", "claude", "openai")
PROVIDER_NAMES = {"codex": "Codex", "claude": "Claude", "openai": "OpenAI"}
CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
DEFAULTS = {
    "shortcut": "Ctrl+Super", "hold": True, "provider": "codex", "codex_auth": "", "claude_auth": "",
    "auto_paste": True, "paste_key": "auto",
    "device": "", "language": "", "save_history": True,
    "tone": "warm", "accent": "copper", "text_size": "regular", "corners": "soft",
    "waveform": "ink", "pill_size": "compact", "live_pill": False, "pill_surface": "charcoal",
    "density": "regular", "reading_face": "book",
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
        for key, choices in (
            ("provider", PROVIDERS), ("paste_key", ("auto", "regular", "terminal")),
            ("tone", ("warm", "neutral", "cool")), ("accent", ("copper", "ink", "sea", "forest", "plum")),
            ("text_size", ("compact", "regular", "large")), ("corners", ("sharp", "soft", "round")),
            ("waveform", ("bars", "ribbon", "ink", "dots")),
            ("pill_size", ("compact", "regular", "large")),
            ("pill_surface", ("charcoal", "paper")),
            ("density", ("compact", "regular", "roomy")),
            ("reading_face", ("book", "sans", "mono")),
        ):
            if self.settings[key] not in choices:
                self.settings[key] = DEFAULTS[key]
        rows = read_json(self.history_path, [])
        loaded = []
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
                loaded.append(entry)
                if len(loaded) == 150:
                    break
        self.history = retain_history(loaded)
        if self.history != rows:
            try:
                write_json(self.history_path, self.history)
            except OSError:
                pass

    def set(self, key, value):
        self.settings[key] = value
        write_json(self.settings_path, self.settings)

    def add(self, text, duration):
        if not self.settings["save_history"]:
            return
        self.history = retain_history([{
            "text": text, "duration": duration, "at": datetime.now().isoformat(timespec="seconds"),
        }, *self.history])
        write_json(self.history_path, self.history)

    def prune(self, now=None):
        retained = retain_history(self.history, now)
        if retained == self.history:
            return False
        self.history = retained
        write_json(self.history_path, self.history)
        return True

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


def connection_label(provider, ready):
    name = PROVIDER_NAMES.get(provider, "Codex")
    return f"Connected via {name}" if ready else f"Sign in to {name}"


def parse_history_time(value):
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when


def retain_history(rows, now=None):
    """Keep transcript text for three days. Microphone audio is never stored."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=HISTORY_DAYS)
    stamp = now.isoformat(timespec="seconds")
    kept = []
    for entry in rows:
        when = parse_history_time(entry.get("at"))
        if entry.get("at") in (None, ""):
            kept.append({**entry, "at": stamp})
        elif when is not None and when > cutoff:
            kept.append(entry)
        if len(kept) == 150:
            break
    return kept


def kept_until(value, now=None):
    when = parse_history_time(value)
    if when is None:
        return ""
    until = when + timedelta(days=HISTORY_DAYS)
    today = (now or datetime.now()).date()
    if until.date() == today:
        return "Removed today"
    if until.date() == today + timedelta(days=1):
        return "Removed tomorrow"
    return "Removed " + until.strftime("%b %d").replace(" 0", " ")


def candidate_claude_logins():
    paths = []
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        paths.append(Path(override).expanduser() / ".credentials.json")
    paths.append(Path.home() / ".claude" / ".credentials.json")
    return list(dict.fromkeys(paths))


def claude_record(path):
    if not path:
        return None
    data = read_json(Path(path), {})
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    return oauth if isinstance(oauth, dict) else None


def usable_claude(record):
    if not isinstance(record, dict):
        return False
    access = record.get("accessToken")
    refresh = record.get("refreshToken")
    return any(isinstance(value, str) and value for value in (access, refresh))


def claude_available(path):
    """True when a Claude.ai sign-in is present. This does not contact the network."""
    if usable_claude(claude_record(path)):
        return True
    if path:
        return False
    env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if valid_text(env) and env:
        return True
    return any(usable_claude(claude_record(item)) for item in candidate_claude_logins() if item.is_file())


def claude_token(path, opener=None):
    """Return a Claude.ai access token, refreshing it when the saved login is due."""
    selected = Path(path) if path else next((item for item in candidate_claude_logins() if item.is_file()), None)
    if selected is None:
        env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
        if valid_text(env) and env:
            return env
        raise ValueError("Connect your Claude sign-in in Settings.")
    data = read_json(selected, {})
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        raise ValueError("No Claude.ai sign-in was found in that Claude Code profile.")
    token = oauth.get("accessToken")
    expires = oauth.get("expiresAt")
    if isinstance(expires, str) and expires.isdigit():
        expires = int(expires)
    due = isinstance(expires, (int, float)) and math.isfinite(expires) and expires <= (time_ms() + 60_000)
    if not due and isinstance(token, str) and token and valid_text(token):
        return token
    refresh = oauth.get("refreshToken")
    if not isinstance(refresh, str) or not refresh:
        raise ValueError("Claude sign-in expired. Open Claude Code and sign in again.")
    payload = refresh_claude(refresh, opener)
    access = payload.get("access_token")
    if not isinstance(access, str) or not access or not valid_text(access):
        raise ValueError("Claude couldn’t refresh the sign-in. Open Claude Code and sign in again.")
    updated = dict(oauth)
    updated["accessToken"] = access
    rotated = payload.get("refresh_token")
    if isinstance(rotated, str) and rotated:
        updated["refreshToken"] = rotated
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)) and math.isfinite(expires_in) and expires_in > 0:
        updated["expiresAt"] = int(time_ms() + expires_in * 1000)
    scopes = payload.get("scope")
    if isinstance(scopes, str) and scopes:
        updated["scopes"] = scopes.split()
    if not isinstance(data, dict):
        data = {}
    data["claudeAiOauth"] = updated
    try:
        write_json(selected, data)
    except OSError:
        if isinstance(rotated, str) and rotated and rotated != refresh:
            raise ValueError("Claude refreshed the sign-in, but Revoice couldn’t save it. Sign in again.") from None
    return access


def refresh_claude(refresh, opener=None):
    body = json.dumps({
        "grant_type": "refresh_token", "refresh_token": refresh, "client_id": CLAUDE_CLIENT_ID,
    }).encode()
    request = urllib.request.Request(CLAUDE_TOKEN_URL, data=body, headers={
        "Content-Type": "application/json", "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-cli/2.1.72 (external, cli)",
    })
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        error.close()
        raise ValueError("Claude couldn’t refresh the sign-in. Open Claude Code and sign in again.") from None
    except (OSError, ValueError, TimeoutError):
        raise ValueError("Claude couldn’t refresh the sign-in. Check your connection and try again.") from None
    if not isinstance(payload, dict):
        raise ValueError("Claude couldn’t refresh the sign-in. Open Claude Code and sign in again.")
    return payload


def time_ms():
    return int(datetime.now().timestamp() * 1000)


def save_api_key(key):
    if not key:
        args = ["secret-tool", "clear", "application", APP_ID, "provider", "openai"]
    else:
        args = ["secret-tool", "store", "--label=Revoice OpenAI API key",
                "application", APP_ID, "provider", "openai"]
    subprocess.run(args, input=key, text=True, check=True, timeout=30, capture_output=True)
