/*
 * HTTP on port 80, for the USB side (10.77.0.1) and the setup AP
 * (10.77.1.1) only; the Wi-Fi the S3 joined gets a 403.
 *
 *   GET  /status.json   {"ssid","rssi","ip","gateway","subnet","firmware"}
 *   GET  /              the setup page
 *   GET  /scan.json     nearby networks
 *   POST /save          ssid=…&password=…   (form-encoded)
 *   POST /forget
 *
 * SPDX-License-Identifier: MIT
 */
#include <string.h>
#include <stdio.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include "esp_app_desc.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "lwip/def.h"
#include "util_core.h"
#include "adapter.h"

static const char *TAG = "web";

extern const char setup_html_start[] asm("_binary_setup_html_start");
extern const char setup_html_end[] asm("_binary_setup_html_end");

typedef enum { SIDE_USB, SIDE_AP, SIDE_OTHER } side_t;

/* Which address did the request come in on? */
static side_t side_of(httpd_req_t *req)
{
    struct sockaddr_storage ss;
    socklen_t len = sizeof(ss);
    int fd = httpd_req_to_sockfd(req);
    if (getsockname(fd, (struct sockaddr *)&ss, &len) != 0) {
        return SIDE_OTHER;
    }
    uint32_t a = 0;
    if (ss.ss_family == AF_INET) {
        a = lwip_ntohl(((struct sockaddr_in *)&ss)->sin_addr.s_addr);
#if CONFIG_LWIP_IPV6
    } else if (ss.ss_family == AF_INET6) {
        const uint8_t *b = ((struct sockaddr_in6 *)&ss)->sin6_addr.s6_addr;
        static const uint8_t mapped[12] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xFF, 0xFF};
        if (memcmp(b, mapped, 12) != 0) {
            return SIDE_OTHER;
        }
        a = ((uint32_t)b[12] << 24) | ((uint32_t)b[13] << 16) | ((uint32_t)b[14] << 8) | b[15];
#endif
    }
    if (a == ADAPTER_USB_IP) {
        return SIDE_USB;
    }
    if (a == ADAPTER_AP_IP && adapter_setup_ap_open()) {
        return SIDE_AP;
    }
    return SIDE_OTHER;
}

static esp_err_t refuse(httpd_req_t *req)
{
    httpd_resp_set_status(req, "403 Forbidden");
    return httpd_resp_sendstr(req, "Not on this network.\n");
}

static void nocache(httpd_req_t *req)
{
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
}

static esp_err_t status_get(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    link_status_t st;
    wifi_link_status(&st);
    char out[256] = "{\"ssid\":";
    char ip[16], gw[16], net[19];
    if (st.connected) {
        json_put_str(out, sizeof(out), st.ssid);
        ip_str(st.ip, ip);
        ip_str(st.gw, gw);
        cidr_str(st.ip, st.mask, net);
        size_t l = strlen(out);
        snprintf(out + l, sizeof(out) - l, ",\"rssi\":%d,\"ip\":\"%s\",\"gateway\":\"%s\",\"subnet\":\"%s\"",
                 st.rssi, ip, gw, net);
    } else {
        strlcat(out, "null,\"rssi\":null,\"ip\":null,\"gateway\":null,\"subnet\":null", sizeof(out));
    }
    strlcat(out, ",\"firmware\":", sizeof(out));
    char fw[48];
    snprintf(fw, sizeof(fw), "s3-usb-wifi %s", esp_app_get_description()->version);
    json_put_str(out, sizeof(out), fw);
    strlcat(out, "}\n", sizeof(out));
    httpd_resp_set_type(req, "application/json");
    nocache(req);
    return httpd_resp_sendstr(req, out);
}

static esp_err_t root_get(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    nocache(req);
    return httpd_resp_send(req, setup_html_start, setup_html_end - setup_html_start);
}

