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
/* The network the S3 joined (0, 0: none): becomes option 121 on USB. */
void netsvc_set_wifi_net(uint32_t ip, uint32_t mask);

/* wifi_link.c */
typedef struct {
    bool connected;
    char ssid[33];
    int rssi;
    uint32_t ip, gw, mask;     /* host order */
    bool stump;                /* joined as an open Stump hotspot */
} link_status_t;

esp_netif_t *wifi_link_init(bool force_setup);   /* returns the AP netif */
void wifi_link_start(void);
void wifi_link_status(link_status_t *out);
bool adapter_setup_ap_open(void);
/* Saves a network (ssid 1-32 bytes, password empty or 8-63) and joins it. */
esp_err_t wifi_link_save(const char *ssid, const char *password);
esp_err_t wifi_link_forget(void);
/* BOOT pressed just after power-up: open the setup AP until a network is saved. */
void wifi_link_request_setup(void);
/* Nearby networks as a JSON array into buf; false if it doesn't fit. */
bool wifi_link_scan_json(char *buf, size_t cap);

/* web.c */
esp_err_t web_start(void);
