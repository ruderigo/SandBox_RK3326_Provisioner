/*
 * HTTP on port 80, on the setup AP (10.77.1.1) only: the S3 has no address
 * anywhere else (the handheld's side is a bridge; the Provisioner uses the
 * USB serial port, ctl.c).
 *
 *   GET  /status.json    as api.c says
 *   GET  /               the setup page
 *   GET  /scan.json      nearby networks [{"ssid","rssi","open","saved"}]
 *   GET  /networks.json  the saved networks' names, most recent first
 *   POST /join, /save    ssid=…[&password=…]  remember it and join it now
 *   POST /forget         [ssid=…]  forget it (or all)
 * (form-encoded; JSON answers with "Accept: application/json")
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

typedef enum { SIDE_AP, SIDE_OTHER } side_t;

/* Which address did the request come in on? Only the setup AP's is served. */
static side_t side_of(httpd_req_t *req)
{
    struct sockaddr_storage ss;
    socklen_t len = sizeof(ss);
    int fd = httpd_req_to_sockfd(req);
    if (getsockname(fd, (struct sockaddr *)&ss, &len) != 0 || ss.ss_family != AF_INET) {
        return SIDE_OTHER;
    }
    uint32_t a = lwip_ntohl(((struct sockaddr_in *)&ss)->sin_addr.s_addr);
    return (a == ADAPTER_AP_IP && adapter_setup_ap_open()) ? SIDE_AP : SIDE_OTHER;
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
    static char out[640];
    if (!api_status_json(out, sizeof(out))) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "too long");
        return ESP_OK;
    }
    strlcat(out, "\n", sizeof(out));
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

static bool wants_json(httpd_req_t *req)
{
    char accept[64] = "";
    httpd_req_get_hdr_value_str(req, "Accept", accept, sizeof(accept));
    return strstr(accept, "application/json") != NULL;
}

static esp_err_t reply_json(httpd_req_t *req, const char *status, const char *error)
{
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, "application/json");
    nocache(req);
    char out[96] = "{\"ok\":";
    if (error) {
        strlcat(out, "false,\"error\":", sizeof(out));
        json_put_str(out, sizeof(out), error);
    } else {
        strlcat(out, "true", sizeof(out));
    }
    strlcat(out, "}\n", sizeof(out));
    return httpd_resp_sendstr(req, out);
}

/*
 * POST /save (the setup page's form) and POST /join (the Provisioner): remember
 * ssid and join it now. password: empty for an open network; left out, a
 * saved network keeps its own. Answers JSON when asked (Accept), else a page.
 */
static esp_err_t join_post(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    bool json = wants_json(req);
    char body[256], ssid[33], pass[65];
    int n = read_body(req, body, sizeof(body));
    if (n < 0 || form_get(body, (size_t)n, "ssid", ssid, sizeof(ssid)) < 1) {
        return json ? reply_json(req, "400 Bad Request", "no_ssid")
               : page(req, "400 Bad Request", "A network name is needed.");
    }
    bool has_pass = form_get(body, (size_t)n, "password", pass, sizeof(pass)) >= 0;
    const char *err = api_join(ssid, has_pass ? pass : NULL);
    memset(pass, 0, sizeof(pass));
    if (err && strcmp(err, "not_stored") != 0) {
        return json ? reply_json(req, "400 Bad Request", err)
               : page(req, "400 Bad Request", "The password is 8 to 63 characters (or empty for an open network).");
    }
    if (err) {
        return json ? reply_json(req, "500 Internal Server Error", err)
               : page(req, "500 Internal Server Error", "Couldn't save it.");
    }
    return json ? reply_json(req, "200 OK", NULL)
           : page(req, "200 OK", "Saved. Joining it now: this page's status shows when it's in.");
}

/* POST /forget: ssid=... forgets that network; no ssid, all of them. */
static esp_err_t forget_post(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    bool json = wants_json(req);
    char body[128], ssid[33];
    int n = read_body(req, body, sizeof(body));
    bool one = n > 0 && form_get(body, (size_t)n, "ssid", ssid, sizeof(ssid)) > 0;
    const char *err = api_forget(one ? ssid : NULL);
    if (json) {
        return !err ? reply_json(req, "200 OK", NULL)
               : reply_json(req, strcmp(err, "not_saved") == 0 ? "404 Not Found" : "500 Internal Server Error", err);
    }
    return page(req, "200 OK", one ? "Forgotten." : "All forgotten.");
}

static esp_err_t networks_get(httpd_req_t *req)
{
    if (side_of(req) == SIDE_OTHER) {
        return refuse(req);
    }
    char out[8 * 40 + 8];
    if (!wifi_link_saved_json(out, sizeof(out))) {
        strlcpy(out, "[]", sizeof(out));
    }
    httpd_resp_set_type(req, "application/json");
    nocache(req);
    return httpd_resp_sendstr(req, out);
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
    cfg.max_uri_handlers = 10;
    httpd_handle_t h = NULL;
    esp_err_t r = httpd_start(&h, &cfg);
    if (r != ESP_OK) {
        return r;
    }
    const httpd_uri_t uris[] = {
        {.uri = "/status.json", .method = HTTP_GET, .handler = status_get},
        {.uri = "/", .method = HTTP_GET, .handler = root_get},
        {.uri = "/scan.json", .method = HTTP_GET, .handler = scan_get},
        {.uri = "/save", .method = HTTP_POST, .handler = join_post},
        {.uri = "/join", .method = HTTP_POST, .handler = join_post},
        {.uri = "/forget", .method = HTTP_POST, .handler = forget_post},
        {.uri = "/networks.json", .method = HTTP_GET, .handler = networks_get},
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) {
        httpd_register_uri_handler(h, &uris[i]);
    }
    httpd_register_err_handler(h, HTTPD_404_NOT_FOUND, not_found);
    ESP_LOGI(TAG, "the setup page on http://10.77.1.1/ (while the setup AP is open)");
    return ESP_OK;
}
