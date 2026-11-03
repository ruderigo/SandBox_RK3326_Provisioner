/*
 * SPDX-License-Identifier: MIT
 */
#include "util_core.h"
#include <stdio.h>
#include <string.h>

bool json_put_str(char *buf, size_t cap, const char *s)
{
    size_t at = strlen(buf);
    size_t start = at;
    if (at + 1 >= cap) {
        return false;
    }
    buf[at++] = '"';
    for (const unsigned char *c = (const unsigned char *)s; *c; c++) {
        char esc[7] = {0};
        if (*c == '"' || *c == '\\') {
            esc[0] = '\\';
            esc[1] = (char)*c;
        } else if (*c < 0x20) {
            snprintf(esc, sizeof(esc), "\\u%04x", *c);
        } else {
            esc[0] = (char)*c;
        }
        size_t n = strlen(esc);
        if (at + n + 2 > cap) {
            buf[start] = 0;
            return false;
        }
        memcpy(buf + at, esc, n);
        at += n;
    }
    if (at + 2 > cap) {
        buf[start] = 0;
        return false;
    }
    buf[at++] = '"';
    buf[at] = 0;
    return true;
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int form_get(const char *body, size_t len, const char *key, char *out, size_t cap)
{
    size_t klen = strlen(key);
    size_t i = 0;
    while (i < len) {
        size_t end = i;
        while (end < len && body[end] != '&') {
            end++;
        }
        if (end - i > klen && memcmp(body + i, key, klen) == 0 && body[i + klen] == '=') {
            size_t o = 0;
            for (size_t j = i + klen + 1; j < end; j++) {
                char c = body[j];
                if (c == '+') {
                    c = ' ';
                } else if (c == '%') {
                    if (j + 2 >= end) {
                        return -1;
                    }
                    int h = hexval(body[j + 1]), l = hexval(body[j + 2]);
                    if (h < 0 || l < 0) {
                        return -1;
                    }
                    c = (char)(h * 16 + l);
                    j += 2;
                }
                if (o + 1 >= cap) {
                    return -1;
                }
                out[o++] = c;
            }
            out[o] = 0;
            return (int)o;
        } else if (end - i == klen && memcmp(body + i, key, klen) == 0) {
            if (cap < 1) {
                return -1;
            }
            out[0] = 0;
            return 0;
        }
        i = end + 1;
    }
    return -1;
}

void ip_str(uint32_t ip, char *out)
{
    snprintf(out, 16, "%u.%u.%u.%u", (unsigned)(ip >> 24) & 255, (unsigned)(ip >> 16) & 255,
             (unsigned)(ip >> 8) & 255, (unsigned)ip & 255);
}

void cidr_str(uint32_t ip, uint32_t mask, char *out)
{
    int n = 0;
    while (n < 32 && (mask & (0x80000000u >> n))) {
        n++;
    }
    if (mask != (n ? (0xFFFFFFFFu << (32 - n)) : 0)) {
        out[0] = 0;
        return;
    }
    char a[16];
    ip_str(ip & mask, a);
    snprintf(out, 19, "%s/%d", a, n);
}

bool nets_overlap(uint32_t a, uint32_t amask, uint32_t b, uint32_t bmask)
{
    uint32_t m = amask & bmask;  /* the shorter prefix */
    return (a & m) == (b & m);
}

bool node_json_is_stump(const char *body, size_t len)
{
    static const char key[] = "\"lxmf\"";
    size_t k = sizeof(key) - 1;
    for (size_t i = 0; i + k <= len; i++) {
        if (memcmp(body + i, key, k) == 0) {
            size_t j = i + k;
            while (j < len && (body[j] == ' ' || body[j] == '\t' || body[j] == '\r' || body[j] == '\n')) {
                j++;
            }
            if (j < len && body[j] == ':') {
                return true;
            }
        }
    }
    return false;
}

void setup_ssid(const uint8_t mac[6], char *out)
{
    snprintf(out, 16, "FireFly-S3-%02X%02X", mac[4], mac[5]);
}

size_t dns_captive_reply(const uint8_t *q, size_t qlen, uint32_t ip, uint8_t *out, size_t cap)
{
    if (qlen < 12 || (q[2] & 0x80)) {      /* too short, or a response */
        return 0;
    }
    if (((q[2] >> 3) & 0x0F) != 0) {      /* only standard queries */
        return 0;
    }
    if (q[4] != 0 || q[5] != 1) {         /* exactly one question */
        return 0;
    }
    size_t i = 12;
    while (i < qlen && q[i] != 0) {
        if (q[i] & 0xC0) {
            return 0;                     /* no compression in a question */
        }
        i += 1 + q[i];
    }
    if (i + 5 > qlen) {
        return 0;
    }
    size_t qend = i + 5;                  /* the 0, QTYPE, QCLASS */
    uint16_t qtype = (uint16_t)((q[i + 1] << 8) | q[i + 2]);
    uint16_t qclass = (uint16_t)((q[i + 3] << 8) | q[i + 4]);
    int answer = (qtype == 1 || qtype == 255) && qclass == 1;
    size_t need = qend + (answer ? 16 : 0);
    if (need > cap) {
        return 0;
    }
    memcpy(out, q, qend);
    out[2] = 0x84 | (q[2] & 0x01);        /* response, authoritative, RD copied */
    out[3] = 0x00;                        /* NOERROR */
    out[6] = 0;
    out[7] = answer ? 1 : 0;              /* ANCOUNT */
    out[8] = out[9] = out[10] = out[11] = 0;
    if (!answer) {
        return qend;
    }
    uint8_t *a = out + qend;
    a[0] = 0xC0; a[1] = 0x0C;             /* the question's name */
    a[2] = 0; a[3] = 1;                   /* A */
    a[4] = 0; a[5] = 1;                   /* IN */
    a[6] = 0; a[7] = 0; a[8] = 0; a[9] = 10;   /* TTL 10 s */
    a[10] = 0; a[11] = 4;
    a[12] = ip >> 24; a[13] = ip >> 16; a[14] = ip >> 8; a[15] = ip;
    return need;
}
