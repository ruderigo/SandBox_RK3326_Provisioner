/*
 * The USB side: a CDC-NCM network device (TinyUSB, through esp_tinyusb)
 * wired to an esp_netif with a fixed address, 10.77.0.1/24.
 *
 * SPDX-License-Identifier: MIT
 */
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_check.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "tinyusb_net.h"
#include "adapter.h"

static const char *TAG = "usb_net";

typedef struct {
    esp_netif_driver_base_t base;
} usb_driver_t;

static usb_driver_t s_driver;
static esp_netif_t *s_netif;
static volatile bool s_mounted;

/* lwIP -> USB. The packet is copied into an NCM buffer before this returns. */
static esp_err_t usb_transmit(void *h, void *buffer, size_t len)
{
    if (len > 0xFFFF || !s_mounted) {
        return ESP_FAIL;
    }
    for (int tries = 0; tries < 4; tries++) {
        esp_err_t r = tinyusb_net_send_sync(buffer, (uint16_t)len, NULL, pdMS_TO_TICKS(20));
        if (r == ESP_OK) {
            return ESP_OK;
        }
        if (r == ESP_ERR_INVALID_STATE) {
            return ESP_FAIL;     /* not mounted: drop */
        }
        vTaskDelay(1);           /* the NCM buffers are busy: give the host a moment */
    }
    return ESP_FAIL;
}

static void usb_free_rx(void *h, void *buffer)
{
    free(buffer);
}

static void usb_free_tx(void *buffer, void *ctx)
{
    /* sync sends only: the buffer stays lwIP's */
}

/* USB -> lwIP. TinyUSB reuses its buffer when this returns, so copy it. */
static esp_err_t usb_recv(void *buffer, uint16_t len, void *ctx)
{
    if (!s_netif || len == 0) {
        return ESP_OK;
    }
    void *copy = malloc(len);
    if (!copy) {
        return ESP_ERR_NO_MEM;
    }
    memcpy(copy, buffer, len);
    return esp_netif_receive(s_netif, copy, len, NULL);
}

static esp_err_t usb_post_attach(esp_netif_t *netif, void *args)
{
    usb_driver_t *d = args;
    d->base.netif = netif;
    esp_netif_driver_ifconfig_t cfg = {
        .handle = d,
        .transmit = usb_transmit,
        .driver_free_rx_buffer = usb_free_rx,
    };
    return esp_netif_set_driver_config(netif, &cfg);
}

static void usb_event(tinyusb_event_t *event, void *arg)
{
    switch (event->id) {
    case TINYUSB_EVENT_ATTACHED:
        s_mounted = true;
        ESP_LOGI(TAG, "host attached");
        break;
    case TINYUSB_EVENT_DETACHED:
        s_mounted = false;
        ESP_LOGI(TAG, "host detached");
        break;
    default:
        break;
    }
}

esp_netif_t *usb_net_start(void)
{
    /* Two locally administered MACs from the chip's: ours, and the one
     * the host's interface takes (NCM's iMACAddress). */
    uint8_t base[6], dev_mac[6], host_mac[6];
    ESP_ERROR_CHECK(esp_read_mac(base, ESP_MAC_WIFI_STA));
    ESP_ERROR_CHECK(esp_derive_local_mac(dev_mac, base));
    memcpy(host_mac, dev_mac, 6);
    host_mac[5] ^= 0x01;

    esp_netif_ip_info_t ip = {
        .ip = {.addr = ESP_IP4TOADDR(10, 77, 0, 1)},
        .netmask = {.addr = ESP_IP4TOADDR(255, 255, 255, 0)},
        .gw = {.addr = 0},
    };
    esp_netif_inherent_config_t base_cfg = {
        .flags = ESP_NETIF_FLAG_AUTOUP,
        .ip_info = &ip,
        .if_key = "USB_NCM",
        .if_desc = "usb",
        .route_prio = 5,          /* never the default route: Wi-Fi is */
    };
    memcpy(base_cfg.mac, dev_mac, 6);
    esp_netif_config_t cfg = {
        .base = &base_cfg,
        .driver = NULL,
        .stack = ESP_NETIF_NETSTACK_DEFAULT_ETH,
    };
    s_netif = esp_netif_new(&cfg);
    assert(s_netif);
    s_driver.base.post_attach = usb_post_attach;
    ESP_ERROR_CHECK(esp_netif_attach(s_netif, &s_driver));
    esp_netif_action_start(s_netif, NULL, 0, NULL);
    esp_netif_action_connected(s_netif, NULL, 0, NULL);

    tinyusb_net_config_t ncfg = {
        .on_recv_callback = usb_recv,
        .free_tx_buffer = usb_free_tx,
        .user_context = NULL,
    };
    memcpy(ncfg.mac_addr, host_mac, 6);
    /* The driver first, then the NCM class: tinyusb_driver_install() resets
     * the string descriptors to its defaults, where the MAC string is empty,
     * and tinyusb_net_init() is what puts our host MAC there. With it empty,
     * Linux's cdc_ncm can't read the MAC and refuses the device ("bind()
     * failure", seen on the R36MAX's kernel 4.4). The host asks for that
     * string only after enumerating, long after this. */
    tinyusb_config_t tcfg = TINYUSB_DEFAULT_CONFIG(usb_event, NULL);
    ESP_ERROR_CHECK(tinyusb_driver_install(&tcfg));
    ESP_ERROR_CHECK(tinyusb_net_init(&ncfg));

    ESP_LOGI(TAG, "CDC-NCM up: S3 " MACSTR " at 10.77.0.1, host " MACSTR,
             MAC2STR(dev_mac), MAC2STR(host_mac));
    return s_netif;
}

bool usb_net_mounted(void)
{
    return s_mounted;
}
