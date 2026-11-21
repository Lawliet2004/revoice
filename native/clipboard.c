#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include "data-control.h"

#define MAX_CLIPBOARD_BYTES (16 * 1024 * 1024)

struct selection {
    struct ext_data_control_offer_v1 *handle;
    struct wl_array types;
    bool failed;
};

struct offer {
    struct wl_display *display;
    struct wl_seat *seat;
    struct ext_data_control_manager_v1 *manager;
    const char *directory;
    char *types[48];
    char *content[48];
    size_t sizes[48];
    unsigned count;
    bool running;
    bool report_reads;
    struct selection *selection;
    unsigned selection_revision;
};

static bool write_all(int fd, const char *content, size_t length)
{
    while (length) {
        ssize_t sent = write(fd, content, length);
        if (sent < 0 && errno == EINTR)
            continue;
        if (sent <= 0)
            return false;
        content += sent;
        length -= (size_t)sent;
    }
    return true;
}

static void source_send(void *state, struct ext_data_control_source_v1 *source,
                        const char *mime_type, int32_t destination)
{
    (void)source;
    const struct offer *offer = state;
    for (unsigned i = 0; i < offer->count; ++i) {
        if (strcmp(mime_type, offer->types[i]) != 0)
            continue;
        bool sent = write_all(destination, offer->content[i], offer->sizes[i]);
        if (offer->report_reads && sent && offer->sizes[i] > 0 &&
            (strncmp(mime_type, "text/plain", 10) == 0 || strcmp(mime_type, "UTF8_STRING") == 0)) {
            puts("read");
            fflush(stdout);
        }
        break;
    }
    close(destination);
}

static void source_cancelled(void *state, struct ext_data_control_source_v1 *source)
{
    (void)source;
    ((struct offer *)state)->running = false;
}

static const struct ext_data_control_source_v1_listener source_listener = {
    .send = source_send, .cancelled = source_cancelled,
};

static void advertised_mime(void *state, struct ext_data_control_offer_v1 *incoming,
                            const char *mime)
{
    (void)incoming;
    struct selection *selection = state;
    size_t length = strlen(mime);
    char *type = wl_array_add(&selection->types, length + 1);
    if (!type) {
        selection->failed = true;
        return;
    }
    memcpy(type, mime, length);
    type[length] = '\n';
}

static const struct ext_data_control_offer_v1_listener offer_listener = {
    .offer = advertised_mime,
};

static void device_offer(void *state, struct ext_data_control_device_v1 *device,
                         struct ext_data_control_offer_v1 *incoming)
{
    (void)state;
    (void)device;
    struct selection *selection = calloc(1, sizeof(*selection));
    if (!selection)
        exit(3);
    selection->handle = incoming;
    wl_array_init(&selection->types);
    ext_data_control_offer_v1_add_listener(incoming, &offer_listener, selection);
}

static void destroy_selection(struct selection *selection)
{
    if (!selection)
        return;
    ext_data_control_offer_v1_destroy(selection->handle);
    wl_array_release(&selection->types);
    free(selection);
}

static void device_selection(void *state, struct ext_data_control_device_v1 *device,
                             struct ext_data_control_offer_v1 *incoming)
{
    (void)device;
    struct offer *offer = state;
    destroy_selection(offer->selection);
    offer->selection = incoming ? ext_data_control_offer_v1_get_user_data(incoming) : NULL;
    ++offer->selection_revision;
}

static void device_primary_selection(void *state, struct ext_data_control_device_v1 *device,
                                     struct ext_data_control_offer_v1 *incoming)
{
    (void)state;
    (void)device;
    if (incoming)
        destroy_selection(ext_data_control_offer_v1_get_user_data(incoming));
}

static void device_finished(void *state, struct ext_data_control_device_v1 *device)
{
    (void)device;
    ((struct offer *)state)->running = false;
}

static const struct ext_data_control_device_v1_listener device_listener = {
    .data_offer = device_offer, .selection = device_selection,
    .finished = device_finished, .primary_selection = device_primary_selection,
};

static void global_added(void *state, struct wl_registry *registry,
                         uint32_t name, const char *interface, uint32_t version)
{
    (void)version;
    struct offer *offer = state;
    if (!offer->seat && strcmp(interface, wl_seat_interface.name) == 0)
        offer->seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
    if (strcmp(interface, ext_data_control_manager_v1_interface.name) == 0)
        offer->manager = wl_registry_bind(registry, name, &ext_data_control_manager_v1_interface, 1);
}

static void global_removed(void *state, struct wl_registry *registry, uint32_t name)
{
    (void)state;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = global_added, .global_remove = global_removed,
};

static bool load_entries(struct offer *offer)
{
    char path[PATH_MAX];
    if (snprintf(path, sizeof(path), "%s/manifest", offer->directory) >= (int)sizeof(path))
        return false;
    FILE *manifest = fopen(path, "r");
    if (!manifest)
        return false;
    char *line = NULL;
    size_t capacity = 0;
    ssize_t size;
    while (offer->count < 48 && (size = getline(&line, &capacity, manifest)) > 0) {
        if (line[size - 1] == '\n')
            line[size - 1] = '\0';
        if (snprintf(path, sizeof(path), "%s/%u", offer->directory, offer->count) >= (int)sizeof(path))
            return false;
        FILE *entry = fopen(path, "rb");
        if (!entry || fseek(entry, 0, SEEK_END) < 0)
            return false;
        long bytes = ftell(entry);
        if (bytes < 0 || bytes > MAX_CLIPBOARD_BYTES || fseek(entry, 0, SEEK_SET) < 0)
            return false;
        char *content = malloc(bytes ? (size_t)bytes : 1);
        if (!content || fread(content, 1, (size_t)bytes, entry) != (size_t)bytes)
            return false;
        fclose(entry);
        offer->sizes[offer->count] = (size_t)bytes;
        offer->content[offer->count] = content;
        offer->types[offer->count++] = line;
        line = NULL;
        capacity = 0;
    }
    free(line);
    fclose(manifest);
    return offer->count > 0;
}

