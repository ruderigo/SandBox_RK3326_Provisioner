/*
 * Host tests for the parts of the firmware with no ESP-IDF in them:
 * the DHCP server (options 1, 3, 6, 121, leases, NAK on a changed
 * network), the captive DNS, and the small helpers.
 *
 *   cc -Wall -Wextra -Werror -I../main test_core.c ../main/dhcp_core.c ../main/util_core.c && ./a.out
 *
 * SPDX-License-Identifier: MIT
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "dhcp_core.h"
#include "util_core.h"
#include "ctl_core.h"

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

#define IP(a, b, c, d) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))

static uint32_t rd32(const uint8_t *b)
{
    return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | b[3];
}

/* A client message: type, options 50/54 when non-zero, ciaddr. */
static size_t msg(uint8_t *b, uint8_t type, const uint8_t mac[6], uint32_t ciaddr,
                  uint32_t requested, uint32_t server_id)
{
    memset(b, 0, 548);
    b[0] = 1; b[1] = 1; b[2] = 6;
    b[4] = 0xDE; b[5] = 0xAD; b[6] = 0xBE; b[7] = 0xEF;
    b[10] = 0x80;  /* broadcast flag */
    b[12] = ciaddr >> 24; b[13] = ciaddr >> 16; b[14] = ciaddr >> 8; b[15] = ciaddr;
    memcpy(b + 28, mac, 6);
    b[236] = 0x63; b[237] = 0x82; b[238] = 0x53; b[239] = 0x63;
    size_t i = 240;
    b[i++] = 0;  /* a pad, to be skipped */
    b[i++] = 53; b[i++] = 1; b[i++] = type;
    if (requested) {
        b[i++] = 50; b[i++] = 4;
        b[i++] = requested >> 24; b[i++] = requested >> 16; b[i++] = requested >> 8; b[i++] = requested;
    }
    if (server_id) {
        b[i++] = 54; b[i++] = 4;
        b[i++] = server_id >> 24; b[i++] = server_id >> 16; b[i++] = server_id >> 8; b[i++] = server_id;
    }
    b[i++] = 55; b[i++] = 4; b[i++] = 1; b[i++] = 3; b[i++] = 6; b[i++] = 121;
    b[i++] = 255;
    return i;
}

/* Finds option code in a reply; returns its value and length. */
static const uint8_t *opt(const uint8_t *r, size_t len, uint8_t code, int *olen)
{
    size_t i = 240;
    while (i < len) {
        uint8_t c = r[i++];
        if (c == 0) continue;
        if (c == 255) break;
        uint8_t l = r[i++];
        if (c == code) {
            *olen = l;
            return r + i;
        }
        i += l;
    }
    *olen = -1;
    return NULL;
}

static int type_of(const uint8_t *r, size_t len)
{
    int l;
    const uint8_t *v = opt(r, len, 53, &l);
    return v && l == 1 ? v[0] : -1;
}

