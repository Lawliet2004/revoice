"""Win32 global shortcut and single-instance support."""

import ctypes as c
import threading
from contextlib import contextmanager
from ctypes import wintypes as w


@contextmanager
def single_instance():
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (c.c_void_p, w.BOOL, w.LPCWSTR)
    kernel.CreateMutexW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    kernel.CloseHandle.restype = w.BOOL
    c.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, "Local\\io.github.revoice.Revoice")
    error = c.get_last_error()
    if not handle:
        raise c.WinError(error)
    try:
        yield error != 183  # ERROR_ALREADY_EXISTS
    finally:
        kernel.CloseHandle(handle)


class WindowsDesktop:
    HOTKEY = "Ctrl+Alt+F9"
    WM_HOTKEY = 0x0312

    def __init__(self, emit):
        user32 = c.WinDLL("user32", use_last_error=True)
        self.emit = emit
        self.closing = threading.Event()
        for name, arguments, result in (
            ("RegisterHotKey", (w.HWND, c.c_int, w.UINT, w.UINT), w.BOOL),
            ("UnregisterHotKey", (w.HWND, c.c_int), w.BOOL),
            ("PeekMessageW", (c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT), w.BOOL),
        ):
            function = getattr(user32, name)
            function.argtypes = arguments
            function.restype = result
        self.user32 = user32
        self.thread = threading.Thread(target=self.listen, daemon=True)
        self.thread.start()

    def listen(self):
        message = w.MSG()
        self.user32.PeekMessageW(c.byref(message), None, 0, 0, 0)  # Initialize this thread's message queue.
        modifiers = 0x0002 | 0x0001 | 0x4000  # Ctrl, Alt, MOD_NOREPEAT
        if not self.user32.RegisterHotKey(None, 1, modifiers, 0x78):  # VK_F9
            self.emit("shortcut", f"{self.HOTKEY} is unavailable. Use the Record button.")
            return
        self.emit("shortcut", f"{self.HOTKEY} starts and stops recording.")
        try:
            while not self.closing.wait(.04):
                if self.user32.PeekMessageW(c.byref(message), None, self.WM_HOTKEY, self.WM_HOTKEY, 1):
                    self.emit("hotkey")
        finally:
            self.user32.UnregisterHotKey(None, 1)

    def close(self):
        self.closing.set()
        self.thread.join(timeout=.25)