static esp_err_t scan_get(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    static char out[2048];   /* one request at a time: the server has one task */
    if (!wifi_link_scan_json(out, sizeof(out))) {
        /* the list was cut short; it's still valid JSON up to a point: close it */
        size_t l = strlen(out);
        while (l > 1 && out[l - 1] != '}') {
            out[--l] = 0;
        }
        strlcat(out, "]", sizeof(out));
        if (out[0] != '[') {
            strlcpy(out, "[]", sizeof(out));
        }
    }
    httpd_resp_set_type(req, "application/json");
    nocache(req);
    return httpd_resp_sendstr(req, out);
}

static int read_body(httpd_req_t *req, char *buf, size_t cap)
{
    if (req->content_len >= cap) {
        return -1;
    }
    size_t got = 0;
    while (got < req->content_len) {
        int r = httpd_req_recv(req, buf + got, req->content_len - got);
        if (r <= 0) {
            return -1;
        }
        got += (size_t)r;
    }
    buf[got] = 0;
    return (int)got;
}

static esp_err_t page(httpd_req_t *req, const char *status, const char *msg)
{
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    char out[512];
    snprintf(out, sizeof(out),
             "<!doctype html><meta name=viewport content='width=device-width'>"
             "<body style='background:#0b0f0c;color:#d8e6d0;font:16px monospace;padding:16px'>"
             "<p>%s</p><p><a style='color:#9fdc6a' href='/'>Back</a></p>", msg);
    return httpd_resp_sendstr(req, out);
}

static esp_err_t save_post(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    char body[256], ssid[33], pass[65];
    int n = read_body(req, body, sizeof(body));
    if (n < 0 || form_get(body, (size_t)n, "ssid", ssid, sizeof(ssid)) < 1) {
        return page(req, "400 Bad Request", "A network name is needed.");
    }
    if (form_get(body, (size_t)n, "password", pass, sizeof(pass)) < 0) {
        pass[0] = 0;
    }
    esp_err_t r = wifi_link_save(ssid, pass);
    if (r == ESP_ERR_INVALID_ARG) {
        return page(req, "400 Bad Request", "The password is 8 to 63 characters (or empty for an open network).");
    }
    if (r != ESP_OK) {
        return page(req, "500 Internal Server Error", "Couldn't save it.");
    }
    return page(req, "200 OK", "Saved. Joining it now: this page's status shows when it's in.");
}

static esp_err_t forget_post(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    wifi_link_forget();
    return page(req, "200 OK", "Forgotten. It now joins only open Stump hotspots.");
}

/* On the setup AP, any other page leads to the setup page (captive portal). */
static esp_err_t not_found(httpd_req_t *req, httpd_err_code_t err)
{
    if (side_of(req) == SIDE_AP) {
        httpd_resp_set_status(req, "302 Found");
        httpd_resp_set_hdr(req, "Location", "http://10.77.1.1/");
        return httpd_resp_send(req, NULL, 0);
    }
    httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Not found");
    return ESP_OK;
}

esp_err_t web_start(void)
{
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.stack_size = 6144;
    cfg.lru_purge_enable = true;
    cfg.max_open_sockets = 5;
    httpd_handle_t h = NULL;
    esp_err_t r = httpd_start(&h, &cfg);
    if (r != ESP_OK) {
        return r;
    }
    const httpd_uri_t uris[] = {
        {.uri = "/status.json", .method = HTTP_GET, .handler = status_get},
        {.uri = "/", .method = HTTP_GET, .handler = root_get},
        {.uri = "/scan.json", .method = HTTP_GET, .handler = scan_get},
        {.uri = "/save", .method = HTTP_POST, .handler = save_post},
        {.uri = "/forget", .method = HTTP_POST, .handler = forget_post},
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) {
        httpd_register_uri_handler(h, &uris[i]);
    }
    httpd_register_err_handler(h, HTTPD_404_NOT_FOUND, not_found);
    ESP_LOGI(TAG, "http://10.77.0.1/status.json");
    return ESP_OK;
}