static void test_usb_pool(void)
{
    const uint8_t mac[6] = {0x02, 0x11, 0x22, 0x33, 0x44, 0x55};
    const uint32_t S = IP(10, 77, 0, 1), C = IP(10, 77, 0, 2);
    dhcp_pool_t p;
    dhcp_pool_init(&p, S, IP(255, 255, 255, 0), C, 1, 60);
    uint8_t in[548], out[600];
    int l;

    /* DISCOVER -> OFFER of 10.77.0.2, no router, no DNS, no routes yet */
    size_t n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    size_t r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(r >= 300);
    CHECK(out[0] == 2);
    CHECK(memcmp(out + 4, in + 4, 4) == 0);
    CHECK(memcmp(out + 28, mac, 6) == 0);
    CHECK(type_of(out, r) == DHCP_OFFER);
    CHECK(rd32(out + 16) == C);
    const uint8_t *v = opt(out, r, 54, &l);
    CHECK(v && l == 4 && rd32(v) == S);
    v = opt(out, r, 51, &l);
    CHECK(v && l == 4 && rd32(v) == 60);
    v = opt(out, r, 1, &l);
    CHECK(v && l == 4 && rd32(v) == IP(255, 255, 255, 0));
    CHECK(opt(out, r, 3, &l) == NULL);    /* never a router */
    CHECK(opt(out, r, 6, &l) == NULL);    /* never a DNS */
    CHECK(opt(out, r, 121, &l) == NULL);  /* no Wi-Fi yet */

    /* REQUEST (selecting) -> ACK */
    n = msg(in, DHCP_REQUEST, mac, 0, C, S);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_ACK);
    CHECK(rd32(out + 16) == C);

    /* the S3 joins 192.168.4.0/24: option 121 with it via 10.77.0.1 */
    dhcp_route_t rt = {IP(192, 168, 4, 0), 24, S};
    uint32_t g = p.generation;
    dhcp_pool_set_routes(&p, &rt, 1);
    CHECK(p.generation == g + 1);
    dhcp_pool_set_routes(&p, &rt, 1);     /* the same again: no change */
    CHECK(p.generation == g + 1);

    /* its renewal of the old lease is refused: it starts over */
    n = msg(in, DHCP_REQUEST, mac, C, 0, 0);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_NAK);
    CHECK(rd32(out + 16) == 0);
    CHECK(out[240] == 53 && out[242] == DHCP_NAK);   /* netsvc.c reads the type there */
    CHECK(opt(out, r, 51, &l) == NULL);

    n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_OFFER);
    v = opt(out, r, 121, &l);
    const uint8_t want121[] = {24, 192, 168, 4, 10, 77, 0, 1};
    CHECK(v && l == (int)sizeof(want121) && memcmp(v, want121, sizeof(want121)) == 0);
    CHECK(opt(out, r, 3, &l) == NULL);

    n = msg(in, DHCP_REQUEST, mac, 0, C, S);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_ACK);
    CHECK(opt(out, r, 121, &l) != NULL);

    /* a renewal in this generation is ACKed, unicast to its address */
    n = msg(in, DHCP_REQUEST, mac, C, 0, 0);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_ACK);
    CHECK(rd32(out + 12) == C);
    CHECK(dhcp_reply_unicast_to(in, n) == C);
    n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    CHECK(dhcp_reply_unicast_to(in, n) == 0);
    in[24] = 10;   /* relayed */
    CHECK(dhcp_reply_unicast_to(in, n) == 0);

    /* a request meant for another server: silence */
    n = msg(in, DHCP_REQUEST, mac, 0, C, IP(10, 77, 0, 9));
    CHECK(dhcp_handle(&p, in, n, out, sizeof(out)) == 0);

    /* a request for another address: NAK */
    n = msg(in, DHCP_REQUEST, mac, 0, IP(10, 77, 0, 5), S);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_NAK);

    /* INIT-REBOOT after a replug: the address it had -> ACK with routes */
    n = msg(in, DHCP_REQUEST, mac, 0, C, 0);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_ACK);
    CHECK(opt(out, r, 121, &l) != NULL);

    /* another host on the same port gets the one address too */
    const uint8_t mac2[6] = {0x02, 0x99, 0, 0, 0, 1};
    n = msg(in, DHCP_DISCOVER, mac2, 0, 0, 0);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_OFFER && rd32(out + 16) == C);

    /* Wi-Fi lost: routes cleared, a new generation, no option 121 */
    g = p.generation;
    dhcp_pool_set_routes(&p, NULL, 0);
    CHECK(p.generation == g + 1);
    n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(opt(out, r, 121, &l) == NULL);

    /* INFORM: an ACK with no address and no lease */
    n = msg(in, DHCP_INFORM, mac, C, 0, 0);
    r = dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(type_of(out, r) == DHCP_ACK && rd32(out + 16) == 0 && opt(out, r, 51, &l) == NULL);

    /* not DHCP, or broken: nothing */
    n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    in[236] = 0;
    CHECK(dhcp_handle(&p, in, n, out, sizeof(out)) == 0);
    n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    in[0] = 2;
    CHECK(dhcp_handle(&p, in, n, out, sizeof(out)) == 0);
    CHECK(dhcp_handle(&p, in, 100, out, sizeof(out)) == 0);
    n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    in[n - 1] = 50; /* an option running off the end */
    in[n] = 200;
    CHECK(dhcp_handle(&p, in, n + 1, out, sizeof(out)) == 0);
    n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    CHECK(dhcp_handle(&p, in, n, out, 100) == 0);   /* no room */
}

