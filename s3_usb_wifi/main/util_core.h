/*
 * Small helpers with no ESP-IDF in them (host-tested).
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Appends s to buf (NUL-terminated, cap bytes) as a JSON string, quotes
 * included. Returns false (buf unchanged) if it doesn't fit. */
bool json_put_str(char *buf, size_t cap, const char *s);

/* Value of key in an application/x-www-form-urlencoded body, decoded
 * (%XX, '+'). Returns its length, or -1 if absent, malformed or too long. */
int form_get(const char *body, size_t body_len, const char *key, char *out, size_t cap);

/* "a.b.c.d" for a host-order address (out: 16 bytes). */
void ip_str(uint32_t ip, char *out);

/* "a.b.c.d/n" for the network ip&mask (out: 19 bytes); "" if the mask isn't contiguous. */
void cidr_str(uint32_t ip, uint32_t mask, char *out);

/* Do two networks overlap? */
bool nets_overlap(uint32_t a, uint32_t amask, uint32_t b, uint32_t bmask);

/* Does a /node.json body look like a Stump's (it has an "lxmf" key)? */
bool node_json_is_stump(const char *body, size_t len);

/* "FireFly-S3-XXXX" from the last two bytes of the MAC (out: 16 bytes). */
void setup_ssid(const uint8_t mac[6], char *out);

/* Captive DNS for the setup AP: answers an A query with ip, any other
 * query with no answer. Returns the reply's length, or 0 to send nothing. */
size_t dns_captive_reply(const uint8_t *q, size_t qlen, uint32_t ip, uint8_t *out, size_t cap);