static bool has_type(const struct selection *selection, const char *mime)
{
    size_t length = strlen(mime);
    const char *types = selection->types.data;
    for (size_t start = 0, end = 0; end < selection->types.size; ++end) {
        if (types[end] != '\n')
            continue;
        if (end - start == length && memcmp(types + start, mime, length) == 0)
            return true;
        start = end + 1;
    }
    return false;
}

static bool read_selection(struct offer *offer, const char *mime)
{
    struct selection *selection = offer->selection;
    if (!selection || selection->failed || !has_type(selection, mime))
        return false;
    int transfer[2];
    if (pipe(transfer) < 0)
        return false;
    ext_data_control_offer_v1_receive(selection->handle, mime, transfer[1]);
    close(transfer[1]);
    bool ok = wl_display_flush(offer->display) >= 0;
    size_t total = 0;
    char data[65536];
    while (ok) {
        ssize_t received = read(transfer[0], data, sizeof(data));
        if (received < 0 && errno == EINTR)
            continue;
        if (received <= 0) {
            ok = received == 0;
            break;
        }
        total += (size_t)received;
        ok = total <= MAX_CLIPBOARD_BYTES && write_all(STDOUT_FILENO, data, (size_t)received);
    }
    close(transfer[0]);
    return ok;
}

int main(int argc, char **argv)
{
    if (argc < 2 || argc > 4)
        return 2;
    bool list = argc == 2 && strcmp(argv[1], "--list-types") == 0;
    bool read = argc == 3 && strcmp(argv[1], "--read") == 0;
    bool clear_if = argc == 3 && strcmp(argv[1], "--clear-if") == 0;
    bool clear = clear_if || (argc == 2 && strcmp(argv[1], "--clear") == 0);
    bool guarded = argc == 3 && strcmp(argv[2], "--guarded-offer") == 0;
    bool report_reads = guarded || (argc == 3 && strcmp(argv[2], "--report-reads") == 0);
    const char *expected_marker = clear_if ? argv[2] : NULL;
    if (argc == 4 && strcmp(argv[2], "--expect-marker") == 0)
        expected_marker = argv[3];
    if ((argc == 3 && !read && !clear && !report_reads) || (argc == 4 && !expected_marker))
        return 2;
    struct offer offer = { .directory = argv[1], .running = true };
    if (!list && !read && !clear && !load_entries(&offer))
        return 2;
    signal(SIGPIPE, SIG_IGN);
    offer.display = wl_display_connect(NULL);
    if (!offer.display)
        return 3;
    struct wl_registry *registry = wl_display_get_registry(offer.display);
    wl_registry_add_listener(registry, &registry_listener, &offer);
    if (wl_display_roundtrip(offer.display) < 0 || !offer.manager || !offer.seat)
        return 3;
    struct ext_data_control_device_v1 *device =
        ext_data_control_manager_v1_get_data_device(offer.manager, offer.seat);
    ext_data_control_device_v1_add_listener(device, &device_listener, &offer);
    struct ext_data_control_source_v1 *source = NULL;
    if (!read && !list && !clear) {
        source = ext_data_control_manager_v1_create_data_source(offer.manager);
        ext_data_control_source_v1_add_listener(source, &source_listener, &offer);
        for (unsigned i = 0; i < offer.count; ++i)
            ext_data_control_source_v1_offer(source, offer.types[i]);
    }
    if ((list || read || guarded || expected_marker)
            && (wl_display_roundtrip(offer.display) < 0 || !offer.running))
        return 3;
    if (guarded) {
        unsigned snapshot_revision = offer.selection_revision;
        puts("watching");
        fflush(stdout);
        if (getchar() != 'p')
            return 3;
        if (wl_display_roundtrip(offer.display) < 0 || !offer.running)
            return 3;
        if (offer.selection_revision != snapshot_revision) {
            puts("changed");
            return 4;
        }
    }
    if (expected_marker && (!offer.selection || offer.selection->failed
            || !has_type(offer.selection, expected_marker))) {
        puts("changed");
        return 4;
    }
    if (read || list || clear) {
        if (clear) {
            ext_data_control_device_v1_set_selection(device, NULL);
            return wl_display_roundtrip(offer.display) < 0 ? 3 : 0;
        }
        if (read)
            return read_selection(&offer, argv[2]) ? 0 : 3;
        if (!offer.selection)
            return 0;
        return !offer.selection->failed && write_all(STDOUT_FILENO, offer.selection->types.data,
                                                     offer.selection->types.size) ? 0 : 3;
    }
    ext_data_control_device_v1_set_selection(device, source);
    if (wl_display_roundtrip(offer.display) < 0 || !offer.running)
        return 3;
    puts("ready");
    fflush(stdout);
    offer.report_reads = report_reads;
    while (offer.running && wl_display_dispatch(offer.display) != -1)
        ;
    destroy_selection(offer.selection);
    ext_data_control_source_v1_destroy(source);
    ext_data_control_device_v1_destroy(device);
    ext_data_control_manager_v1_destroy(offer.manager);
    wl_seat_destroy(offer.seat);
    wl_registry_destroy(registry);
    wl_display_disconnect(offer.display);
    for (unsigned i = 0; i < offer.count; ++i) {
        free(offer.types[i]);
        free(offer.content[i]);
    }
    return 0;
}
