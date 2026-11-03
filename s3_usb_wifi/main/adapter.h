/*
 * The firmware's parts, and the addresses they agree on.
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_netif.h"

/* host byte order */
#define ADAPTER_AP_IP       0x0A4D0101u   /* 10.77.1.1: the S3 on its setup AP */
#define ADAPTER_MASK24      0xFFFFFF00u

/* usb_net.c: the network card, bridged to the joined Wi-Fi */
esp_err_t usb_net_start(void);
bool usb_net_mounted(void);
/* Frames cross (and the handheld sees its link up) only while on a network. */
void usb_net_set_bridge(bool on);
void usb_net_counters(uint32_t *to_wifi, uint32_t *to_usb, uint32_t *dropped);

/* ctl.c: the control channel on the USB serial port (the Provisioner's) */
esp_err_t ctl_start(void);

/* netsvc.c: DHCP and a captive DNS for the setup AP */
esp_err_t netsvc_start(esp_netif_t *ap);

/* wifi_link.c */
typedef enum { LINK_IDLE, LINK_JOINING, LINK_CONNECTED } link_state_t;

typedef struct {
    link_state_t state;
    bool connected;
    char ssid[33];             /* connected to */
    char target[33];           /* joining (or last tried) */
    const char *error;         /* why the last asked-for join failed, or NULL */
    int rssi;
    uint8_t channel;
} link_status_t;

esp_netif_t *wifi_link_init(bool force_setup);   /* returns the AP netif */
void wifi_link_start(void);
void wifi_link_status(link_status_t *out);
bool adapter_setup_ap_open(void);
/* Remembers a network (ssid 1-32 bytes; password empty for open, else 8-63;
 * NULL keeps a saved one's) at the top of the list, and joins it now. */
esp_err_t wifi_link_join(const char *ssid, const char *password);
/* Forgets one network (ssid), or all (NULL). ESP_ERR_NOT_FOUND if not saved. */
esp_err_t wifi_link_forget(const char *ssid);
/* BOOT pressed just after power-up: open the setup AP until a network is saved. */
void wifi_link_request_setup(void);
/* Nearby networks as a JSON array into buf; false if it doesn't fit. */
bool wifi_link_scan_json(char *buf, size_t cap);
/* The saved networks' names, most recent first, as a JSON array. */
bool wifi_link_saved_json(char *buf, size_t cap);

/* api.c: what the setup page and the control channel both say */
bool api_status_json(char *buf, size_t cap);
/* A join or forget, answered with an error word (NULL: done). */
const char *api_join(const char *ssid, const char *password);   /* password NULL: keep a saved one's */
const char *api_forget(const char *ssid);                       /* NULL: all */

/* web.c: the setup page, on the setup AP */
esp_err_t web_start(void);
