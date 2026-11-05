/*
 * A small DHCP server core: no ESP-IDF or lwIP in here, so the host tests
 * build it with gcc. Addresses are uint32_t in host byte order.
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define DHCP_MAX_ROUTES 4
#define DHCP_MAX_LEASES 8

/* DHCP message types (option 53) */
enum {
    DHCP_DISCOVER = 1, DHCP_OFFER = 2, DHCP_REQUEST = 3, DHCP_DECLINE = 4,
    DHCP_ACK = 5, DHCP_NAK = 6, DHCP_RELEASE = 7, DHCP_INFORM = 8,
};

typedef struct {
    uint32_t net;     /* network address */
    uint8_t prefix;   /* 0..32 */
    uint32_t via;     /* router for that network */
} dhcp_route_t;

typedef struct {
    uint8_t mac[6];
    uint8_t used;
    uint32_t gen;     /* the pool's generation when this lease was last ACKed */
} dhcp_lease_t;

/*
 * One pool per interface. The USB side has one address (10.77.0.2), no
 * router (option 3), no DNS (option 6), and its routes as option 121.
 *
 * `generation` is bumped whenever what the pool hands out changes (the
 * routes): a client renewing a lease ACKed in an older generation gets a
 * NAK, so it starts over and takes the new options.
 */
typedef struct {
    uint32_t server_ip;
    uint32_t netmask;
    uint32_t first_ip;
    uint8_t pool_size;           /* 1..DHCP_MAX_LEASES */
    uint32_t lease_s;
    uint32_t router;             /* 0: option 3 not sent */
    uint32_t dns;                /* 0: option 6 not sent */
    dhcp_route_t routes[DHCP_MAX_ROUTES];
    uint8_t n_routes;            /* 0: option 121 not sent */
    uint32_t generation;
    dhcp_lease_t leases[DHCP_MAX_LEASES];
    uint8_t next;                /* next slot to reuse when all are taken */
} dhcp_pool_t;

/* Sets up a pool; leases cleared, generation 1. */
void dhcp_pool_init(dhcp_pool_t *p, uint32_t server_ip, uint32_t netmask,
                    uint32_t first_ip, uint8_t pool_size, uint32_t lease_s);

/* Replaces the routes (n may be 0) and bumps the generation if they changed. */
void dhcp_pool_set_routes(dhcp_pool_t *p, const dhcp_route_t *r, uint8_t n);

/*
 * Handles one client message (the UDP payload). Writes the reply into out
 * and returns its length, or 0 when nothing should be sent.
 */
size_t dhcp_handle(dhcp_pool_t *p, const uint8_t *in, size_t in_len,
                   uint8_t *out, size_t out_cap);

/*
 * Where the reply goes. A client with an address (ciaddr: renewing,
 * rebinding, INFORM) may only listen on it, so the reply is unicast there
 * (RFC 2131 4.1); a NAK also goes out as a broadcast. Returns ciaddr, or 0
 * for "broadcast only".
 */
uint32_t dhcp_reply_unicast_to(const uint8_t *in, size_t in_len);

/* Option 121's value (RFC 3442) for these routes; 0 if it doesn't fit. */
size_t dhcp_encode_routes(const dhcp_route_t *r, uint8_t n, uint8_t *out, size_t cap);

/* Prefix length of a contiguous netmask, or -1. */
int dhcp_mask_prefix(uint32_t mask);
