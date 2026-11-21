#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <wayland-client.h>
#include "keystate.h"

struct modifiers {
    struct org_kde_kwin_keystate *keystate;
    unsigned pressed;
    bool ready;
};

static void report(unsigned pressed)
{
    printf("%u\n", pressed);
    fflush(stdout);
}

static void state_changed(void *data, struct org_kde_kwin_keystate *keystate,
                          uint32_t key, uint32_t state)
{
    (void)keystate;
    if (key < ORG_KDE_KWIN_KEYSTATE_KEY_ALT || key > ORG_KDE_KWIN_KEYSTATE_KEY_ALTGR)
        return;
    struct modifiers *modifiers = data;
    unsigned old = modifiers->pressed;
    if (state == ORG_KDE_KWIN_KEYSTATE_STATE_PRESSED)
        modifiers->pressed |= 1u << key;
    else
        modifiers->pressed &= ~(1u << key);
    if (modifiers->ready && modifiers->pressed != old)
        report(modifiers->pressed);
}

static const struct org_kde_kwin_keystate_listener state_listener = {
    .stateChanged = state_changed,
};

static void global_added(void *data, struct wl_registry *registry,
                         uint32_t name, const char *interface, uint32_t version)
{
    struct modifiers *modifiers = data;
    if (version >= 5 && strcmp(interface, org_kde_kwin_keystate_interface.name) == 0)
        modifiers->keystate = wl_registry_bind(registry, name, &org_kde_kwin_keystate_interface, 5);
}

static void global_removed(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = global_added, .global_remove = global_removed,
};

int main(void)
{
    struct wl_display *display = wl_display_connect(NULL);
    if (!display)
        return 1;
    struct modifiers modifiers = {0};
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, &modifiers);
    if (wl_display_roundtrip(display) < 0 || !modifiers.keystate)
        return 1;
    org_kde_kwin_keystate_add_listener(modifiers.keystate, &state_listener, &modifiers);
    org_kde_kwin_keystate_fetchStates(modifiers.keystate);
    if (wl_display_roundtrip(display) < 0)
        return 1;
    modifiers.ready = true;
    report(modifiers.pressed);
    while (wl_display_dispatch(display) != -1)
        ;
    org_kde_kwin_keystate_destroy(modifiers.keystate);
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return 0;
}