static void test_ap_pool(void)
{
    /* the setup AP: several phones, a router and DNS (the captive page) */
    dhcp_pool_t p;
    const uint32_t S = IP(10, 77, 1, 1);
    dhcp_pool_init(&p, S, IP(255, 255, 255, 0), IP(10, 77, 1, 2), 3, 120);
    p.router = S;
    p.dns = S;
    uint8_t in[548], out[600], mac[6] = {2, 0, 0, 0, 0, 0};
    uint32_t got[5];
    int l;
    for (int i = 0; i < 5; i++) {
        mac[5] = (uint8_t)i;
        size_t n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
        size_t r = dhcp_handle(&p, in, n, out, sizeof(out));
        got[i] = rd32(out + 16);
        const uint8_t *v = opt(out, r, 3, &l);
        CHECK(v && rd32(v) == S);
        v = opt(out, r, 6, &l);
        CHECK(v && rd32(v) == S);
    }
    CHECK(got[0] == IP(10, 77, 1, 2) && got[1] == IP(10, 77, 1, 3) && got[2] == IP(10, 77, 1, 4));
    CHECK(got[3] >= IP(10, 77, 1, 2) && got[3] <= IP(10, 77, 1, 4));   /* reused */
    CHECK(got[4] >= IP(10, 77, 1, 2) && got[4] <= IP(10, 77, 1, 4) && got[4] != got[3]);
    /* the same phone again keeps its address */
    mac[5] = 4;
    size_t n = msg(in, DHCP_DISCOVER, mac, 0, 0, 0);
    dhcp_handle(&p, in, n, out, sizeof(out));
    CHECK(rd32(out + 16) == got[4]);
    /* RELEASE frees it */
    n = msg(in, DHCP_RELEASE, mac, got[4], 0, S);
    CHECK(dhcp_handle(&p, in, n, out, sizeof(out)) == 0);
}

static void test_routes(void)
{
    uint8_t b[64];
    dhcp_route_t r[3] = {
        {IP(192, 168, 4, 0), 24, IP(10, 77, 0, 1)},
        {IP(10, 0, 0, 0), 8, IP(10, 77, 0, 1)},
        {IP(172, 16, 5, 128), 25, IP(10, 77, 0, 1)},
    };
    size_t n = dhcp_encode_routes(r, 3, b, sizeof(b));
    const uint8_t want[] = {24, 192, 168, 4, 10, 77, 0, 1,
                            8, 10, 10, 77, 0, 1,
                            25, 172, 16, 5, 128, 10, 77, 0, 1};
    CHECK(n == sizeof(want) && memcmp(b, want, n) == 0);
    CHECK(dhcp_encode_routes(r, 3, b, 10) == 0);
    dhcp_route_t z = {0, 0, IP(1, 2, 3, 4)};
    n = dhcp_encode_routes(&z, 1, b, sizeof(b));
    CHECK(n == 5 && b[0] == 0 && b[1] == 1 && b[4] == 4);
    CHECK(dhcp_mask_prefix(IP(255, 255, 255, 0)) == 24);
    CHECK(dhcp_mask_prefix(IP(255, 255, 252, 0)) == 22);
    CHECK(dhcp_mask_prefix(0) == 0);
    CHECK(dhcp_mask_prefix(0xFFFFFFFFu) == 32);
    CHECK(dhcp_mask_prefix(IP(255, 0, 255, 0)) == -1);
}

