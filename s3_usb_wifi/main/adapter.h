/*
 * The firmware's parts, and the addresses they agree on.
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_netif.h"

/* host byte order */
#define ADAPTER_USB_IP      0x0A4D0001u   /* 10.77.0.1: the S3 on USB */
#define ADAPTER_USB_CLIENT  0x0A4D0002u   /* 10.77.0.2: the handheld */
#define ADAPTER_AP_IP       0x0A4D0101u   /* 10.77.1.1: the S3 on its setup AP */
#define ADAPTER_MASK24      0xFFFFFF00u

/* usb_net.c */
esp_netif_t *usb_net_start(void);
bool usb_net_mounted(void);

/* netsvc.c */
esp_err_t netsvc_start(esp_netif_t *usb, esp_netif_t *ap);
/* The joined network's DNS (0: none): where the handheld's DNS questions
 * to 10.77.0.1 go on to. */
void netsvc_set_upstream_dns(uint32_t dns);

/* wifi_link.c */
#define LINK_SAVED_MAX 8

typedef enum { LINK_IDLE, LINK_JOINING, LINK_CONNECTED } link_state_t;

typedef struct {
    link_state_t state;
    bool connected;
    char ssid[33];             /* connected to */
    char target[33];           /* joining (or last tried) */
    const char *error;         /* why the last asked-for join failed, or NULL */
    int rssi;
    uint32_t ip, gw, mask, dns;   /* host order */
    bool stump;                /* joined as an open Stump hotspot */
} link_status_t;

esp_netif_t *wifi_link_init(bool force_setup);   /* returns the AP netif */
void wifi_link_start(void);
void wifi_link_status(link_status_t *out);
bool adapter_setup_ap_open(void);
/* Remembers a network (ssid 1-32 bytes; password empty for open, else 8-63;
 * NULL keeps a saved one's) at the top of the list, and joins it now. */
esp_err_t wifi_link_join(const char *ssid, const char *password);
/* Forgets one network (ssid), or all (NULL). */
esp_err_t wifi_link_forget(const char *ssid);
/* BOOT pressed just after power-up: open the setup AP until a network is saved. */
void wifi_link_request_setup(void);
/* Nearby networks as a JSON array into buf; false if it doesn't fit. */
bool wifi_link_scan_json(char *buf, size_t cap);
/* The saved networks' names, most recent first, as a JSON array. */
bool wifi_link_saved_json(char *buf, size_t cap);

/* web.c */
esp_err_t web_start(void);
