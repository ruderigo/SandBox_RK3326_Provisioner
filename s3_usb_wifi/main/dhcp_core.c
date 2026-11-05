/*
 * SPDX-License-Identifier: MIT
 */
#include "dhcp_core.h"
#include <string.h>

#define BOOTP_FIXED   236
#define MAGIC_OFF     236
#define OPTS_OFF      240
#define MIN_REPLY     300  /* BOOTP's minimum message size */

static uint32_t rd32(const uint8_t *b)
{
    return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | b[3];
}

static void wr32(uint8_t *b, uint32_t v)
{
    b[0] = v >> 24; b[1] = v >> 16; b[2] = v >> 8; b[3] = v;
}

int dhcp_mask_prefix(uint32_t mask)
{
    int n = 0;
    while (n < 32 && (mask & (0x80000000u >> n))) {
        n++;
    }
    uint32_t want = n ? (0xFFFFFFFFu << (32 - n)) : 0;
    return mask == want ? n : -1;
}

void dhcp_pool_init(dhcp_pool_t *p, uint32_t server_ip, uint32_t netmask,
                    uint32_t first_ip, uint8_t pool_size, uint32_t lease_s)
{
    memset(p, 0, sizeof(*p));
    p->server_ip = server_ip;
    p->netmask = netmask;
    p->first_ip = first_ip;
    p->pool_size = pool_size < 1 ? 1 : (pool_size > DHCP_MAX_LEASES ? DHCP_MAX_LEASES : pool_size);
    p->lease_s = lease_s;
    p->generation = 1;
}

void dhcp_pool_set_routes(dhcp_pool_t *p, const dhcp_route_t *r, uint8_t n)
{
    if (n > DHCP_MAX_ROUTES) {
        n = DHCP_MAX_ROUTES;
    }
    int same = (n == p->n_routes);
    for (uint8_t i = 0; same && i < n; i++) {
        same = r[i].net == p->routes[i].net && r[i].prefix == p->routes[i].prefix
               && r[i].via == p->routes[i].via;
    }
    if (same) {
        return;
    }
    for (uint8_t i = 0; i < n; i++) {
        p->routes[i] = r[i];
    }
    p->n_routes = n;
    p->generation++;
}

size_t dhcp_encode_routes(const dhcp_route_t *r, uint8_t n, uint8_t *out, size_t cap)
{
    size_t len = 0;
    for (uint8_t i = 0; i < n; i++) {
        uint8_t prefix = r[i].prefix > 32 ? 32 : r[i].prefix;
        size_t sig = (prefix + 7) / 8;
        if (len + 1 + sig + 4 > cap) {
            return 0;
        }
        uint8_t net[4];
        wr32(net, r[i].net);
        out[len++] = prefix;
        memcpy(out + len, net, sig);
        len += sig;
        wr32(out + len, r[i].via);
        len += 4;
    }
    return len;
}

typedef struct {
    int type;
    uint32_t requested;  /* option 50 */
    uint32_t server_id;  /* option 54 */
    int has_requested, has_server_id;
} parsed_t;

static int parse_options(const uint8_t *in, size_t len, parsed_t *o)
{
    memset(o, 0, sizeof(*o));
    size_t i = OPTS_OFF;
    while (i < len) {
        uint8_t code = in[i++];
        if (code == 0) {
            continue;
        }
        if (code == 255) {
            break;
        }
        if (i >= len) {
            return -1;
        }
        uint8_t olen = in[i++];
        if (i + olen > len) {
            return -1;
        }
        const uint8_t *v = in + i;
        if (code == 53 && olen == 1) {
            o->type = v[0];
        } else if (code == 50 && olen == 4) {
            o->requested = rd32(v);
            o->has_requested = 1;
        } else if (code == 54 && olen == 4) {
            o->server_id = rd32(v);
            o->has_server_id = 1;
        }
        i += olen;
    }
    return o->type ? 0 : -1;
}

/* The slot for this MAC: its lease, else a free one, else the next to reuse. */
static int slot_for(dhcp_pool_t *p, const uint8_t *mac, int allocate)
{
    for (int i = 0; i < p->pool_size; i++) {
        if (p->leases[i].used && memcmp(p->leases[i].mac, mac, 6) == 0) {
            return i;
        }
    }
    if (!allocate) {
        return -1;
    }
    int s = -1;
    for (int i = 0; i < p->pool_size; i++) {
        if (!p->leases[i].used) {
            s = i;
            break;
        }
    }
    if (s < 0) {
        s = p->next % p->pool_size;
        p->next = (uint8_t)((s + 1) % p->pool_size);
    }
    memcpy(p->leases[s].mac, mac, 6);
    p->leases[s].used = 1;
    p->leases[s].gen = 0;
    return s;
}

static size_t put_opt(uint8_t *out, size_t at, size_t cap, uint8_t code,
                      const uint8_t *v, size_t len)
{
    if (at == 0 || len > 255 || at + 2 + len > cap) {
        return 0;
    }
    out[at] = code;
    out[at + 1] = (uint8_t)len;
    memcpy(out + at + 2, v, len);
    return at + 2 + len;
}

