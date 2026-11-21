function reportFocus() {
    const window = workspace.activeWindow;
    callDBus("io.github.revoice.Revoice.Focus", "/io/github/revoice/Revoice/Focus",
        "io.github.revoice.Revoice.Focus", "Changed",
        window ? window.internalId.toString() : "",
        window ? window.resourceClass.toString() : "");
}
workspace.windowActivated.connect(reportFocus);
reportFocus();
