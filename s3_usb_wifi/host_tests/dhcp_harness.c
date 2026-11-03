/*
 * The firmware's DHCP core on a Linux interface, for testing it against
 * real DHCP clients (see dhcp_clients.sh). Serves the setup AP's pool on
 * IFACE as the firmware sets it up (netsvc.c): 10.77.1.2-9, the S3
 * (10.77.1.1) as router and DNS. LEASE_S defaults to the firmware's 120;
 * the tests use a short one to see renewals.
 *
 *   dhcp_harness IFACE [LEASE_S]
 *
 * SPDX-License-Identifier: MIT
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <net/if.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include "dhcp_core.h"

#define IP(a, b, c, d) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s IFACE [LEASE_S]\n", argv[0]);
        return 2;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &one, sizeof(one));
    if (setsockopt(fd, SOL_SOCKET, SO_BINDTODEVICE, argv[1], (socklen_t)strlen(argv[1])) != 0) {
        perror("SO_BINDTODEVICE");
        return 1;
    }
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(67), .sin_addr.s_addr = INADDR_ANY};
    if (bind(fd, (struct sockaddr *)&a, sizeof(a)) != 0) {
        perror("bind");
        return 1;
    }

    const uint32_t S = IP(10, 77, 1, 1);
    dhcp_pool_t pool;
    dhcp_pool_init(&pool, S, IP(255, 255, 255, 0), IP(10, 77, 1, 2), 8,
                   argc > 2 ? (uint32_t)atoi(argv[2]) : 120);
    pool.router = S;
    pool.dns = S;

    static const char *names[] = {"?", "DISCOVER", "OFFER", "REQUEST", "DECLINE", "ACK", "NAK", "RELEASE", "INFORM"};
    uint8_t in[1500], out[1024];
    printf("serving on %s\n", argv[1]);
    for (;;) {
        ssize_t n = recv(fd, in, sizeof(in), 0);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("recv");
            return 1;
        }
        size_t m = dhcp_handle(&pool, in, (size_t)n, out, sizeof(out));
        int qt = 0, rt = 0;
        for (size_t i = 240; i + 2 < (size_t)n && in[i] != 255; i += in[i] ? 2u + in[i + 1] : 1u) {
            if (in[i] == 53) { qt = in[i + 2]; break; }
        }
        for (size_t i = 240; m && i + 2 < m && out[i] != 255; i += out[i] ? 2u + out[i + 1] : 1u) {
            if (out[i] == 53) { rt = out[i + 2]; break; }
        }
        uint32_t uc = dhcp_reply_unicast_to(in, (size_t)n);
        printf("%s%s -> %s\n", names[qt > 0 && qt <= 8 ? qt : 0], uc ? " (renewing)" : "",
               m ? names[rt > 0 && rt <= 8 ? rt : 0] : "(nothing)");
        if (m) {
            /* as the firmware does (netsvc.c): unicast to ciaddr; broadcast if none, and NAKs */
            struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(68)};
            if (uc) {
                to.sin_addr.s_addr = htonl(uc);
                sendto(fd, out, m, 0, (struct sockaddr *)&to, sizeof(to));
            }
            if (!uc || rt == DHCP_NAK) {
                to.sin_addr.s_addr = INADDR_BROADCAST;
                sendto(fd, out, m, 0, (struct sockaddr *)&to, sizeof(to));
            }
        }
    }
}
