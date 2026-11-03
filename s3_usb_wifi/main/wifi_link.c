/*
 * The Wi-Fi side. It remembers up to 8 networks (in NVS, most recent first)
 * and joins whichever of them is in range, else an open hotspot that answers
 * as a Stump (GET /node.json with an "lxmf" key), and keeps at it. A network
 * asked for (the Provisioner's Wi-Fi page, the setup page) is tried first,
 * and why it failed is kept for the asker.
 *
 * The setup AP, FireFly-S3-xxxx (open), opens when nothing is saved, after
 * a while with no network, or when BOOT is pressed just after power-up.
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
#define BIT_WAKE    BIT2      /* a join asked for, a network forgotten, or setup asked for */

#define JOIN_MS             20000
#define JOIN_OPEN_MS        12000
#define NO_LINK_SETUP_MS    120000
#define SETUP_CLOSE_MS      60000
#define BLOCK_MS            (5 * 60 * 1000)
#define SCAN_MAX            24

static EventGroupHandle_t s_ev;
static SemaphoreHandle_t s_lock;       /* s_status, s_nets, s_req */
static SemaphoreHandle_t s_radio;      /* scanning and joining */
static esp_netif_t *s_sta, *s_ap;
static link_status_t s_status;
static netlist_t s_nets;
static char s_req[33];                 /* the network asked for, tried first */
static volatile uint8_t s_reason;      /* the last disconnect's reason */
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

/* ---- the saved networks ------------------------------------------------ */

static void nets_load(void)
{
    nvs_handle_t h;
    memset(&s_nets, 0, sizeof(s_nets));
    if (nvs_open("s3wifi", NVS_READWRITE, &h) != ESP_OK) {
        return;
    }
    size_t len = sizeof(s_nets);
    if (nvs_get_blob(h, "nets", &s_nets, &len) != ESP_OK || len != sizeof(s_nets) || !netlist_sane(&s_nets)) {
        memset(&s_nets, 0, sizeof(s_nets));
        /* 0.1.0 kept one network as "ssid" / "pass" */
        char ssid[33], pass[65];
        size_t a = sizeof(ssid), b = sizeof(pass);
        if (nvs_get_str(h, "ssid", ssid, &a) == ESP_OK) {
            if (nvs_get_str(h, "pass", pass, &b) != ESP_OK) {
                pass[0] = 0;
            }
            netlist_put(&s_nets, ssid, pass);
            nvs_set_blob(h, "nets", &s_nets, sizeof(s_nets));
            nvs_erase_key(h, "ssid");
            nvs_erase_key(h, "pass");
            nvs_commit(h);
        }
    }
    nvs_close(h);
}

/* with s_lock held */
static esp_err_t nets_store(void)
{
    nvs_handle_t h;
    esp_err_t r = nvs_open("s3wifi", NVS_READWRITE, &h);
    if (r == ESP_OK) {
        r = nvs_set_blob(h, "nets", &s_nets, sizeof(s_nets));
        if (r == ESP_OK) {
            r = nvs_commit(h);
        }
        nvs_close(h);
    }
    return r;
}

esp_err_t wifi_link_join(const char *ssid, const char *password)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    netlist_t was = s_nets;
    if (!netlist_put(&s_nets, ssid, password)) {
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_ARG;
    }
    esp_err_t r = nets_store();
    if (r != ESP_OK) {
        s_nets = was;
    } else {
        strlcpy(s_req, ssid, sizeof(s_req));
        s_status.error = NULL;
        s_status.state = LINK_JOINING;
        strlcpy(s_status.target, ssid, sizeof(s_status.target));
    }
    xSemaphoreGive(s_lock);
    if (r == ESP_OK) {
        ESP_LOGI(TAG, "asked to join a network (%u-byte name)", (unsigned)strlen(ssid));
        s_saved_since_setup = true;
        xEventGroupSetBits(s_ev, BIT_WAKE);
    }
    return r;
}

esp_err_t wifi_link_forget(const char *ssid)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    esp_err_t r = ESP_OK;
    if (ssid) {
        if (!netlist_remove(&s_nets, ssid)) {
            r = ESP_ERR_NOT_FOUND;
        }
    } else {
        memset(&s_nets, 0, sizeof(s_nets));
    }
    if (r == ESP_OK) {
        r = nets_store();
    }
    xSemaphoreGive(s_lock);
    xEventGroupSetBits(s_ev, BIT_WAKE);
    return r;
}

static bool is_saved(const char *ssid)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    bool yes = netlist_find(&s_nets, ssid) >= 0;
    xSemaphoreGive(s_lock);
    return yes;
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

