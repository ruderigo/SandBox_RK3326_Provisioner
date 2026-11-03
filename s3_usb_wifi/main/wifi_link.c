/*
 * The Wi-Fi side: joins the saved network by itself (credentials in NVS),
 * else an open hotspot that answers as a Stump (GET /node.json with an
 * "lxmf" key), and keeps at it. The setup AP, FireFly-S3-xxxx (open), opens
 * when there's nothing to join for a while, when no network is saved, or
 * when BOOT is pressed just after power-up.
 *
 * SPDX-License-Identifier: MIT
 */
#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "lwip/def.h"
#include "nvs.h"
#include "util_core.h"
#include "adapter.h"

static const char *TAG = "wifi_link";

#define BIT_IP      BIT0
#define BIT_DISC    BIT1
#define BIT_WAKE    BIT2      /* credentials changed, or setup asked for */

#define JOIN_SAVED_MS       20000
#define JOIN_OPEN_MS        12000
#define NO_LINK_SETUP_MS    120000
#define SETUP_CLOSE_MS      60000
#define BLOCK_MS            (5 * 60 * 1000)
#define SCAN_MAX            20

static EventGroupHandle_t s_ev;
static SemaphoreHandle_t s_lock;       /* status, credentials flags */
static SemaphoreHandle_t s_radio;      /* scanning and joining */
static esp_netif_t *s_sta, *s_ap;
static link_status_t s_status;
static bool s_setup_open, s_setup_by_button, s_saved_since_setup;
static volatile bool s_want_setup;
static char s_ap_ssid[16];

static wifi_ap_record_t s_scan[SCAN_MAX];
static uint16_t s_scan_n;
static int64_t s_scan_at;

static struct {
    uint8_t bssid[6];
    int64_t until;
} s_block[8];

static int64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

/* ---- credentials ---------------------------------------------------- */

static bool load_creds(char *ssid, char *pass)
{
    nvs_handle_t h;
    if (nvs_open("s3wifi", NVS_READONLY, &h) != ESP_OK) {
        return false;
    }
    size_t a = 33, b = 65;
    bool ok = nvs_get_str(h, "ssid", ssid, &a) == ESP_OK && ssid[0];
    if (ok && nvs_get_str(h, "pass", pass, &b) != ESP_OK) {
        pass[0] = 0;
    }
    nvs_close(h);
    return ok;
}

esp_err_t wifi_link_save(const char *ssid, const char *password)
{
    size_t sl = strlen(ssid), pl = strlen(password);
    if (sl < 1 || sl > 32 || (pl != 0 && (pl < 8 || pl > 63))) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t h;
    esp_err_t r = nvs_open("s3wifi", NVS_READWRITE, &h);
    if (r == ESP_OK) {
        r = nvs_set_str(h, "ssid", ssid);
        if (r == ESP_OK) {
            r = nvs_set_str(h, "pass", password);
        }
        if (r == ESP_OK) {
            r = nvs_commit(h);
        }
        nvs_close(h);
    }
    if (r == ESP_OK) {
        ESP_LOGI(TAG, "saved a network (%u-byte name)", (unsigned)sl);
        s_saved_since_setup = true;
        xEventGroupSetBits(s_ev, BIT_WAKE);
    }
    return r;
}

esp_err_t wifi_link_forget(void)
{
    nvs_handle_t h;
    esp_err_t r = nvs_open("s3wifi", NVS_READWRITE, &h);
    if (r == ESP_OK) {
        nvs_erase_all(h);
        r = nvs_commit(h);
        nvs_close(h);
    }
    xEventGroupSetBits(s_ev, BIT_WAKE);
    return r;
}

/* ---- status ----------------------------------------------------------- */

void wifi_link_status(link_status_t *out)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    *out = s_status;
    xSemaphoreGive(s_lock);
    if (out->connected) {
        wifi_ap_record_t ap;
        if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
            out->rssi = ap.rssi;
        }
    }
}

bool adapter_setup_ap_open(void)
{
    return s_setup_open;
}

