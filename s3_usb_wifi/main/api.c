/*
 * What the S3 says about itself, the same on the setup page (HTTP, on its
 * setup AP) and on the control channel (the USB serial port).
 *
 * status: {"state": "idle"|"joining"|"connected", "ssid", "rssi", "channel",
 *          "target", "error", "mac", "link", "setup_ap", "frames": {...},
 *          "firmware"}
 *
 * SPDX-License-Identifier: MIT
 */
#include <stdio.h>
#include <string.h>
#include "esp_app_desc.h"
#include "esp_err.h"
#include "esp_mac.h"
#include "util_core.h"
#include "adapter.h"

static void put_opt_str(char *out, size_t cap, const char *key, const char *v)
{
    size_t l = strlen(out);
    snprintf(out + l, cap - l, ",\"%s\":", key);
    if (v && v[0]) {
        json_put_str(out, cap, v);
    } else {
        strlcat(out, "null", cap);
    }
}

bool api_status_json(char *out, size_t cap)
{
    static const char *states[] = {"idle", "joining", "connected"};
    link_status_t st;
    wifi_link_status(&st);
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    uint32_t tw, tu, dr;
    usb_net_counters(&tw, &tu, &dr);

    snprintf(out, cap, "{\"state\":\"%s\"", states[st.state]);
    put_opt_str(out, cap, "ssid", st.connected ? st.ssid : NULL);
    size_t l = strlen(out);
    if (st.connected) {
        snprintf(out + l, cap - l, ",\"rssi\":%d,\"channel\":%u", st.rssi, st.channel);
    } else {
        snprintf(out + l, cap - l, ",\"rssi\":null,\"channel\":null");
    }
    put_opt_str(out, cap, "target", st.target);
    put_opt_str(out, cap, "error", st.error);
    l = strlen(out);
    snprintf(out + l, cap - l,
             ",\"mac\":\"" MACSTR "\",\"link\":%s,\"usb\":%s,\"setup_ap\":%s,"
             "\"frames\":{\"to_wifi\":%lu,\"to_usb\":%lu,\"dropped\":%lu}",
             MAC2STR(mac), st.connected ? "true" : "false", usb_net_mounted() ? "true" : "false",
             adapter_setup_ap_open() ? "true" : "false",
             (unsigned long)tw, (unsigned long)tu, (unsigned long)dr);
    char fw[48];
    snprintf(fw, sizeof(fw), "s3-usb-wifi %s", esp_app_get_description()->version);
    put_opt_str(out, cap, "firmware", fw);
    if (strlen(out) + 2 >= cap) {
        return false;
    }
    strlcat(out, "}", cap);
    return true;
}

const char *api_join(const char *ssid, const char *password)
{
    esp_err_t r = wifi_link_join(ssid, password);
    if (r == ESP_ERR_INVALID_ARG) {
        size_t sl = strlen(ssid);
        return (sl < 1 || sl > 32) ? "bad_ssid" : "bad_password";
    }
    return r == ESP_OK ? NULL : "not_stored";
}

const char *api_forget(const char *ssid)
{
    esp_err_t r = wifi_link_forget(ssid);
    if (r == ESP_ERR_NOT_FOUND) {
        return "not_saved";
    }
    return r == ESP_OK ? NULL : "not_stored";
}