static void set_joining(const char *ssid)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_status.state = LINK_JOINING;
    strlcpy(s_status.target, ssid, sizeof(s_status.target));
    xSemaphoreGive(s_lock);
}

static void set_failed(const char *ssid, const char *why, bool asked)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_status.state = LINK_IDLE;
    if (asked) {
        strlcpy(s_status.target, ssid, sizeof(s_status.target));
        s_status.error = why;
    }
    xSemaphoreGive(s_lock);
}

static void set_connected(bool connected, const char *ssid, bool stump)
{
    uint32_t dns = 0;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (connected) {
        esp_netif_ip_info_t info;
        esp_netif_dns_info_t d = {0};
        esp_netif_get_ip_info(s_sta, &info);
        esp_netif_get_dns_info(s_sta, ESP_NETIF_DNS_MAIN, &d);
        s_status.state = LINK_CONNECTED;
        s_status.connected = true;
        s_status.error = NULL;
        strlcpy(s_status.ssid, ssid, sizeof(s_status.ssid));
        strlcpy(s_status.target, ssid, sizeof(s_status.target));
        s_status.ip = lwip_ntohl(info.ip.addr);
        s_status.gw = lwip_ntohl(info.gw.addr);
        s_status.mask = lwip_ntohl(info.netmask.addr);
        s_status.dns = dns = lwip_ntohl(d.ip.u_addr.ip4.addr);
        if (!dns) {
            dns = s_status.gw;   /* no DNS given: most gateways answer one */
        }
        s_status.stump = stump;
    } else {
        const char *err = s_status.error;
        char target[33];
        strlcpy(target, s_status.target, sizeof(target));
        memset(&s_status, 0, sizeof(s_status));
        s_status.state = LINK_IDLE;
        s_status.error = err;
        strlcpy(s_status.target, target, sizeof(s_status.target));
    }
    xSemaphoreGive(s_lock);
    netsvc_set_upstream_dns(dns);
}

/* Why a join failed, in a word the Provisioner shows. */
static const char *reason_word(uint8_t r)
{
    switch (r) {
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_MIC_FAILURE:
    case WIFI_REASON_AUTH_EXPIRE:
        return "wrong_password";
    case WIFI_REASON_NO_AP_FOUND:
    case WIFI_REASON_NO_AP_FOUND_IN_RSSI_THRESHOLD:
        return "not_found";
    case WIFI_REASON_NO_AP_FOUND_W_COMPATIBLE_SECURITY:
    case WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD:
        return "security_mismatch";
    case 0:
        return "no_address";   /* associated, but no DHCP answer */
    default:
        return "failed";
    }
}

/* ---- events ----------------------------------------------------------- */

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_reason = ((wifi_event_sta_disconnected_t *)data)->reason;
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

/* Joins; true once it has an address. bssid pins one AP (may be NULL).
 * On failure, *why says why (may be NULL). */
static bool join(const char *ssid, const char *pass, const uint8_t *bssid, int timeout_ms, const char **why)
{
    leave();
    set_joining(ssid);
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
    s_reason = 0;
    if (esp_wifi_set_config(WIFI_IF_STA, &wc) != ESP_OK || esp_wifi_connect() != ESP_OK) {
        if (why) {
            *why = "failed";
        }
        return false;
    }
    EventBits_t b = xEventGroupWaitBits(s_ev, BIT_IP | BIT_DISC | BIT_WAKE, pdFALSE, pdFALSE,
                                        pdMS_TO_TICKS(timeout_ms));
    if (b & BIT_IP) {
        return true;
    }
    if (why) {
        if (b & BIT_DISC) {
            *why = reason_word(s_reason);
        } else if (b & BIT_WAKE) {
            *why = NULL;   /* cut short: something else was asked for */
        } else {
            *why = s_reason ? reason_word(s_reason) : "no_address";
        }
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

static bool in_scan(const char *ssid)
{
    for (uint16_t i = 0; i < s_scan_n; i++) {
        if (strcmp((const char *)s_scan[i].ssid, ssid) == 0) {
            return true;
        }
    }
    return false;
}

/* Connected: stays until the link drops, another network is asked for, or
 * this one is forgotten. */
static void hold(const char *ssid, bool stump)
{
    set_connected(true, ssid, stump);
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
            xEventGroupClearBits(s_ev, BIT_WAKE);
            xSemaphoreTake(s_lock, portMAX_DELAY);
            bool asked = s_req[0] != 0;
            xSemaphoreGive(s_lock);
            if (asked || (!stump && !is_saved(ssid))) {
                ESP_LOGI(TAG, "leaving %s (%s)", ssid, asked ? "another network asked for" : "forgotten");
                leave();
                break;
            }
            continue;   /* setup asked for, or another network forgotten */
        }
        if (b & BIT_DISC) {
            ESP_LOGI(TAG, "lost %s", ssid);
            break;
        }
    }
    set_connected(false, "", false);
}