static void test_util(void)
{
    char b[64] = "";
    CHECK(json_put_str(b, sizeof(b), "Bob \"x\" \\ \n"));
    CHECK(strcmp(b, "\"Bob \\\"x\\\" \\\\ \\u000a\"") == 0);
    char s[8] = "";
    CHECK(!json_put_str(s, sizeof(s), "toolongvalue"));
    CHECK(s[0] == 0);
    CHECK(json_put_str(s, sizeof(s), "abcde"));     /* "abcde" + NUL = 8 */

    char o[40];
    const char *f = "ssid=My+Net%21&password=p%26ss%3Dw&empty=&flag";
    CHECK(form_get(f, strlen(f), "ssid", o, sizeof(o)) == 7 && strcmp(o, "My Net!") == 0);
    CHECK(form_get(f, strlen(f), "password", o, sizeof(o)) == 6 && strcmp(o, "p&ss=w") == 0);
    CHECK(form_get(f, strlen(f), "empty", o, sizeof(o)) == 0 && o[0] == 0);
    CHECK(form_get(f, strlen(f), "flag", o, sizeof(o)) == 0);
    CHECK(form_get(f, strlen(f), "pass", o, sizeof(o)) == -1);
    CHECK(form_get(f, strlen(f), "ssid", o, 4) == -1);
    CHECK(form_get("a=%2", 4, "a", o, sizeof(o)) == -1);
    CHECK(form_get("a=%zz", 5, "a", o, sizeof(o)) == -1);
    CHECK(form_get("a=b%41", 5, "a", o, sizeof(o)) == -1);   /* cut short by its length */

    char ip[16], c[19];
    ip_str(IP(192, 168, 4, 1), ip);
    CHECK(strcmp(ip, "192.168.4.1") == 0);
    cidr_str(IP(192, 168, 4, 37), IP(255, 255, 255, 0), c);
    CHECK(strcmp(c, "192.168.4.0/24") == 0);
    cidr_str(IP(255, 255, 255, 255), 0xFFFFFFFFu, c);
    CHECK(strcmp(c, "255.255.255.255/32") == 0);
    cidr_str(1, IP(255, 0, 255, 0), c);
    CHECK(c[0] == 0);

    CHECK(nets_overlap(IP(10, 77, 0, 0), IP(255, 255, 255, 0), IP(10, 0, 0, 0), IP(255, 0, 0, 0)));
    CHECK(!nets_overlap(IP(10, 77, 0, 0), IP(255, 255, 255, 0), IP(192, 168, 4, 0), IP(255, 255, 255, 0)));
    CHECK(!nets_overlap(IP(10, 77, 0, 0), IP(255, 255, 255, 0), IP(10, 77, 1, 0), IP(255, 255, 255, 0)));


    const uint8_t mac[6] = {1, 2, 3, 4, 0xAB, 0x0C};
    char ss[16];
    setup_ssid(mac, ss);
    CHECK(strcmp(ss, "FireFly-S3-AB0C") == 0);
}

static void test_dns(void)
{
    /* id 0x1234, RD, one question: connectivitycheck.gstatic.com A IN */
    uint8_t q[64] = {0x12, 0x34, 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0};
    size_t i = 12;
    const char *labels[] = {"connectivitycheck", "gstatic", "com"};
    for (int k = 0; k < 3; k++) {
        q[i++] = (uint8_t)strlen(labels[k]);
        memcpy(q + i, labels[k], strlen(labels[k]));
        i += strlen(labels[k]);
    }
    q[i++] = 0;
    q[i++] = 0; q[i++] = 1; q[i++] = 0; q[i++] = 1;
    uint8_t r[128];
    size_t n = dns_captive_reply(q, i, IP(10, 77, 1, 1), r, sizeof(r));
    CHECK(n == i + 16);
    CHECK(r[0] == 0x12 && r[1] == 0x34 && (r[2] & 0x80) && (r[2] & 0x01) && r[3] == 0);
    CHECK(r[7] == 1);
    CHECK(r[i] == 0xC0 && r[i + 1] == 0x0C && r[i + 11] == 4);
    CHECK(rd32(r + i + 12) == IP(10, 77, 1, 1));
    /* AAAA: no answer, NOERROR */
    q[i - 3] = 28;
    n = dns_captive_reply(q, i, IP(10, 77, 1, 1), r, sizeof(r));
    CHECK(n == i && r[7] == 0 && r[3] == 0);
    /* a response, a short packet, no room: nothing */
    q[2] |= 0x80;
    CHECK(dns_captive_reply(q, i, 1, r, sizeof(r)) == 0);
    q[2] &= 0x7F;
    CHECK(dns_captive_reply(q, 8, 1, r, sizeof(r)) == 0);
    CHECK(dns_captive_reply(q, i, 1, r, 10) == 0);
    q[12] = 200;   /* a label running off the end */
    CHECK(dns_captive_reply(q, i, 1, r, sizeof(r)) == 0);
}

