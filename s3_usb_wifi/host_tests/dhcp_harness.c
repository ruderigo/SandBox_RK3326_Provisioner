/*
 * The firmware's DHCP core on a Linux interface, for testing it against
 * real DHCP clients (see dhcp_clients.sh). Serves the USB pool on IFACE:
 * 10.77.0.2, 60 s leases, no router, no DNS. Signals change what the
 * "S3" has joined: SIGUSR1 192.168.4.0/24, SIGUSR2 192.168.50.0/24,
 * SIGHUP none (each becomes option 121 via 10.77.0.1).
 *
 *   dhcp_harness IFACE
 *
 * SPDX-License-Identifier: MIT
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <net/if.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include "dhcp_core.h"

#define IP(a, b, c, d) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (uint32_t)(d))

static volatile sig_atomic_t s_want = -1;

static void on_sig(int s)
{
    s_want = s == SIGUSR1 ? 1 : s == SIGUSR2 ? 2 : 0;
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s IFACE\n", argv[0]);
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
    struct sigaction sa = {.sa_handler = on_sig};
    sigaction(SIGUSR1, &sa, NULL);
    sigaction(SIGUSR2, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);

    dhcp_pool_t pool;
    dhcp_pool_init(&pool, IP(10, 77, 0, 1), IP(255, 255, 255, 0), IP(10, 77, 0, 2), 1, 60);
    static const char *names[] = {"?", "DISCOVER", "OFFER", "REQUEST", "DECLINE", "ACK", "NAK", "RELEASE", "INFORM"};
    uint8_t in[1500], out[1024];
    printf("serving on %s\n", argv[1]);
    for (;;) {
        if (s_want >= 0) {
            dhcp_route_t r[1];
            uint8_t n = 0;
            if (s_want == 1) {
                r[0] = (dhcp_route_t){IP(192, 168, 4, 0), 24, IP(10, 77, 0, 1)};
                n = 1;
            } else if (s_want == 2) {
                r[0] = (dhcp_route_t){IP(192, 168, 50, 0), 24, IP(10, 77, 0, 1)};
                n = 1;
            }
            dhcp_pool_set_routes(&pool, r, n);
            printf("routes: %s (generation %u)\n",
                   s_want == 1 ? "192.168.4.0/24" : s_want == 2 ? "192.168.50.0/24" : "none",
                   (unsigned)pool.generation);
            s_want = -1;
        }
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
        printf("%s -> %s\n", names[qt > 0 && qt <= 8 ? qt : 0], m ? names[rt > 0 && rt <= 8 ? rt : 0] : "(nothing)");
        if (m) {
            /* as the firmware does (netsvc.c): unicast to ciaddr; broadcast if none, and NAKs */
            uint32_t uc = dhcp_reply_unicast_to(in, (size_t)n);
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
