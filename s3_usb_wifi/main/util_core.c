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

int netlist_find(const netlist_t *l, const char *ssid)
{
    for (int i = 0; i < l->n && i < NETLIST_MAX; i++) {
        if (strcmp(l->e[i].ssid, ssid) == 0) {
            return i;
        }
    }
    return -1;
}

bool netlist_put(netlist_t *l, const char *ssid, const char *pass)
{
    size_t sl = strlen(ssid);
    if (sl < 1 || sl > 32) {
        return false;
    }
    char keep[65] = "";
    int at = netlist_find(l, ssid);
    if (pass == NULL) {
        pass = at >= 0 ? l->e[at].pass : "";
    }
    size_t pl = strlen(pass);
    if (pl != 0 && (pl < 8 || pl > 63)) {
        return false;
    }
    memcpy(keep, pass, pl + 1);
    if (at < 0) {
        at = l->n < NETLIST_MAX ? l->n++ : NETLIST_MAX - 1;   /* the oldest goes */
    }
    for (int i = at; i > 0; i--) {
        l->e[i] = l->e[i - 1];
    }
    memset(&l->e[0], 0, sizeof(l->e[0]));
    memcpy(l->e[0].ssid, ssid, sl + 1);
    memcpy(l->e[0].pass, keep, pl + 1);
    return true;
}

bool netlist_remove(netlist_t *l, const char *ssid)
{
    int at = netlist_find(l, ssid);
    if (at < 0) {
        return false;
    }
    for (int i = at; i + 1 < l->n; i++) {
        l->e[i] = l->e[i + 1];
    }
    l->n--;
    memset(&l->e[l->n], 0, sizeof(l->e[0]));
    return true;
}

bool netlist_sane(netlist_t *l)
{
    bool ok = l->n <= NETLIST_MAX;
    for (int i = 0; ok && i < l->n; i++) {
        ok = memchr(l->e[i].ssid, 0, sizeof(l->e[i].ssid)) && memchr(l->e[i].pass, 0, sizeof(l->e[i].pass))
             && l->e[i].ssid[0];
    }
    if (!ok) {
        memset(l, 0, sizeof(*l));
    }
    return ok;
}

bool dnsfwd_out(dnsfwd_t *f, uint8_t *q, size_t len, uint32_t ip, uint16_t port)
{
    if (len < 12 || (q[2] & 0x80)) {
        return false;
    }
    if (++f->next_id == 0) {
        f->next_id = 1;
    }
    int slot = -1;
    for (int i = 0; i < DNSFWD_SLOTS; i++) {
        if (!f->s[i].used) {
            slot = i;
            break;
        }
    }
    if (slot < 0) {
        slot = f->next_slot;   /* the oldest in flight gives way */
        f->next_slot = (uint8_t)((f->next_slot + 1) % DNSFWD_SLOTS);
    }
    f->s[slot].client_id = (uint16_t)(q[0] << 8 | q[1]);
    f->s[slot].our_id = f->next_id;
    f->s[slot].ip = ip;
    f->s[slot].port = port;
    f->s[slot].used = 1;
    q[0] = (uint8_t)(f->next_id >> 8);
    q[1] = (uint8_t)f->next_id;
    return true;
}

bool dnsfwd_in(dnsfwd_t *f, uint8_t *r, size_t len, uint32_t *ip, uint16_t *port)
{
    if (len < 12 || !(r[2] & 0x80)) {
        return false;
    }
    uint16_t id = (uint16_t)(r[0] << 8 | r[1]);
    for (int i = 0; i < DNSFWD_SLOTS; i++) {
        if (f->s[i].used && f->s[i].our_id == id) {
            r[0] = (uint8_t)(f->s[i].client_id >> 8);
            r[1] = (uint8_t)f->s[i].client_id;
            *ip = f->s[i].ip;
            *port = f->s[i].port;
            f->s[i].used = 0;
            return true;
        }
    }
    return false;
}

size_t dns_servfail(const uint8_t *q, size_t qlen, uint8_t *out, size_t cap)
{
    if (qlen < 12 || (q[2] & 0x80) || cap < 12) {
        return 0;
    }
    /* the header and the one question, nothing after it (EDNS etc. dropped) */
    size_t end = 12;
    int qd = (q[4] == 0 && q[5] == 1);
    if (qd) {
        while (end < qlen && q[end] != 0 && !(q[end] & 0xC0)) {
            end += 1 + q[end];
        }
        if (end < qlen && q[end] == 0 && end + 5 <= qlen) {
            end += 5;
        } else {
            qd = 0;
            end = 12;
        }
    }
    if (end > cap) {
        return 0;
    }
    memcpy(out, q, end);
    out[2] = 0x80 | (q[2] & 0x79);   /* a response; opcode and RD kept */
    out[3] = 0x80 | 0x02;            /* RA, SERVFAIL */
    out[4] = 0;
    out[5] = (uint8_t)qd;
    out[6] = out[7] = out[8] = out[9] = out[10] = out[11] = 0;
    return end;
}