static void link_task(void *arg)
{
    static netlist_t nets;
    static char req[33];
    int64_t last_link = now_ms();
    for (;;) {
        if (s_want_setup) {
            s_want_setup = false;
            setup_open(true);
        }
        xEventGroupClearBits(s_ev, BIT_WAKE);
        xSemaphoreTake(s_lock, portMAX_DELAY);
        nets = s_nets;
        strlcpy(req, s_req, sizeof(req));
        s_req[0] = 0;
        xSemaphoreGive(s_lock);
        if (nets.n == 0 && !s_setup_open) {
            setup_open(false);   /* nothing saved: offer the setup page */
        }

        bool joined = false;
        xSemaphoreTake(s_radio, portMAX_DELAY);
        scan_locked();

        /* the network asked for (even if the scan missed it), then the saved
         * ones in range, most recent first */
        for (int i = -1; i < nets.n && !joined; i++) {
            const char *ss = i < 0 ? req : nets.e[i].ssid;
            if (!ss[0] || (i >= 0 && (strcmp(ss, req) == 0 || !in_scan(ss)))) {
                continue;
            }
            int k = netlist_find(&nets, ss);
            const char *pw = k >= 0 ? nets.e[k].pass : "";
            const char *why = NULL;
            if (join(ss, pw, NULL, JOIN_MS, &why)) {
                xSemaphoreGive(s_radio);
                hold(ss, false);
                joined = true;
            } else {
                if (!why) {
                    break;   /* cut short by a new request: start over */
                }
                ESP_LOGI(TAG, "couldn't join %s: %s", ss, why);
                set_failed(ss, why, i < 0);
                if (xEventGroupGetBits(s_ev) & BIT_WAKE) {
                    break;
                }
            }
        }

        /* else: open hotspots that answer as a Stump, strongest first */
        if (!joined && !(xEventGroupGetBits(s_ev) & BIT_WAKE)) {
            wifi_ap_record_t cand[SCAN_MAX];
            uint16_t nc = 0;
            for (uint16_t i = 0; i < s_scan_n; i++) {
                const char *ss = (const char *)s_scan[i].ssid;
                if (s_scan[i].authmode == WIFI_AUTH_OPEN && ss[0] && strcmp(ss, s_ap_ssid) != 0
                        && netlist_find(&nets, ss) < 0 && !blocked(s_scan[i].bssid)) {
                    cand[nc++] = s_scan[i];   /* already sorted by RSSI */
                }
            }
            for (uint16_t i = 0; i < nc && !joined; i++) {
                if (xEventGroupGetBits(s_ev) & BIT_WAKE) {
                    break;
                }
                const char *cs = (const char *)cand[i].ssid;
                if (join(cs, "", cand[i].bssid, JOIN_OPEN_MS, NULL) && probe_stump()) {
                    xSemaphoreGive(s_radio);
                    hold(cs, true);
                    joined = true;
                } else {
                    leave();
                    block(cand[i].bssid);
                    set_failed(cs, NULL, false);
                }
            }
        }
        if (!joined) {
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

/* ---- lists for the pages ---------------------------------------------- */

bool wifi_link_scan_json(char *buf, size_t cap)
{
    if (xSemaphoreTake(s_radio, 0) == pdTRUE) {
        if (now_ms() - s_scan_at > 8000 || s_scan_n == 0) {
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
        int w = snprintf(buf + l, cap - l, ",\"rssi\":%d,\"open\":%s,\"saved\":%s}", s_scan[i].rssi,
                         s_scan[i].authmode == WIFI_AUTH_OPEN ? "true" : "false",
                         is_saved(ss) ? "true" : "false");
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

bool wifi_link_saved_json(char *buf, size_t cap)
{
    bool ok = true;
    snprintf(buf, cap, "[");
    xSemaphoreTake(s_lock, portMAX_DELAY);
    for (int i = 0; i < s_nets.n && ok; i++) {
        if (i && strlen(buf) + 2 < cap) {
            strcat(buf, ",");
        }
        ok = json_put_str(buf, cap, s_nets.e[i].ssid);
    }
    xSemaphoreGive(s_lock);
    if (!ok || strlen(buf) + 2 > cap) {
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
    nets_load();
    ESP_LOGI(TAG, "%u saved network(s)", s_nets.n);

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
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));   /* our NVS keys hold the networks */
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
    xTaskCreate(link_task, "wifi_link", 8192, NULL, 5, NULL);
}

void wifi_link_request_setup(void)
{
    s_want_setup = true;
    xEventGroupSetBits(s_ev, BIT_WAKE);
}