static void test_netlist(void)
{
    netlist_t l;
    memset(&l, 0, sizeof(l));
    CHECK(netlist_put(&l, "Home", "password1"));
    CHECK(netlist_put(&l, "Stump", ""));
    CHECK(l.n == 2 && strcmp(l.e[0].ssid, "Stump") == 0 && strcmp(l.e[1].ssid, "Home") == 0);
    /* joining Home again (no password given) moves it up and keeps its password */
    CHECK(netlist_put(&l, "Home", NULL));
    CHECK(l.n == 2 && strcmp(l.e[0].ssid, "Home") == 0 && strcmp(l.e[0].pass, "password1") == 0);
    /* a new password replaces the old */
    CHECK(netlist_put(&l, "Home", "password2"));
    CHECK(strcmp(l.e[0].pass, "password2") == 0 && l.n == 2);
    /* bounds */
    CHECK(!netlist_put(&l, "", ""));
    CHECK(!netlist_put(&l, "x", "short"));
    CHECK(!netlist_put(&l, "123456789012345678901234567890123", ""));
    CHECK(netlist_put(&l, "12345678901234567890123456789012", ""));   /* 32: fine */
    /* a full list drops the oldest */
    char name[8];
    for (int i = 0; i < 10; i++) {
        snprintf(name, sizeof(name), "n%d", i);
        CHECK(netlist_put(&l, name, NULL));
    }
    CHECK(l.n == NETLIST_MAX && strcmp(l.e[0].ssid, "n9") == 0 && strcmp(l.e[7].ssid, "n2") == 0);
    CHECK(netlist_find(&l, "Home") == -1);
    CHECK(netlist_remove(&l, "n5") && l.n == 7 && netlist_find(&l, "n5") == -1);
    CHECK(strcmp(l.e[4].ssid, "n4") == 0 && l.e[7].ssid[0] == 0);
    CHECK(!netlist_remove(&l, "n5"));
    CHECK(netlist_sane(&l));
    l.n = 99;
    CHECK(!netlist_sane(&l) && l.n == 0);
    memset(&l, 'A', sizeof(l));
    l.n = 1;
    CHECK(!netlist_sane(&l));   /* no terminating NULs */
}

static void parse(const char *line, ctl_req_t *r)
{
    ctl_parse(line, strlen(line), r);
}