static size_t put_u32(uint8_t *out, size_t at, size_t cap, uint8_t code, uint32_t v)
{
    uint8_t b[4];
    wr32(b, v);
    return put_opt(out, at, cap, code, b, 4);
}

static size_t reply(dhcp_pool_t *p, const uint8_t *in, uint8_t type, uint32_t yiaddr,
                    int with_lease, uint8_t *out, size_t cap)
{
    if (cap < MIN_REPLY) {
        return 0;
    }
    memset(out, 0, cap < 576 ? cap : 576);
    out[0] = 2;                 /* BOOTREPLY */
    out[1] = 1;                 /* Ethernet */
    out[2] = 6;
    memcpy(out + 4, in + 4, 4); /* xid */
    memcpy(out + 10, in + 10, 2);  /* flags */
    if (type != DHCP_NAK) {
        memcpy(out + 12, in + 12, 4);  /* ciaddr */
    }
    wr32(out + 16, yiaddr);
    memcpy(out + 24, in + 24, 4);  /* giaddr */
    memcpy(out + 28, in + 28, 16); /* chaddr */
    wr32(out + MAGIC_OFF, 0x63825363u);

    size_t at = OPTS_OFF;
    uint8_t t = type;
    at = put_opt(out, at, cap, 53, &t, 1);
    at = put_u32(out, at, cap, 54, p->server_ip);
    if (type != DHCP_NAK) {
        if (with_lease) {
            at = put_u32(out, at, cap, 51, p->lease_s);
            at = put_u32(out, at, cap, 58, p->lease_s / 2);
            at = put_u32(out, at, cap, 59, p->lease_s * 7 / 8);
        }
        at = put_u32(out, at, cap, 1, p->netmask);
        if (p->router) {
            at = put_u32(out, at, cap, 3, p->router);
        }
        if (p->dns) {
            at = put_u32(out, at, cap, 6, p->dns);
        }
        if (p->n_routes) {
            uint8_t rb[DHCP_MAX_ROUTES * 9];
            size_t rl = dhcp_encode_routes(p->routes, p->n_routes, rb, sizeof(rb));
            if (rl) {
                at = put_opt(out, at, cap, 121, rb, rl);
            }
        }
    }
    if (at == 0 || at + 1 > cap) {
        return 0;
    }
    out[at++] = 255;
    return at < MIN_REPLY ? MIN_REPLY : at;
}

uint32_t dhcp_reply_unicast_to(const uint8_t *in, size_t len)
{
    if (len < OPTS_OFF || rd32(in + 24) != 0) {
        return 0;   /* relayed (giaddr): not something we see */
    }
    return rd32(in + 12);
}

size_t dhcp_handle(dhcp_pool_t *p, const uint8_t *in, size_t len, uint8_t *out, size_t cap)
{
    if (len < OPTS_OFF || in[0] != 1 || in[1] != 1 || in[2] != 6
            || rd32(in + MAGIC_OFF) != 0x63825363u) {
        return 0;
    }
    parsed_t o;
    if (parse_options(in, len, &o) != 0) {
        return 0;
    }
    const uint8_t *mac = in + 28;
    uint32_t ciaddr = rd32(in + 12);

    switch (o.type) {
    case DHCP_DISCOVER: {
        int s = slot_for(p, mac, 1);
        return reply(p, in, DHCP_OFFER, p->first_ip + (uint32_t)s, 1, out, cap);
    }
    case DHCP_REQUEST: {
        if (o.has_server_id && o.server_id != p->server_ip) {
            return 0;  /* it chose another server */
        }
        int s;
        uint32_t want;
        if (o.has_server_id || (o.has_requested && !ciaddr)) {
            /* SELECTING, or INIT-REBOOT: the address it asks for */
            s = slot_for(p, mac, 1);
            want = o.has_requested ? o.requested : ciaddr;
            if (want != p->first_ip + (uint32_t)s) {
                return reply(p, in, DHCP_NAK, 0, 0, out, cap);
            }
        } else {
            /* RENEWING / REBINDING: only a lease of this generation */
            s = slot_for(p, mac, 0);
            if (s < 0 || ciaddr != p->first_ip + (uint32_t)s || p->leases[s].gen != p->generation) {
                if (s >= 0) {
                    p->leases[s].gen = 0;
                }
                return reply(p, in, DHCP_NAK, 0, 0, out, cap);
            }
        }
        p->leases[s].gen = p->generation;
        return reply(p, in, DHCP_ACK, p->first_ip + (uint32_t)s, 1, out, cap);
    }
    case DHCP_INFORM:
        return reply(p, in, DHCP_ACK, 0, 0, out, cap);
    case DHCP_RELEASE:
    case DHCP_DECLINE: {
        int s = slot_for(p, mac, 0);
        if (s >= 0) {
            p->leases[s].used = 0;
        }
        return 0;
    }
    default:
        return 0;
    }
}
