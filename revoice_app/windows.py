"""Windows dashboard. Speech providers and transcript storage are shared with Linux."""

import os
import queue
import shutil
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import Store, claude_available, claude_token, codex_token, connection_label
from .speech import SpeechError
from .windows_audio import WindowsRecording
from .windows_desktop import WindowsDesktop, single_instance

PROVIDERS = {"OpenAI API": "openai", "Codex": "codex", "Claude": "claude"}


class Dashboard:
    def __init__(self, root, store, desktop_factory=WindowsDesktop, recording_factory=WindowsRecording):
        self.root = root
        self.store = store
        self.recording_factory = recording_factory
        self.events = queue.SimpleQueue()
        self.recording = None
        self.state = "idle"
        self.generation = 0
        self.in_dialog = False
        self.provider = tk.StringVar(value=next(label for label, key in PROVIDERS.items() if key == store.settings["provider"]))
        self.api_key = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        self.profile = tk.StringVar(value=store.settings["codex_auth"])
        self.claude_profile = tk.StringVar(value=store.settings["claude_auth"])
        self.keep_history = tk.BooleanVar(value=store.settings["save_history"])
        self.status = tk.StringVar(value="Ready to record.")
        self.shortcut = tk.StringVar(value="Registering the global shortcut…")
        self.build()
        self.desktop = desktop_factory(lambda *event: self.events.put(event))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_timer = self.root.after(35, self.poll)

    def build(self):
        self.root.title("Revoice")
        self.root.geometry("720x540")
        self.root.minsize(540, 450)
        main = ttk.Frame(self.root, padding=22)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Revoice", font=("Segoe UI", 24, "bold")).pack(anchor="w")
        ttk.Label(main, textvariable=self.shortcut).pack(anchor="w", pady=(2, 16))

        connection = ttk.Frame(main)
        connection.pack(fill="x", pady=(0, 12))
        provider = ttk.Combobox(connection, textvariable=self.provider, values=tuple(PROVIDERS), state="readonly", width=17)
        provider.pack(side="left", padx=(0, 8))
        provider.bind("<<ComboboxSelected>>", self.change_provider)
        self.api_entry = ttk.Entry(connection, textvariable=self.api_key, show="*", width=34)
        self.profile_button = ttk.Button(connection, text="Choose Codex profile…", command=self.choose_profile)
        self.connection_label = ttk.Label(connection)
        self.refresh_provider()

        sign = ttk.LabelFrame(main, text="Sign in", padding=10)
        sign.pack(fill="x", pady=(0, 12))
        codex_row = ttk.Frame(sign)
        codex_row.pack(fill="x", pady=3)
        ttk.Button(codex_row, text="Sign in with Codex", command=self.sign_codex).pack(side="left")
        ttk.Button(codex_row, text="Choose Codex profile…", command=lambda: self.choose_named("codex")).pack(side="left", padx=8)
        self.codex_state = ttk.Label(codex_row, text="Sign in to Codex")
        self.codex_state.pack(side="left", padx=(8, 0))
        claude_row = ttk.Frame(sign)
        claude_row.pack(fill="x", pady=3)
        ttk.Button(claude_row, text="Sign in with Claude", command=self.sign_claude).pack(side="left")
        ttk.Button(claude_row, text="Choose Claude profile…", command=lambda: self.choose_named("claude")).pack(side="left", padx=8)
        self.claude_state = ttk.Label(claude_row, text="Sign in to Claude")
        self.claude_state.pack(side="left", padx=(8, 0))
        self.refresh_provider()

        controls = ttk.Frame(main)
        controls.pack(fill="x")
        self.record_button = ttk.Button(controls, text="Record", command=self.toggle)
        self.record_button.pack(side="left")
        self.cancel_button = ttk.Button(controls, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 12))
        ttk.Label(controls, textvariable=self.status, wraplength=395).pack(side="left", fill="x")

        options = ttk.Frame(main)
        options.pack(fill="x", pady=(10, 10))
        ttk.Checkbutton(options, text="Keep a text library for 3 days", variable=self.keep_history,
                        command=lambda: self.save_setting("save_history", self.keep_history.get())).pack(side="left")
        ttk.Label(options, text="Words only. Audio is not saved.").pack(side="left", padx=(12, 0))


        editor = ttk.Frame(main)
        editor.pack(fill="both", expand=True)
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(0, weight=1)
        self.transcript = tk.Text(editor, wrap="word", undo=True, font=("Segoe UI", 12), padx=10, pady=10)
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(editor, command=self.transcript.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="Copy transcript", command=self.copy).pack(side="left")
        self.history = ttk.Combobox(footer, state="readonly", width=27)
        self.history.pack(side="left", padx=(8, 6), fill="x", expand=True)
        self.history.bind("<<ComboboxSelected>>", self.load_history)
        ttk.Button(footer, text="Clear history", command=self.clear_history).pack(side="right")
        self.refresh_history()
        if self.store.history:
            self.display(self.store.history[0]["text"])

    def refresh_provider(self):
        self.api_entry.pack_forget()
        self.profile_button.pack_forget()
        self.connection_label.pack_forget()
        provider = PROVIDERS[self.provider.get()]
        if provider == "openai":
            self.api_entry.pack(side="left", fill="x", expand=True)
            ready = bool(self.api_key.get().strip())
        else:
            self.profile_button.configure(text="Choose Claude profile…" if provider == "claude" else "Choose Codex profile…")
            self.profile_button.pack(side="left")
            path = self.claude_profile.get() if provider == "claude" else self.profile.get()
            ready = claude_available(path) if provider == "claude" else bool(path)
        self.connection_label.configure(text=connection_label(provider, ready))
        self.connection_label.pack(side="left", padx=(8, 0))
        if getattr(self, "codex_state", None):
            self.codex_state.configure(text=connection_label("codex", bool(self.profile.get())))
            self.claude_state.configure(text=connection_label("claude", claude_available(self.claude_profile.get())))

    def sign_codex(self):
        self.provider.set("Codex")
        self.change_provider(None)
        self.status.set(self.open_cli("codex", ["login"], "Codex"))

    def sign_claude(self):
        self.provider.set("Claude")
        self.change_provider(None)
        self.status.set(self.open_cli("claude", [], "Claude Code"))

    def choose_named(self, provider):
        self.provider.set("Claude" if provider == "claude" else "Codex")
        self.change_provider(None)
        self.choose_profile()

    def open_cli(self, program, args, title):
        binary = shutil.which(program)
        if not binary:
            return f"Install the {title} CLI, then choose the sign-in file."
        try:
            subprocess.Popen(["cmd", "/c", "start", "", binary, *args])
        except OSError:
            return f"Revoice couldn’t open {title}. Choose the sign-in file instead."
        return f"Finish signing in with {title}, then choose that profile."

    def change_provider(self, _event):
        self.save_setting("provider", PROVIDERS[self.provider.get()])
        self.refresh_provider()

    def choose_profile(self):
        provider = PROVIDERS[self.provider.get()]
        claude = provider == "claude"
        if claude:
            home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
            title = "Choose Claude credentials"
            reader = claude_token
        else:
            home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            title = "Choose Codex auth.json"
            reader = codex_token
        self.in_dialog = True
        try:
            path = filedialog.askopenfilename(
                parent=self.root, title=title,
                initialdir=home if home.is_dir() else Path.home(),
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
        finally:
            self.in_dialog = False
        if path:
            try:
                reader(path)
            except ValueError as error:
                self.status.set(str(error))
                return
            if claude:
                self.claude_profile.set(path)
                self.save_setting("claude_auth", path)
            else:
                self.profile.set(path)
                self.save_setting("codex_auth", path)
            self.refresh_provider()

    def save_setting(self, key, value):
        try:
            self.store.set(key, value)
        except OSError:
            self.status.set("Couldn’t save the setting to disk.")

    def credential(self, provider):
        if provider == "codex":
            return codex_token(self.profile.get())
        if provider == "claude":
            return claude_token(self.claude_profile.get())
        key = self.api_key.get().strip()
        if not key:
            raise ValueError("Enter an OpenAI API key before recording.")
        return key

    def toggle(self):
        if self.in_dialog:
            return
        if self.state == "idle":
            provider = PROVIDERS[self.provider.get()]
            try:
                key = self.credential(provider)
                self.generation += 1
                generation = self.generation
                recording = self.recording_factory(
                    {**self.store.settings, "provider": provider}, key,
                    lambda kind, *values: self.events.put(("speech", generation, kind, values)),
                )
                recording.start()
            except (SpeechError, ValueError, ImportError) as error:
                self.status.set(str(error))
                return
            self.recording = recording
            self.set_state("recording", "Listening…")
        elif self.state == "recording":
            self.recording.stop()
            self.set_state("processing", "Finishing dictation…")

    def set_state(self, state, message):
        self.state = state
        self.status.set(message)
        self.record_button.configure(text="Stop recording" if state == "recording" else "Record",
                                     state="disabled" if state == "processing" else "normal")
        self.cancel_button.configure(state="disabled" if state == "idle" else "normal")

    def cancel(self):
        self.generation += 1
        if self.recording:
            self.recording.cancel()
            self.recording = None
        self.set_state("idle", "Dictation cancelled.")

    def poll(self):
        while not self.events.empty():
            kind, *values = self.events.get()
            if kind == "hotkey":
                self.toggle()
            elif kind == "shortcut":
                self.shortcut.set(values[0])
            elif kind == "speech":
                self.finish(*values)
        self.poll_timer = self.root.after(35, self.poll)

    def finish(self, generation, kind, values):
        if generation != self.generation or self.recording is None:
            return
        if kind == "partial":
            if self.state == "recording" and values and isinstance(values[0], str):
                self.display(values[0])
            return
        if kind not in ("error", "result"):
            return
        message = values[0] if kind == "error" else "Transcript ready to copy."
        if kind == "error":
            self.recording.cancel()
        self.recording = None
        transcript = values[1:] if kind == "error" else values
        if transcript:
            text, duration = transcript
            self.display(text)
            try:
                self.store.add(text, duration)
            except OSError:
                message += " Couldn’t save to the library."
            else:
                if self.store.settings["save_history"]:
                    message += " Saved in your library for 3 days."
            self.refresh_history()
            if kind == "error":
                message += " Partial text is ready to copy."
        self.set_state("idle", message)

    def display(self, text):
        self.transcript.delete("1.0", "end")
        self.transcript.insert("1.0", text)
        self.transcript.edit_reset()

    def copy(self):
        text = self.transcript.get("1.0", "end-1c")
        if text:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
            except tk.TclError:
                self.status.set("Couldn’t copy. Try again or select the text to copy it.")
            else:
                self.status.set("Transcript copied.")

    def refresh_history(self):
        self.history.configure(values=[f"{index + 1}. {' '.join(row['text'].split())[:56]}"
                                       for index, row in enumerate(self.store.history)])
        self.history.set("Text library" if self.store.history else "Library is empty")

    def load_history(self, _event):
        index = self.history.current()
        if index >= 0:
            self.display(self.store.history[index]["text"])

    def clear_history(self):
        self.in_dialog = True
        try:
            confirmed = messagebox.askyesno("Clear library", "Delete saved Revoice text? Audio is never stored.", parent=self.root)
        finally:
            self.in_dialog = False
        if confirmed:
            try:
                self.store.clear()
            except OSError:
                self.status.set("Couldn’t clear the saved history.")
            self.refresh_history()

    def close(self):
        self.root.after_cancel(self.poll_timer)
        self.cancel()
        self.desktop.close()
        self.root.destroy()


def main():
    if os.name != "nt":
        raise SystemExit("This launcher is for Windows. On Linux, run ./revoice.")
    with single_instance() as primary:
        if not primary:
            messagebox.showinfo("Revoice", "Revoice is already running.")
            return
        data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Revoice"
        root = tk.Tk()
        Dashboard(root, Store(data / "settings.json", data / "history.json"))
        root.mainloop()


if __name__ == "__main__":
    main()