static void test_ctl(void)
{
    ctl_req_t r;
    parse("{\"id\":7,\"cmd\":\"status\"}", &r);
    CHECK(r.cmd == CTL_STATUS && r.id == 7 && !r.error);
    parse("  { \"cmd\" : \"scan\" , \"id\" : 12 }  ", &r);
    CHECK(r.cmd == CTL_SCAN && r.id == 12);
    parse("{\"cmd\":\"saved\",\"extra\":true,\"n\":-3,\"s\":\"x\"}", &r);
    CHECK(r.cmd == CTL_SAVED && r.id == 0);

    /* join: escapes, UTF-8, a password or none */
    parse("{\"id\":1,\"cmd\":\"join\",\"ssid\":\"Caf\\u00e9 \\\"5G\\\"\",\"password\":\"p\\\\w\\/rd\\tx\"}", &r);
    CHECK(r.cmd == CTL_JOIN && r.has_password);
    CHECK(strcmp(r.ssid, "Caf\xc3\xa9 \"5G\"") == 0);
    CHECK(strcmp(r.password, "p\\w/rd\tx") == 0);
    parse("{\"id\":2,\"cmd\":\"join\",\"ssid\":\"Home\"}", &r);
    CHECK(r.cmd == CTL_JOIN && !r.has_password);
    parse("{\"id\":3,\"cmd\":\"join\",\"ssid\":\"Open\",\"password\":\"\"}", &r);
    CHECK(r.cmd == CTL_JOIN && r.has_password && r.password[0] == 0);
    parse("{\"cmd\":\"join\",\"ssid\":\"\\ud83d\\ude00\"}", &r);   /* a surrogate pair */
    CHECK(r.cmd == CTL_JOIN && strcmp(r.ssid, "\xf0\x9f\x98\x80") == 0);
    parse("{\"cmd\":\"join\"}", &r);
    CHECK(r.cmd == CTL_BAD && strcmp(r.error, "no_ssid") == 0);
    parse("{\"cmd\":\"join\",\"ssid\":\"\"}", &r);
    CHECK(r.cmd == CTL_BAD && strcmp(r.error, "no_ssid") == 0);
    parse("{\"cmd\":\"join\",\"ssid\":\"123456789012345678901234567890123\"}", &r);   /* 33 */
    CHECK(r.cmd == CTL_BAD && strcmp(r.error, "bad_ssid") == 0);
    parse("{\"cmd\":\"join\",\"ssid\":\"x\",\"password\":\"\\u0000abc\"}", &r);
    CHECK(r.cmd == CTL_BAD && strcmp(r.error, "bad_password") == 0);
    parse("{\"cmd\":\"forget\"}", &r);
    CHECK(r.cmd == CTL_FORGET && !r.has_ssid);
    parse("{\"cmd\":\"forget\",\"ssid\":\"Home\"}", &r);
    CHECK(r.cmd == CTL_FORGET && r.has_ssid && strcmp(r.ssid, "Home") == 0);

    /* not requests */
    const char *bad[] = {"", "AT", "AT+CGMI", "[]", "{", "{}", "{\"cmd\":}", "{\"cmd\":\"x\"}",
                         "{\"cmd\":\"status\"", "{\"cmd\":\"status\",}", "{\"cmd\":{\"a\":1}}",
                         "{\"id\":\"7\",\"cmd\":\"status\"}", "{\"cmd\":\"stat\\us\"}", "{\"cmd\":\"status\" x}"};
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        parse(bad[i], &r);
        if (r.cmd != CTL_BAD || !r.error) {
            printf("  accepted: %s\n", bad[i]);
        }
        CHECK(r.cmd == CTL_BAD && r.error);
    }

    /* answers */
    char out[128];
    CHECK(ctl_answer(out, sizeof(out), 7, NULL, "{\"state\":\"idle\"}"));
    CHECK(strcmp(out, "{\"id\":7,\"ok\":true,\"data\":{\"state\":\"idle\"}}\n") == 0);
    CHECK(ctl_answer(out, sizeof(out), 8, "bad_password", NULL));
    CHECK(strcmp(out, "{\"id\":8,\"ok\":false,\"error\":\"bad_password\"}\n") == 0);
    CHECK(ctl_answer(out, sizeof(out), 9, NULL, NULL) && strstr(out, "\"data\":null"));
    CHECK(!ctl_answer(out, 20, 7, NULL, "{\"state\":\"idle\"}"));

    /* lines from a byte stream */
    ctl_lines_t L;
    memset(&L, 0, sizeof(L));
    const char *stream = "{\"cmd\":\"status\"}\r\n\nAT\r\n";
    const char *got[4] = {0};
    int n = 0;
    for (const char *c = stream; *c; c++) {
        const char *line = ctl_feed(&L, *c);
        if (line && n < 4) {
            got[n++] = line[0] ? "x" : "";
            if (n == 1) {
                CHECK(strcmp(line, "{\"cmd\":\"status\"}") == 0);
            }
            if (n == 3) {
                CHECK(strcmp(line, "AT") == 0);
            }
        }
    }
    CHECK(n == 3 && got[1][0] == 0);
    /* a line too long is dropped whole, and the next one is fine */
    for (int i = 0; i < 600; i++) {
        CHECK(ctl_feed(&L, 'a') == NULL);
    }
    CHECK(ctl_feed(&L, '\n') == NULL);
    const char *ok = NULL;
    for (const char *c = "{}\n"; *c; c++) {
        ok = ctl_feed(&L, *c);
    }
    CHECK(ok && strcmp(ok, "{}") == 0);
}

int main(void)
{
    test_usb_pool();
    test_ctl();
    test_ap_pool();
    test_routes();
    test_util();
    test_dns();
    test_netlist();
    printf("%d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
