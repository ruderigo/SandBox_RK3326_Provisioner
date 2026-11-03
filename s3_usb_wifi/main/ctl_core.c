/*
 * SPDX-License-Identifier: MIT
 */
#include "ctl_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static size_t skip_ws(const char *s, size_t i, size_t n)
{
    while (i < n && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) {
        i++;
    }
    return i;
}

static int hex4(const char *s, unsigned *v)
{
    *v = 0;
    for (int k = 0; k < 4; k++) {
        char c = s[k];
        int d = (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10
                : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
        if (d < 0) {
            return -1;
        }
        *v = *v * 16 + (unsigned)d;
    }
    return 0;
}

/* A JSON string at s[i] (on its opening quote) into out (UTF-8). Returns the
 * index after the closing quote, or 0 (bad, or too long for out). */
static size_t parse_string(const char *s, size_t i, size_t n, char *out, size_t cap)
{
    if (i >= n || s[i] != '"') {
        return 0;
    }
    size_t o = 0;
    for (i++; i < n; i++) {
        unsigned c = (unsigned char)s[i];
        if (c == '"') {
            if (out) {
                out[o] = 0;
            }
            return i + 1;
        }
        char tmp[4];
        size_t k = 0;
        if (c == '\\') {
            if (++i >= n) {
                return 0;
            }
            switch (s[i]) {
            case '"': tmp[k++] = '"'; break;
            case '\\': tmp[k++] = '\\'; break;
            case '/': tmp[k++] = '/'; break;
            case 'b': tmp[k++] = '\b'; break;
            case 'f': tmp[k++] = '\f'; break;
            case 'n': tmp[k++] = '\n'; break;
            case 'r': tmp[k++] = '\r'; break;
            case 't': tmp[k++] = '\t'; break;
            case 'u': {
                unsigned u;
                if (i + 4 >= n || hex4(s + i + 1, &u) != 0) {
                    return 0;
                }
                i += 4;
                if (u >= 0xD800 && u <= 0xDBFF) {   /* a surrogate pair */
                    unsigned lo;
                    if (i + 6 >= n || s[i + 1] != '\\' || s[i + 2] != 'u' || hex4(s + i + 3, &lo) != 0
                            || lo < 0xDC00 || lo > 0xDFFF) {
                        return 0;
                    }
                    i += 6;
                    u = 0x10000 + ((u - 0xD800) << 10) + (lo - 0xDC00);
                } else if (u >= 0xDC00 && u <= 0xDFFF) {
                    return 0;
                }
                if (u == 0) {
                    return 0;               /* no NULs inside names or passwords */
                }
                if (u < 0x80) {
                    tmp[k++] = (char)u;
                } else if (u < 0x800) {
                    tmp[k++] = (char)(0xC0 | (u >> 6));
                    tmp[k++] = (char)(0x80 | (u & 0x3F));
                } else if (u < 0x10000) {
                    tmp[k++] = (char)(0xE0 | (u >> 12));
                    tmp[k++] = (char)(0x80 | ((u >> 6) & 0x3F));
                    tmp[k++] = (char)(0x80 | (u & 0x3F));
                } else {
                    tmp[k++] = (char)(0xF0 | (u >> 18));
                    tmp[k++] = (char)(0x80 | ((u >> 12) & 0x3F));
                    tmp[k++] = (char)(0x80 | ((u >> 6) & 0x3F));
                    tmp[k++] = (char)(0x80 | (u & 0x3F));
                }
                break;
            }
            default:
                return 0;
            }
        } else if (c < 0x20) {
            return 0;
        } else {
            tmp[k++] = (char)c;
        }
        if (out) {
            if (o + k + 1 > cap) {
                return 0;
            }
            memcpy(out + o, tmp, k);
        }
        o += k;
    }
    return 0;
}

/* Skips a JSON value we don't use (number, true/false/null, string). */
static size_t skip_value(const char *s, size_t i, size_t n)
{
    if (i < n && s[i] == '"') {
        return parse_string(s, i, n, NULL, 0);
    }
    size_t start = i;
    while (i < n && s[i] != ',' && s[i] != '}' && s[i] != ' ' && s[i] != '\t'
           && s[i] != '\r' && s[i] != '\n') {
        if (s[i] == '{' || s[i] == '[' || s[i] == '"') {
            return 0;   /* nothing nested in a request */
        }
        i++;
    }
    return i > start ? i : 0;
}

void ctl_parse(const char *s, size_t n, ctl_req_t *r)
{
    memset(r, 0, sizeof(*r));
    char cmd[16] = "";
    size_t i = skip_ws(s, 0, n);
    if (i >= n || s[i] != '{') {
        r->error = "bad_request";
        return;
    }
    i = skip_ws(s, i + 1, n);
    if (i < n && s[i] == '}') {
        r->error = "no_cmd";
        return;
    }
    for (;;) {
        char key[16];
        size_t j = parse_string(s, i, n, key, sizeof(key));
        if (!j) {
            r->error = "bad_request";
            return;
        }
        i = skip_ws(s, j, n);
        if (i >= n || s[i] != ':') {
            r->error = "bad_request";
            return;
        }
        i = skip_ws(s, i + 1, n);
        if (strcmp(key, "id") == 0) {
            char *end;
            char num[24];
            size_t k = 0;
            while (i + k < n && k + 1 < sizeof(num) && ((s[i + k] >= '0' && s[i + k] <= '9') || s[i + k] == '-')) {
                num[k] = s[i + k];
                k++;
            }
            num[k] = 0;
            r->id = strtol(num, &end, 10);
            if (k == 0 || *end) {
                r->error = "bad_request";
                return;
            }
            j = i + k;
        } else if (strcmp(key, "cmd") == 0) {
            j = parse_string(s, i, n, cmd, sizeof(cmd));
        } else if (strcmp(key, "ssid") == 0) {
            j = parse_string(s, i, n, r->ssid, sizeof(r->ssid));
            r->has_ssid = j != 0;
            if (!j) {
                r->error = "bad_ssid";
                return;
            }
        } else if (strcmp(key, "password") == 0) {
            j = parse_string(s, i, n, r->password, sizeof(r->password));
            r->has_password = j != 0;
            if (!j) {
                r->error = "bad_password";
                return;
            }
        } else {
            j = skip_value(s, i, n);
        }
        if (!j) {
            r->error = "bad_request";
            return;
        }
        i = skip_ws(s, j, n);
        if (i < n && s[i] == ',') {
            i = skip_ws(s, i + 1, n);
            continue;
        }
        if (i < n && s[i] == '}') {
            break;
        }
        r->error = "bad_request";
        return;
    }
    static const struct {
        const char *name;
        ctl_cmd_t cmd;
    } cmds[] = {{"status", CTL_STATUS}, {"scan", CTL_SCAN}, {"saved", CTL_SAVED},
                {"join", CTL_JOIN}, {"forget", CTL_FORGET}};
    for (size_t k = 0; k < sizeof(cmds) / sizeof(cmds[0]); k++) {
        if (strcmp(cmd, cmds[k].name) == 0) {
            r->cmd = cmds[k].cmd;
        }
    }
    if (r->cmd == CTL_BAD) {
        r->error = cmd[0] ? "unknown_cmd" : "no_cmd";
    } else if (r->cmd == CTL_JOIN && (!r->has_ssid || !r->ssid[0])) {
        r->cmd = CTL_BAD;
        r->error = "no_ssid";
    }
}

bool ctl_answer(char *out, size_t cap, long id, const char *error, const char *data)
{
    int w;
    if (error) {
        w = snprintf(out, cap, "{\"id\":%ld,\"ok\":false,\"error\":\"%s\"}\n", id, error);
    } else {
        w = snprintf(out, cap, "{\"id\":%ld,\"ok\":true,\"data\":%s}\n", id, data ? data : "null");
    }
    return w > 0 && (size_t)w < cap;
}

const char *ctl_feed(ctl_lines_t *l, char c)
{
    if (c == '\r') {
        return NULL;
    }
    if (c == '\n') {
        bool bad = l->overflow;
        l->buf[l->len] = 0;
        l->len = 0;
        l->overflow = false;
        return bad ? NULL : l->buf;
    }
    if (l->len + 1 >= sizeof(l->buf)) {
        l->overflow = true;
        return NULL;
    }
    if (!l->overflow) {
        l->buf[l->len++] = c;
    }
    return NULL;
}
