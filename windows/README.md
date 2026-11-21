# Revoice for Windows x64

Download **revoice-windows-x64.zip** from [GitHub Releases](https://github.com/Lawliet2004/revoice/releases), extract the entire ZIP on Windows, and open **Revoice.cmd**. The portable build includes Python, Tk, and the audio libraries.

## Dictate

1. Choose **OpenAI API** and enter your API key, or choose **Codex sign-in** and select an existing Codex `auth.json` from a ChatGPT sign-in. Both providers send audio over the network. OpenAI API transcription uses API billing.
2. Click **Record**, or press **Ctrl+Alt+F9** from another application. Revoice uses the default Windows microphone. Press the shortcut again or click **Stop recording** to transcribe.
3. Edit the result if needed, click **Copy transcript**, and paste it in your destination app.

Revoice keeps its settings and optional history under `%LOCALAPPDATA%\Revoice`. It keeps the API key in memory for the current session. For Codex, it saves the selected profile path and reads the sign-in token when recording starts. Enable microphone access for desktop apps in Windows if capture fails. If the shortcut is already taken, use the dashboard controls.

The Windows build uses tap-to-start and tap-to-stop. The dashboard displays recording state. The launcher and global shortcut passed under Wine with synthetic audio. Physical microphone capture on Windows and live provider sign-in still need verification.

## Build the portable ZIP on Linux

Run `./build-windows.sh` from the project root with `curl`, `tar`, `sha256sum`, `python3`, and `uv` available. The build downloads a pinned Windows runtime and binary wheels, verifies the runtime checksum, and writes `dist/revoice-windows-x64.zip`.
