/*
 * The small network services, on lwIP's raw UDP API (they run in the TCP/IP
 * thread), each answering only on the interface it's for (nothing on the
 * Wi-Fi the S3 joined):
 *  - DHCP for the USB side: 10.77.0.2, the S3 (10.77.0.1) as its router and
 *    DNS, the default route in option 121 too. It never changes, whatever
 *    the S3 joins, so the handheld never has to be told anything new;
 *  - DNS for the USB side: a forwarder to the joined network's DNS
 *    (SERVFAIL while there's none);
 *  - DHCP and a captive DNS for the setup AP.
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
static struct udp_pcb *s_dhcp_pcb, *s_dns_pcb, *s_fwd_pcb;
static dnsfwd_t s_fwd;
static uint32_t s_upstream;   /* the joined network's DNS (host order), 0: none */
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
    if (in && in == s_usb_if) {
        /* the handheld's question: on to the joined network's DNS */
        uint32_t asker = lwip_ntohl(ip4_addr_get_u32(ip_2_ip4(addr)));
        if (s_upstream && dnsfwd_out(&s_fwd, s_in, n, asker, port)) {
            ip_addr_t up = IPADDR4_INIT(lwip_htonl(s_upstream));
            struct pbuf *q = pbuf_alloc(PBUF_TRANSPORT, (u16_t)n, PBUF_RAM);
            if (q) {
                memcpy(q->payload, s_in, n);
                udp_sendto(s_fwd_pcb, q, &up, 53);
                pbuf_free(q);
            }
        } else if (!s_upstream) {
            size_t m = dns_servfail(s_in, n, s_out, sizeof(s_out));
            if (m) {
                send_on(pcb, in, addr, port, s_out, m);
            }
        }
        return;
    }
    if (!in || in != s_ap_if || !adapter_setup_ap_open()) {
        return;   /* captive DNS on the setup AP only */
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

/* An answer from the joined network's DNS: back to the handheld. */
static void on_fwd(void *arg, struct udp_pcb *pcb, struct pbuf *p, const ip_addr_t *addr, u16_t port)
{
    size_t n = pbuf_copy_partial(p, s_in, sizeof(s_in), 0);
    pbuf_free(p);
    uint32_t from = lwip_ntohl(ip4_addr_get_u32(ip_2_ip4(addr)));
    uint32_t to;
    uint16_t to_port;
    if (port != 53 || from != s_upstream || !dnsfwd_in(&s_fwd, s_in, n, &to, &to_port)) {
        return;
    }
    ip_addr_t dst = IPADDR4_INIT(lwip_htonl(to));
    send_on(s_dns_pcb, s_usb_if, &dst, to_port, s_in, n);
}

typedef struct {
    esp_netif_t *usb, *ap;
} start_args_t;

static esp_err_t start_in_tcpip(void *ctx)
{
    start_args_t *a = ctx;
    s_usb_if = esp_netif_get_netif_impl(a->usb);
    s_ap_if = a->ap ? esp_netif_get_netif_impl(a->ap) : NULL;

    dhcp_pool_init(&s_usb_pool, ADAPTER_USB_IP, ADAPTER_MASK24, ADAPTER_USB_CLIENT, 1, 600);
    s_usb_pool.router = ADAPTER_USB_IP;   /* the S3 is the handheld's Wi-Fi card */
    s_usb_pool.dns = ADAPTER_USB_IP;
    dhcp_route_t def = {0, 0, ADAPTER_USB_IP};
    dhcp_pool_set_routes(&s_usb_pool, &def, 1);   /* a client taking 121 ignores option 3 */
    dhcp_pool_init(&s_ap_pool, ADAPTER_AP_IP, ADAPTER_MASK24, ADAPTER_AP_IP + 1, 8, 120);
    s_ap_pool.router = ADAPTER_AP_IP;   /* phones want both to show the setup page */
    s_ap_pool.dns = ADAPTER_AP_IP;

    s_dhcp_pcb = udp_new();
    s_dns_pcb = udp_new();
    s_fwd_pcb = udp_new();
    if (!s_dhcp_pcb || !s_dns_pcb || !s_fwd_pcb) {
        return ESP_ERR_NO_MEM;
    }
    ip_set_option(s_dhcp_pcb, SOF_BROADCAST);
    if (udp_bind(s_dhcp_pcb, IP4_ADDR_ANY, 67) != ERR_OK || udp_bind(s_dns_pcb, IP4_ADDR_ANY, 53) != ERR_OK
            || udp_bind(s_fwd_pcb, IP4_ADDR_ANY, 0) != ERR_OK) {
        return ESP_FAIL;
    }
    udp_recv(s_dhcp_pcb, on_dhcp, NULL);
    udp_recv(s_dns_pcb, on_dns, NULL);
    udp_recv(s_fwd_pcb, on_fwd, NULL);
    return ESP_OK;
}

esp_err_t netsvc_start(esp_netif_t *usb, esp_netif_t *ap)
{
    start_args_t a = {usb, ap};
    esp_err_t r = esp_netif_tcpip_exec(start_in_tcpip, &a);
    if (r == ESP_OK) {
        ESP_LOGI(TAG, "usb: 10.77.0.2, router and DNS 10.77.0.1; the setup AP served too");
    }
    return r;
}

static esp_err_t upstream_in_tcpip(void *ctx)
{
    s_upstream = *(uint32_t *)ctx;
    memset(&s_fwd, 0, sizeof(s_fwd));   /* questions to the old one are void */
    return ESP_OK;
}

void netsvc_set_upstream_dns(uint32_t dns)
{
    esp_netif_tcpip_exec(upstream_in_tcpip, &dns);
    char d[16];
    ip_str(dns, d);
    ESP_LOGI(TAG, "DNS for the handheld: %s", dns ? d : "none (SERVFAIL)");
}
