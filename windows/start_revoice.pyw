"""Launch the portable Windows app with its bundled Python and dependencies."""

import ctypes
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from revoice_app.windows import main

    main()
except Exception:
    folder = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Revoice"
    message = "Revoice couldn’t start. Extract the complete ZIP before launching."
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "startup.log").write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass
    else:
        message += f"\n\nDetails: {folder / 'startup.log'}"
    ctypes.windll.user32.MessageBoxW(None, message, "Revoice", 0x10)
    raise SystemExit(1)
