/*
 * The control channel's protocol (no ESP-IDF here: host-tested). The
 * Provisioner talks to the S3 over the USB serial port that comes with the
 * network card, one JSON object per line each way:
 *
 *   -> {"id":7,"cmd":"status"}
 *   <- {"id":7,"ok":true,"data":{...}}
 *   -> {"id":8,"cmd":"join","ssid":"Home","password":"..."}
 *   <- {"id":8,"ok":false,"error":"bad_password"}
 *
 * Commands: status, scan, saved, join (ssid, password: left out, a saved
 * network keeps its own), forget (ssid; left out, all).
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <stdbool.h>
#include <stddef.h>

typedef enum { CTL_BAD = 0, CTL_STATUS, CTL_SCAN, CTL_SAVED, CTL_JOIN, CTL_FORGET } ctl_cmd_t;

typedef struct {
    long id;                 /* echoed back; 0 if there was none */
    ctl_cmd_t cmd;
    char ssid[33];
    char password[65];
    bool has_ssid, has_password;
    const char *error;       /* why it's CTL_BAD */
} ctl_req_t;

/* Parses one line (a flat JSON object; strings with JSON escapes). */
void ctl_parse(const char *line, size_t len, ctl_req_t *r);

/* The answer line, newline included, into out: data is raw JSON (or NULL),
 * error a word (or NULL for ok). False if it doesn't fit. */
bool ctl_answer(char *out, size_t cap, long id, const char *error, const char *data);

/* Line assembly from a byte stream: feed bytes; returns a complete line (NUL-
 * terminated, without its \r\n) or NULL. A line longer than the buffer is
 * dropped whole. */
typedef struct {
    char buf[512];
    size_t len;
    bool overflow;
} ctl_lines_t;

const char *ctl_feed(ctl_lines_t *l, char c);