static void set_status(bool connected, const char *ssid, bool stump)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (connected) {
        esp_netif_ip_info_t ip;
        esp_netif_get_ip_info(s_sta, &ip);
        s_status.connected = true;
        strlcpy(s_status.ssid, ssid, sizeof(s_status.ssid));
        s_status.ip = lwip_ntohl(ip.ip.addr);
        s_status.gw = lwip_ntohl(ip.gw.addr);
        s_status.mask = lwip_ntohl(ip.netmask.addr);
        s_status.stump = stump;
    } else {
        memset(&s_status, 0, sizeof(s_status));
    }
    xSemaphoreGive(s_lock);
    if (connected) {
        netsvc_set_wifi_net(s_status.ip, s_status.mask);
    } else {
        netsvc_set_wifi_net(0, 0);
    }
}

/* ---- events ----------------------------------------------------------- */

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_ev, BIT_IP);
        xEventGroupSetBits(s_ev, BIT_DISC);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_ev, BIT_IP);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
        xEventGroupClearBits(s_ev, BIT_IP);
        xEventGroupSetBits(s_ev, BIT_DISC);
    }
}

/* ---- the setup AP ----------------------------------------------------- */

static void setup_open(bool by_button)
{
    if (s_setup_open) {
        s_setup_by_button |= by_button;
        return;
    }
    wifi_config_t ap = {0};
    memcpy(ap.ap.ssid, s_ap_ssid, strlen(s_ap_ssid));
    ap.ap.ssid_len = (uint8_t)strlen(s_ap_ssid);
    ap.ap.authmode = WIFI_AUTH_OPEN;
    ap.ap.max_connection = 4;
    ap.ap.channel = 1;
    if (esp_wifi_set_mode(WIFI_MODE_APSTA) == ESP_OK && esp_wifi_set_config(WIFI_IF_AP, &ap) == ESP_OK) {
        s_setup_open = true;
        s_setup_by_button = by_button;
        s_saved_since_setup = false;
        ESP_LOGI(TAG, "setup AP %s open: http://10.77.1.1/", s_ap_ssid);
    }
}

static void setup_close(void)
{
    if (s_setup_open && esp_wifi_set_mode(WIFI_MODE_STA) == ESP_OK) {
        s_setup_open = false;
        ESP_LOGI(TAG, "setup AP closed");
    }
}

/* ---- joining ---------------------------------------------------------- */

static bool blocked(const uint8_t *bssid)
{
    int64_t t = now_ms();
    for (int i = 0; i < 8; i++) {
        if (s_block[i].until > t && memcmp(s_block[i].bssid, bssid, 6) == 0) {
            return true;
        }
    }
    return false;
}

static void block(const uint8_t *bssid)
{
    int oldest = 0;
    for (int i = 1; i < 8; i++) {
        if (s_block[i].until < s_block[oldest].until) {
            oldest = i;
        }
    }
    memcpy(s_block[oldest].bssid, bssid, 6);
    s_block[oldest].until = now_ms() + BLOCK_MS;
}

static void leave(void)
{
    wifi_ap_record_t ap;
    bool associated = esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
    xEventGroupClearBits(s_ev, BIT_DISC);
    if (esp_wifi_disconnect() == ESP_OK && associated) {
        xEventGroupWaitBits(s_ev, BIT_DISC, pdTRUE, pdFALSE, pdMS_TO_TICKS(2000));
    }
    vTaskDelay(pdMS_TO_TICKS(200));   /* a late event from an attempt cut short */
    xEventGroupClearBits(s_ev, BIT_IP | BIT_DISC);
}

/* Joins; true once it has an address. bssid pins one AP (may be NULL). */
static bool join(const char *ssid, const char *pass, const uint8_t *bssid, int timeout_ms)
{
    leave();
    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, ssid, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, pass, sizeof(wc.sta.password));
    wc.sta.threshold.authmode = pass[0] ? WIFI_AUTH_WPA_PSK : WIFI_AUTH_OPEN;
    wc.sta.pmf_cfg.capable = true;
    wc.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    wc.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
    if (bssid) {
        wc.sta.bssid_set = true;
        memcpy(wc.sta.bssid, bssid, 6);
    }
    if (esp_wifi_set_config(WIFI_IF_STA, &wc) != ESP_OK || esp_wifi_connect() != ESP_OK) {
        return false;
    }
    EventBits_t b = xEventGroupWaitBits(s_ev, BIT_IP | BIT_DISC | BIT_WAKE, pdFALSE, pdFALSE,
                                        pdMS_TO_TICKS(timeout_ms));
    if (b & BIT_IP) {
        return true;
    }
    leave();
    return false;
}

