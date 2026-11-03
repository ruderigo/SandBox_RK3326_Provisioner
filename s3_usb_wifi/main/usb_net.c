/*
 * The USB side: a CDC-NCM network device bridged to the Wi-Fi the S3 joined.
 *
 * The handheld's interface takes the S3's own Wi-Fi station MAC, and frames
 * go across unchanged: USB -> esp_wifi_internal_tx(STA), Wi-Fi STA rx ->
 * USB. So the handheld is on the Wi-Fi itself: its address from the
 * network's DHCP, its broadcasts and multicasts (Reticulum, mDNS) reach the
 * others, and they reach it (SSH, a Stump's portal). The S3 has no address
 * on that network of its own. Wi-Fi allows one MAC per station, which is why
 * the handheld uses the S3's.
 *
 * The NCM link is "up" for the handheld only while the S3 is on a network:
 * joining one makes its network manager ask for an address there, leaving
 * one drops it.
 *
 * SPDX-License-Identifier: MIT
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_check.h"
#include "esp_wifi.h"
#include "esp_private/wifi.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "tinyusb_net.h"
#include "class/net/net_device.h"
#include "device/usbd_pvt.h"
#include "adapter.h"

static const char *TAG = "usb_net";

static volatile bool s_mounted;
static volatile bool s_bridging;     /* the S3 is on a network: frames cross */
static uint8_t s_mac[6];             /* the S3's station MAC = the handheld's */
static volatile uint32_t s_to_wifi, s_to_usb, s_dropped;
static bool s_warned_mac;

/* ---- Wi-Fi -> USB ------------------------------------------------------ */

static esp_err_t wifi_rx(void *buffer, uint16_t len, void *eb)
{
    if (!s_bridging || !s_mounted
            || tinyusb_net_send_sync(buffer, len, eb, pdMS_TO_TICKS(100)) != ESP_OK) {
        esp_wifi_internal_free_rx_buffer(eb);
        s_dropped++;
        return ESP_OK;
    }
    s_to_usb++;
    return ESP_OK;
}

/* TinyUSB copied a Wi-Fi frame into its buffer: give the frame back */
static void usb_tx_done(void *buff_free_arg, void *ctx)
{
    if (buff_free_arg) {
        esp_wifi_internal_free_rx_buffer(buff_free_arg);
    }
}

/* ---- USB -> Wi-Fi ------------------------------------------------------ */

static esp_err_t usb_rx(void *buffer, uint16_t len, void *ctx)
{
    if (!s_bridging || len < 14) {
        s_dropped++;
        return ESP_OK;
    }
    const uint8_t *f = buffer;
    if (memcmp(f + 6, s_mac, 6) != 0 && !s_warned_mac) {
        /* the access point only answers the S3's MAC */
        ESP_LOGW(TAG, "the handheld sends from " MACSTR ", not " MACSTR ": its replies won't come back",
                 MAC2STR(f + 6), MAC2STR(s_mac));
        s_warned_mac = true;
    }
    if (esp_wifi_internal_tx(WIFI_IF_STA, buffer, len) == ESP_OK) {
        s_to_wifi++;
    } else {
        s_dropped++;
    }
    return ESP_OK;
}

/* ---- the link the handheld sees ---------------------------------------- */

/* TinyUSB asks this when the host (re)configures the device. */
bool tud_network_default_link_state_cb(void)
{
    return s_bridging;
}

static void link_in_usb_task(void *arg)
{
    tud_network_link_state(0, arg != NULL);
}

void usb_net_set_bridge(bool on)
{
    if (on == s_bridging) {
        return;
    }
    if (on) {
        s_bridging = true;
        esp_wifi_internal_reg_rxcb(WIFI_IF_STA, wifi_rx);
    } else {
        esp_wifi_internal_reg_rxcb(WIFI_IF_STA, NULL);
        s_bridging = false;
    }
    usbd_defer_func(link_in_usb_task, on ? (void *)1 : NULL, false);
    ESP_LOGI(TAG, "link to the handheld %s", on ? "up: bridged to the Wi-Fi" : "down");
}

void usb_net_counters(uint32_t *to_wifi, uint32_t *to_usb, uint32_t *dropped)
{
    *to_wifi = s_to_wifi;
    *to_usb = s_to_usb;
    *dropped = s_dropped;
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

esp_err_t usb_net_start(void)
{
    ESP_RETURN_ON_ERROR(esp_read_mac(s_mac, ESP_MAC_WIFI_STA), TAG, "no MAC");

    tinyusb_net_config_t ncfg = {
        .on_recv_callback = usb_rx,
        .free_tx_buffer = usb_tx_done,
        .user_context = NULL,
    };
    memcpy(ncfg.mac_addr, s_mac, 6);
    /* The driver first, then the NCM class: tinyusb_driver_install() resets
     * the string descriptors to its defaults, where the MAC string is empty,
     * and tinyusb_net_init() is what puts the MAC there. With it empty,
     * Linux's cdc_ncm can't read the MAC and refuses the device ("bind()
     * failure", seen on the R36MAX's kernel 4.4). The host asks for that
     * string only after enumerating, long after this. */
    tinyusb_config_t tcfg = TINYUSB_DEFAULT_CONFIG(usb_event, NULL);
    ESP_RETURN_ON_ERROR(tinyusb_driver_install(&tcfg), TAG, "USB driver");
    ESP_RETURN_ON_ERROR(tinyusb_net_init(&ncfg), TAG, "NCM");
    ESP_LOGI(TAG, "CDC-NCM up: the handheld's interface is " MACSTR " (the S3's station MAC)", MAC2STR(s_mac));
    return ESP_OK;
}

bool usb_net_mounted(void)
{
    return s_mounted;
}
