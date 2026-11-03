/*
 * The small network services, on lwIP's raw UDP API (they run in the TCP/IP
 * thread): our own DHCP server for the USB side and the setup AP (the IDF
 * one can't leave out option 3 or send option 121), and a captive DNS for
 * the setup AP only. Each answers only on the interface it's for: nothing
 * is answered on the Wi-Fi the S3 joined.
 *
 * SPDX-License-Identifier: MIT
 */
#include <string.h>
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_net_stack.h"
#include "lwip/udp.h"
#include "lwip/ip.h"
#include "lwip/pbuf.h"
#include "lwip/def.h"
#include "lwip/prot/ip4.h"
#include "lwip_hooks.h"
#include "dhcp_core.h"
#include "util_core.h"
#include "adapter.h"

static const char *TAG = "netsvc";

static struct netif *s_usb_if, *s_ap_if;
static dhcp_pool_t s_usb_pool, s_ap_pool;
static struct udp_pcb *s_dhcp_pcb, *s_dns_pcb;
static uint8_t s_in[1024], s_out[1024];   /* used only in the TCP/IP thread */

static void send_on(struct udp_pcb *pcb, struct netif *nif, const ip_addr_t *to, u16_t port,
                    const uint8_t *data, size_t len)
{
    struct pbuf *q = pbuf_alloc(PBUF_TRANSPORT, (u16_t)len, PBUF_RAM);
    if (!q) {
        return;
    }
    memcpy(q->payload, data, len);
    udp_sendto_if(pcb, q, to, port, nif);
    pbuf_free(q);
}

static void on_dhcp(void *arg, struct udp_pcb *pcb, struct pbuf *p, const ip_addr_t *addr, u16_t port)
{
    struct netif *in = ip_current_input_netif();
    size_t n = pbuf_copy_partial(p, s_in, sizeof(s_in), 0);
    pbuf_free(p);
    dhcp_pool_t *pool = NULL;
    if (in && in == s_usb_if) {
        pool = &s_usb_pool;
    } else if (in && in == s_ap_if) {
        pool = &s_ap_pool;
    }
    if (!pool) {
        return;   /* the joined Wi-Fi's own DHCP traffic: not ours */
    }
    size_t m = dhcp_handle(pool, s_in, n, s_out, sizeof(s_out));
    if (!m) {
        return;
    }
    uint32_t uc = dhcp_reply_unicast_to(s_in, n);
    if (uc) {
        ip_addr_t to = IPADDR4_INIT(lwip_htonl(uc));
        send_on(pcb, in, &to, 68, s_out, m);
    }
    if (!uc || s_out[242] == DHCP_NAK) {   /* option 53 is always first: 240-242 */
        /* no address yet: broadcast (one hop). A NAK goes out both ways. */
        send_on(pcb, in, IP_ADDR_BROADCAST, 68, s_out, m);
    }
}

static void on_dns(void *arg, struct udp_pcb *pcb, struct pbuf *p, const ip_addr_t *addr, u16_t port)
{
    struct netif *in = ip_current_input_netif();
    size_t n = pbuf_copy_partial(p, s_in, sizeof(s_in), 0);
    pbuf_free(p);
    if (!in || in != s_ap_if || !adapter_setup_ap_open()) {
        return;   /* captive DNS on the setup AP only: no DNS for the USB side */
    }
    size_t m = dns_captive_reply(s_in, n, lwip_ntohl(ip4_addr_get_u32(netif_ip4_addr(s_ap_if))),
                                 s_out, sizeof(s_out));
    if (m) {
        send_on(pcb, in, addr, port, s_out, m);
    }
}

/*
 * What may come in where (the TCP/IP thread, before NAT looks at it):
 *  - 10.77.0.0/24 (the handheld, and the S3's own USB address with its
 *    setup page) only from USB: nothing on the joined Wi-Fi reaches them,
 *    even by routing through the S3;
 *  - 10.77.1.0/24 (the setup AP) only from the AP or USB;
 *  - from the setup AP, only the AP's own network and broadcasts (DHCP):
 *    phones on it are not forwarded anywhere.
 * Replies to the handheld's NATed traffic arrive addressed to the S3's
 * Wi-Fi address and pass; NAT then sends them on.
 */