/* Is the gateway a Stump? GET http://<gateway>/node.json, "lxmf" in it. */
static bool probe_stump(void)
{
    esp_netif_ip_info_t ip;
    if (esp_netif_get_ip_info(s_sta, &ip) != ESP_OK || ip.gw.addr == 0) {
        return false;
    }
    char url[40];
    snprintf(url, sizeof(url), "http://" IPSTR "/node.json", IP2STR(&ip.gw));
    esp_http_client_config_t cfg = {.url = url, .timeout_ms = 4000, .disable_auto_redirect = true};
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (!c) {
        return false;
    }
    static char body[2048];
    bool ok = false;
    if (esp_http_client_open(c, 0) == ESP_OK) {
        esp_http_client_fetch_headers(c);
        if (esp_http_client_get_status_code(c) == 200) {
            int n = 0, r;
            while (n < (int)sizeof(body) && (r = esp_http_client_read(c, body + n, sizeof(body) - n)) > 0) {
                n += r;
            }
            ok = node_json_is_stump(body, (size_t)n);
        }
    }
    esp_http_client_cleanup(c);
    ESP_LOGI(TAG, "%s: %s", url, ok ? "a Stump" : "not a Stump");
    return ok;
}

static void scan_locked(void)
{
    wifi_scan_config_t sc = {.show_hidden = false};
    if (esp_wifi_scan_start(&sc, true) != ESP_OK) {
        return;
    }
    uint16_t n = SCAN_MAX;
    if (esp_wifi_scan_get_ap_records(&n, s_scan) == ESP_OK) {
        s_scan_n = n;
        s_scan_at = now_ms();
    }
}

/* Connected: stays until the link drops or something changes. */
static void hold(const char *ssid, bool stump)
{
    set_status(true, ssid, stump);
    ESP_LOGI(TAG, "joined %s%s", stump ? "a Stump's hotspot " : "", ssid);
    int64_t since = now_ms();
    for (;;) {
        if (s_want_setup) {
            s_want_setup = false;
            setup_open(true);
        }
        if (s_setup_open && (!s_setup_by_button || s_saved_since_setup)
                && now_ms() - since > SETUP_CLOSE_MS) {
            setup_close();
        }
        EventBits_t b = xEventGroupWaitBits(s_ev, BIT_DISC | BIT_WAKE, pdFALSE, pdFALSE, pdMS_TO_TICKS(1000));
        if (b & BIT_WAKE) {
            if (s_want_setup) {
                xEventGroupClearBits(s_ev, BIT_WAKE);
                continue;
            }
            xEventGroupClearBits(s_ev, BIT_WAKE);
            ESP_LOGI(TAG, "credentials changed: leaving %s", ssid);
            leave();
            break;
        }
        if (b & BIT_DISC) {
            ESP_LOGI(TAG, "lost %s", ssid);
            break;
        }
    }
    set_status(false, "", false);
}

static void link_task(void *arg)
{
    static char ssid[33], pass[65];
    int64_t last_link = now_ms();
    for (;;) {
        if (s_want_setup) {
            s_want_setup = false;
            setup_open(true);
        }
        xEventGroupClearBits(s_ev, BIT_WAKE);
        bool saved = load_creds(ssid, pass);
        if (!saved && !s_setup_open) {
            setup_open(false);   /* nothing saved: offer the setup page */
        }
        bool joined = false;
        xSemaphoreTake(s_radio, portMAX_DELAY);
        if (saved && join(ssid, pass, NULL, JOIN_SAVED_MS)) {
            xSemaphoreGive(s_radio);
            hold(ssid, false);
            joined = true;
        } else if (!(xEventGroupGetBits(s_ev) & BIT_WAKE)) {
            /* auto-join: open hotspots that answer as a Stump, strongest first */
            scan_locked();
            wifi_ap_record_t cand[SCAN_MAX];
            uint16_t nc = 0;
            for (uint16_t i = 0; i < s_scan_n; i++) {
                if (s_scan[i].authmode == WIFI_AUTH_OPEN && s_scan[i].ssid[0]
                        && strcmp((char *)s_scan[i].ssid, s_ap_ssid) != 0 && !blocked(s_scan[i].bssid)) {
                    cand[nc++] = s_scan[i];   /* already sorted by RSSI */
                }
            }
            for (uint16_t i = 0; i < nc && !joined; i++) {
                if (xEventGroupGetBits(s_ev) & BIT_WAKE) {
                    break;
                }
                const char *cs = (const char *)cand[i].ssid;
                if (join(cs, "", cand[i].bssid, JOIN_OPEN_MS) && probe_stump()) {
                    xSemaphoreGive(s_radio);
                    hold(cs, true);
                    joined = true;
                } else {
                    leave();
                    block(cand[i].bssid);
                }
            }
            if (!joined) {
                xSemaphoreGive(s_radio);
            }
        } else {
            xSemaphoreGive(s_radio);
        }
        if (joined) {
            last_link = now_ms();
            continue;
        }
        if (!s_setup_open && now_ms() - last_link > NO_LINK_SETUP_MS) {
            setup_open(false);
        }
        xEventGroupWaitBits(s_ev, BIT_WAKE, pdFALSE, pdFALSE, pdMS_TO_TICKS(10000));
    }
}

