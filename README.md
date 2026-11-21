# Revoice

Revoice turns speech into editable text. The Linux app supports hands-free dictation and can paste into a verified target window on KDE Wayland. The portable Windows x64 preview supports shortcut recording, editing, local history, and manual copy and paste.

## Windows x64 preview

1. Download **revoice-windows-x64.zip** from [GitHub Releases](https://github.com/Lawliet2004/revoice/releases).
2. Extract the entire ZIP on Windows and double-click **Revoice.cmd**. The download includes Python and the audio libraries.
3. Choose **OpenAI API** and enter an API key, or choose **Codex sign-in** and select an existing Codex `auth.json`.
4. Press **Ctrl+Alt+F9** to start and stop recording, or use the **Record** button. Click **Copy transcript** when the text is ready and paste it into your destination app.

Testing covered the launcher, shortcut, and synthetic audio under Wine. Physical Windows microphones and live provider sign-in still need verification. See the [Windows guide](windows/README.md) for microphone access, storage, and build instructions.

## Start dictating on Linux

1. Open **Revoice** and choose **Connect Codex → Use existing Codex sign-in**. You can also open a dedicated login via **Sign in with Codex**, or choose a different Codex profile. Revoice reads the selected sign-in when you dictate and stores only its path.
2. Click the text field where you want your words to appear.
3. Hold **Ctrl+Super** while you speak, then release to transcribe and paste. **Super** is the Windows key.
4. For hands-free dictation, press the shortcut twice within half a second. You can also keep **Ctrl** held and tap **Super** twice. Tap the combination again and release the keys to paste.
5. Use **Settings → Change shortcut** to choose **Shift+Super** or another combination. Turn off **Hold and double-press** for tap-to-start, tap-to-stop behavior.

The floating waveform appears during desktop dictation and disappears when dictation finishes or is cancelled. Click the waveform to stop recording or use **×** to cancel. **Start recording** in the dashboard records inside Revoice and makes a transcript you can copy.

Automatic paste requires a verified target window. When the target changes or Revoice can’t verify it, the transcript stays available for copying. Paste uses **Ctrl+V**, or **Ctrl+Shift+V** in recognized terminals. You can override that in Settings. Revoice checks for clipboard changes before publishing the transcript and before restoring the previous clipboard. For Qt image offers with many equivalent encodings, it restores the image as PNG. If an offer is too large to snapshot safely, the transcript stays available to copy. KDE identifies changes between windows. Within the same window, paste goes to the field currently at the cursor.

## Speech providers

- **Codex sign-in** streams audio to the undocumented ChatGPT dictation service used by Codex. For a modifier-only shortcut, Revoice buffers audio locally until KDE confirms the first release. OpenAI can change this connection or its account eligibility. If disconnected, refresh the profile through Codex or select another connection in Settings.
- **OpenAI API** uses the documented `gpt-transcribe` model. Short dictations are sent after you stop. Long recordings are sent in segments as you dictate. It requires an API key and API usage billing or credits. On Linux, the key is stored in the desktop keyring using Secret Service. On Windows, the key stays in memory for the current session.

Both providers use the network. Hands-free dictation runs until you stop or cancel, subject to microphone and provider availability. Revoice splits long audio into provider-sized segments and combines the text for a single paste. If a later segment fails, completed text stays available to copy. Revoice keeps audio in memory during dictation. Transcript history can be disabled or cleared.

## Linux (Debian and Ubuntu)

The launcher uses the system Python with GTK bindings. On Debian 12 or Ubuntu 24.04 and newer, install the build dependencies first.

```sh
sudo apt install build-essential pkg-config libwayland-dev libwayland-bin
./build.sh --package
sudo apt install ./dist/revoice_0.1.0_$(dpkg --print-architecture).deb
```

Installing the package also installs the runtime dependencies, including `python3-gi-cairo`. For a source checkout, install the runtime packages listed in [build.sh](build.sh) before running `./revoice`. Install `libsecret-tools` if you use the OpenAI API with a desktop keyring. Use `revoice --background` for a tray launch, or `revoice --quit` to quit a running instance.

Revoice targets KDE Plasma on Wayland. Plasma 6.1 or newer supports modifier-only bindings. Hold and double-press on those bindings require KWin's version 5 key-state protocol, verified on Plasma 6.6. Older versions use tap-to-start, tap-to-stop for supported modifier-only bindings. Regular combinations use the desktop's global press and release events. Other desktops can use global shortcuts where their Global Shortcuts portal supports them. Automatic paste requires KDE window tracking, access to `/dev/uinput`, and, on Wayland, the compositor's ext-data-control protocol. The dashboard can record and copy results when a desktop integration is unavailable.

## Tests

```sh
/usr/bin/python3 -m unittest discover -s tests -v
./build.sh
./revoice --quit
PYTHONPATH=. /usr/bin/python3 tests/wayland_ui.py
PYTHONPATH=. /usr/bin/python3 tests/wayland_browser.py
```

The desktop tests use a fixed transcript and require KDE Wayland and `/dev/uinput`. The GTK test checks shortcuts, focus, concurrent clipboard copies, clipboard restoration, and overlay visibility. The browser test uses a temporary Chrome profile in each backend and verifies that paste replaces a selection even when the renderer handles it late. The GTK test saves screenshots in `build/qa/wayland/`.

## Contributing

See [the contribution guide](CONTRIBUTING.md) for test commands and bug reports. The [third-party notices](THIRD_PARTY_NOTICES.md) identify reused assets, protocols, and bundled components.

## References

The local UI reuses Reflow’s manuscript and waveform markup and CSS for the features Revoice supports. [Reflow design](https://github.com/Lawliet2004/reflow/blob/main/DESIGN.md) · [Reflow CSS](https://github.com/Lawliet2004/reflow/blob/main/src/styles/globals.css) · [Reflow gesture](https://github.com/Lawliet2004/reflow/blob/main/src-tauri/src/hotkey/gesture.rs).

The Wayland modifier helper uses KDE's key-state protocol. [KDE keystate](https://github.com/KDE/plasma-wayland-protocols/blob/master/src/protocols/keystate.xml).

The Codex streaming connection follows the protocol described by Speecher. [Speecher protocol notes](https://github.com/firemonster612/speecher/blob/master/docs/research/0004-codex-dictation-protocol.md).
