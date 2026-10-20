/* Copyright (c) 2026 Shengao contributors. MIT.
 * Thin libass adapter; deliberately independent of the Aegisub application.
 */
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "ass.h"

#define API __declspec(dllexport)
typedef struct { ASS_Library *library; ASS_Renderer *renderer; ASS_Track *track; } SG;
API void *sg_create(const char *fonts) {
    SG *sg = calloc(1, sizeof(SG));
    if (!sg) return NULL;
    sg->library = ass_library_init();
    if (!sg->library) { free(sg); return NULL; }
    sg->renderer = ass_renderer_init(sg->library);
    if (!sg->renderer) { ass_library_done(sg->library); free(sg); return NULL; }
    ass_set_fonts(sg->renderer, NULL, "Noto Sans CJK JP", ASS_FONTPROVIDER_AUTODETECT, NULL, 1);
    return sg;
}
API void sg_add_font(void *handle, const char *name, const char *data, int size) {
    SG *sg = handle;
    ass_add_font(sg->library, (char *)name, (char *)data, size);
    ass_set_fonts(sg->renderer, NULL, "Noto Sans CJK JP", ASS_FONTPROVIDER_AUTODETECT, NULL, 1);
}
API int sg_set(void *handle, const char *data, int size) {
    SG *sg = handle;
    ASS_Track *track = ass_read_memory(sg->library, (char *)data, size, "UTF-8");
    if (!track) return 0;
    if (sg->track) ass_free_track(sg->track);
    sg->track = track;
    return 1;
}
/* Straight-alpha RGBA for Qt composition. The output buffer belongs to caller. */
API int sg_render(void *handle, int width, int height, int64_t time, unsigned char *rgba) {
    SG *sg = handle;
    if (!sg || !sg->track || width < 1 || height < 1 || width > 8192 || height > 8192) return 0;
    memset(rgba, 0, (size_t)width * height * 4);
    ass_set_frame_size(sg->renderer, width, height);
    ass_set_storage_size(sg->renderer, width, height);
    int changed;
    for (ASS_Image *im = ass_render_frame(sg->renderer, sg->track, time, &changed); im; im = im->next) {
        unsigned char r = im->color >> 24, g = im->color >> 16, b = im->color >> 8;
        unsigned opacity = 255 - (im->color & 255);
        for (int y = 0; y < im->h; ++y) {
            int yy = im->dst_y + y;
            if (yy < 0 || yy >= height) continue;
            for (int x = 0; x < im->w; ++x) {
                int xx = im->dst_x + x;
                if (xx < 0 || xx >= width) continue;
                unsigned a = (im->bitmap[y * im->stride + x] * opacity + 127) / 255;
                if (!a) continue;
                unsigned char *p = rgba + ((size_t)yy * width + xx) * 4;
                unsigned back = (p[3] * (255-a) + 127) / 255, out = a + back;
                p[0] = (r*a + p[0]*back + out/2)/out;
                p[1] = (g*a + p[1]*back + out/2)/out;
                p[2] = (b*a + p[2]*back + out/2)/out;
                p[3] = out;
            }
        }
    }
    return 1;
}
API void sg_destroy(void *handle) {
    SG *sg = handle;
    if (!sg) return;
    if (sg->track) ass_free_track(sg->track);
    ass_renderer_done(sg->renderer);
    ass_library_done(sg->library);
    free(sg);
}
