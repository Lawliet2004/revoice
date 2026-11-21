# Contributing to Revoice

The Linux entry point is `./revoice`. The Windows dashboard is packaged with `./build-windows.sh`. See the [Linux setup](README.md#linux-debian-and-ubuntu) and [Windows build instructions](windows/README.md#build-the-portable-zip-on-linux) for dependencies.

Run the unit tests before submitting changes.

```sh
./build.sh
/usr/bin/python3 -m unittest discover -s tests -v
```

The Windows dashboard smoke test uses Tk, synthetic PCM, and a local HTTP server. On Linux, install `python3-tk`, `xvfb`, and `xauth`, then run it from the repository root.

```sh
PYTHONPATH=. xvfb-run -a /usr/bin/python3 tests/windows_smoke.py
```

Use the [KDE Wayland tests](README.md#tests) for changes to shortcut gestures, focus, or clipboard handling. Run them from a test desktop session with access to `/dev/uinput`.

For bug reports, include your OS version, desktop environment or Windows build, Revoice version, speech provider, and steps to reproduce. Remove credentials, transcript history, and private audio from anything you attach.
