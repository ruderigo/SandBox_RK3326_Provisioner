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

/* The DNS forwarder (the handheld asks 10.77.0.1; the S3 asks the joined
 * network's DNS): queries in flight, under ids of our own. */
#define DNSFWD_SLOTS 16
typedef struct {
    struct {
        uint16_t client_id, our_id;
        uint32_t ip;
        uint16_t port;
        uint8_t used;
    } s[DNSFWD_SLOTS];
    uint16_t next_id;
    uint8_t next_slot;
} dnsfwd_t;

/* A query going upstream: gives it an id of ours (in place) and remembers
 * who asked. False if it isn't a query. */
bool dnsfwd_out(dnsfwd_t *f, uint8_t *q, size_t len, uint32_t ip, uint16_t port);
/* An answer from upstream: puts the asker's id back (in place) and says who
 * asked. False if it isn't one of ours. */
bool dnsfwd_in(dnsfwd_t *f, uint8_t *r, size_t len, uint32_t *ip, uint16_t *port);
/* A SERVFAIL answer to a query (no network yet). 0 if it isn't a query. */
size_t dns_servfail(const uint8_t *q, size_t qlen, uint8_t *out, size_t cap);

/* The saved networks, most recent first (kept in NVS as this blob). */
#define NETLIST_MAX 8
typedef struct {
    uint8_t n;
    struct {
        char ssid[33];
        char pass[65];
    } e[NETLIST_MAX];
} netlist_t;

/* Index of ssid, or -1. */
int netlist_find(const netlist_t *l, const char *ssid);
/* Puts ssid at the top (pass NULL: keeps its saved password, or "" if new);
 * the oldest drops off a full list. False if ssid/pass are out of bounds. */
bool netlist_put(netlist_t *l, const char *ssid, const char *pass);
/* Removes ssid; false if it wasn't there. */
bool netlist_remove(netlist_t *l, const char *ssid);
/* A list read back from storage: false (and emptied) if it isn't sane. */
bool netlist_sane(netlist_t *l);