int s3_ip4_input_filter(struct pbuf *p, struct netif *inp)
{
    if (p->len < IP_HLEN) {
        return 0;
    }
    const struct ip_hdr *h = (const struct ip_hdr *)p->payload;
    uint32_t dst = lwip_ntohl(h->dest.addr);
    bool to_usb_net = (dst & ADAPTER_MASK24) == (ADAPTER_USB_IP & ADAPTER_MASK24);
    bool to_ap_net = (dst & ADAPTER_MASK24) == (ADAPTER_AP_IP & ADAPTER_MASK24);
    bool from_usb = inp && inp == s_usb_if;
    bool from_ap = inp && inp == s_ap_if;
    bool drop = (to_usb_net && !from_usb)
                || (to_ap_net && !from_ap && !from_usb)
                || (from_ap && !to_ap_net && dst != 0xFFFFFFFFu);
    if (drop) {
        pbuf_free(p);
        return 1;
    }
    return 0;
}

typedef struct {
    esp_netif_t *usb, *ap;
} start_args_t;

static esp_err_t start_in_tcpip(void *ctx)
{
    start_args_t *a = ctx;
    s_usb_if = esp_netif_get_netif_impl(a->usb);
    s_ap_if = a->ap ? esp_netif_get_netif_impl(a->ap) : NULL;

    dhcp_pool_init(&s_usb_pool, ADAPTER_USB_IP, ADAPTER_MASK24, ADAPTER_USB_CLIENT, 1, 60);
    dhcp_pool_init(&s_ap_pool, ADAPTER_AP_IP, ADAPTER_MASK24, ADAPTER_AP_IP + 1, 8, 120);
    s_ap_pool.router = ADAPTER_AP_IP;   /* phones want both to show the setup page */
    s_ap_pool.dns = ADAPTER_AP_IP;

    s_dhcp_pcb = udp_new();
    s_dns_pcb = udp_new();
    if (!s_dhcp_pcb || !s_dns_pcb) {
        return ESP_ERR_NO_MEM;
    }
    ip_set_option(s_dhcp_pcb, SOF_BROADCAST);
    if (udp_bind(s_dhcp_pcb, IP4_ADDR_ANY, 67) != ERR_OK || udp_bind(s_dns_pcb, IP4_ADDR_ANY, 53) != ERR_OK) {
        return ESP_FAIL;
    }
    udp_recv(s_dhcp_pcb, on_dhcp, NULL);
    udp_recv(s_dns_pcb, on_dns, NULL);
    return ESP_OK;
}

esp_err_t netsvc_start(esp_netif_t *usb, esp_netif_t *ap)
{
    start_args_t a = {usb, ap};
    esp_err_t r = esp_netif_tcpip_exec(start_in_tcpip, &a);
    if (r == ESP_OK) {
        ESP_LOGI(TAG, "DHCP on usb (10.77.0.2, 60 s, no router, no DNS) and the setup AP");
    }
    return r;
}

typedef struct {
    dhcp_route_t routes[DHCP_MAX_ROUTES];
    uint8_t n;
} routes_args_t;

static esp_err_t routes_in_tcpip(void *ctx)
{
    routes_args_t *a = ctx;
    dhcp_pool_set_routes(&s_usb_pool, a->routes, a->n);
    return ESP_OK;
}

void netsvc_set_wifi_net(uint32_t ip, uint32_t mask)
{
    routes_args_t a = {0};
    if (ip && mask) {
        int prefix = dhcp_mask_prefix(mask);
        if (prefix <= 0) {
            ESP_LOGW(TAG, "odd netmask: no route sent");
        } else if (nets_overlap(ip, mask, ADAPTER_USB_IP, ADAPTER_MASK24)
                   || nets_overlap(ip, mask, ADAPTER_AP_IP, ADAPTER_MASK24)) {
            ESP_LOGW(TAG, "the Wi-Fi's network overlaps 10.77.0.0/23: no route sent");
        } else {
            a.routes[0] = (dhcp_route_t){ip & mask, (uint8_t)prefix, ADAPTER_USB_IP};
            a.n = 1;
        }
    }
    esp_netif_tcpip_exec(routes_in_tcpip, &a);
    char c[19];
    cidr_str(ip, mask, c);
    ESP_LOGI(TAG, "option 121: %s", a.n ? c : "(none)");
}
