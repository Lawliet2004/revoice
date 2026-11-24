"""Pill window sizes. No display and no window."""

import unittest

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # noqa: F401
except Exception as gtk_error:
    gtk_error = gtk_error
else:
    gtk_error = None


class PillWindowTests(unittest.TestCase):
    def setUp(self):
        if gtk_error is not None:
            self.skipTest(f"Gtk cannot be imported ({gtk_error})")

    def test_pill_window_sizes(self):
        from revoice_app.visuals import pill_window
        self.assertEqual(pill_window("compact", False), (108, 40))
        self.assertEqual(pill_window("regular", False), (164, 52))
        self.assertEqual(pill_window("large", False), (220, 68))
        self.assertEqual(pill_window("compact", True), (640, 196))
        self.assertEqual(pill_window("nope", False), (108, 40))
        self.assertEqual(pill_window("nope", True), (640, 196))