/* ---- the setup page's list -------------------------------------------- */

bool wifi_link_scan_json(char *buf, size_t cap)
{
    if (xSemaphoreTake(s_radio, 0) == pdTRUE) {
        if (now_ms() - s_scan_at > 10000 || s_scan_n == 0) {
            scan_locked();
        }
        xSemaphoreGive(s_radio);
    }
    /* else: it's joining; the last list will do */
    snprintf(buf, cap, "[");
    bool first = true;
    for (uint16_t i = 0; i < s_scan_n; i++) {
        const char *ss = (const char *)s_scan[i].ssid;
        if (!ss[0] || strcmp(ss, s_ap_ssid) == 0) {
            continue;
        }
        bool dup = false;
        for (uint16_t j = 0; j < i && !dup; j++) {
            dup = strcmp(ss, (const char *)s_scan[j].ssid) == 0;
        }
        if (dup) {
            continue;
        }
        size_t at = strlen(buf);
        if (at + 8 >= cap) {
            return false;
        }
        strcat(buf, first ? "{\"ssid\":" : ",{\"ssid\":");
        if (!json_put_str(buf, cap, ss)) {
            buf[at] = 0;
            return false;
        }
        size_t l = strlen(buf);
        int w = snprintf(buf + l, cap - l, ",\"rssi\":%d,\"open\":%s}", s_scan[i].rssi,
                         s_scan[i].authmode == WIFI_AUTH_OPEN ? "true" : "false");
        if (w < 0 || (size_t)w >= cap - l) {
            buf[at] = 0;
            return false;
        }
        first = false;
    }
    size_t l = strlen(buf);
    if (l + 2 > cap) {
        return false;
    }
    strcat(buf, "]");
    return true;
}

/* ---- start ------------------------------------------------------------ */

esp_netif_t *wifi_link_init(bool force_setup)
{
    s_ev = xEventGroupCreate();
    s_lock = xSemaphoreCreateMutex();
    s_radio = xSemaphoreCreateMutex();

    s_sta = esp_netif_create_default_wifi_sta();

    /* the setup AP at 10.77.1.1, without the IDF's DHCP server (ours runs) */
    static esp_netif_ip_info_t ap_ip;
    ap_ip.ip.addr = ESP_IP4TOADDR(10, 77, 1, 1);
    ap_ip.gw.addr = ESP_IP4TOADDR(10, 77, 1, 1);
    ap_ip.netmask.addr = ESP_IP4TOADDR(255, 255, 255, 0);
    esp_netif_inherent_config_t ap_cfg = ESP_NETIF_INHERENT_DEFAULT_WIFI_AP();
    ap_cfg.flags = ESP_NETIF_FLAG_AUTOUP;
    ap_cfg.ip_info = &ap_ip;
    s_ap = esp_netif_create_wifi(WIFI_IF_AP, &ap_cfg);
    ESP_ERROR_CHECK(esp_wifi_set_default_wifi_ap_handlers());

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));   /* our NVS keys hold the network */
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));

    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    setup_ssid(mac, s_ap_ssid);
    s_want_setup = force_setup;
    return s_ap;
}

void wifi_link_start(void)
{
    ESP_ERROR_CHECK(esp_wifi_start());
    xTaskCreate(link_task, "wifi_link", 6144, NULL, 5, NULL);
}

void wifi_link_request_setup(void)
{
    s_want_setup = true;
    xEventGroupSetBits(s_ev, BIT_WAKE);
}
