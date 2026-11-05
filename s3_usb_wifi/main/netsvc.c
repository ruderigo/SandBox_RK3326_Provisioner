/*
 * The setup AP's small network services, on lwIP's raw UDP API (they run in
 * the TCP/IP thread): DHCP for the phones that join it (router and DNS
 * 10.77.1.1, so they show the setup page) and a captive DNS answering every
 * name with 10.77.1.1. Nothing else in the S3 has an address: the handheld's
 * side is a bridge (usb_net.c).
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
#include "dhcp_core.h"
#include "util_core.h"
#include "adapter.h"

static const char *TAG = "netsvc";

static struct netif *s_ap_if;
static dhcp_pool_t s_ap_pool;
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
    if (!in || in != s_ap_if) {
        return;
    }
    size_t m = dhcp_handle(&s_ap_pool, s_in, n, s_out, sizeof(s_out));
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
        return;
    }
    size_t m = dns_captive_reply(s_in, n, ADAPTER_AP_IP, s_out, sizeof(s_out));
    if (m) {
        send_on(pcb, in, addr, port, s_out, m);
    }
}

static esp_err_t start_in_tcpip(void *ctx)
{
    s_ap_if = esp_netif_get_netif_impl((esp_netif_t *)ctx);
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

esp_err_t netsvc_start(esp_netif_t *ap)
{
    esp_err_t r = esp_netif_tcpip_exec(start_in_tcpip, ap);
    if (r == ESP_OK) {
        ESP_LOGI(TAG, "the setup AP's DHCP and captive DNS (10.77.1.1)");
    }
    return r;
}
