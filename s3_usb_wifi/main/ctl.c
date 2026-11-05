/*
 * The control channel: a CDC-ACM serial port next to the network card on
 * the same USB cable (the handheld sees /dev/ttyACMx), one JSON line each
 * way (ctl_core.h). It's how the Provisioner's S3 USB Wi-Fi page lists,
 * joins and forgets networks: the S3 has no address of its own on the
 * bridged network for HTTP.
 *
 * SPDX-License-Identifier: MIT
 */
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_check.h"
#include "tinyusb.h"
#include "tinyusb_cdc_acm.h"
#include "ctl_core.h"
#include "adapter.h"

static const char *TAG = "ctl";

static QueueHandle_t s_lines;          /* char* lines, malloc'ed */
static ctl_lines_t s_asm;              /* used in TinyUSB's task only */

static void on_rx(int itf, cdcacm_event_t *event)
{
    uint8_t buf[64];
    size_t n = 0;
    while (tinyusb_cdcacm_read(itf, buf, sizeof(buf), &n) == ESP_OK && n > 0) {
        for (size_t i = 0; i < n; i++) {
            const char *line = ctl_feed(&s_asm, (char)buf[i]);
            if (line && line[0]) {
                char *copy = strdup(line);
                if (copy && xQueueSend(s_lines, &copy, 0) != pdTRUE) {
                    free(copy);   /* busy: the Provisioner asks again */
                }
            }
        }
    }
}

static void send_line(const char *s)
{
    size_t n = strlen(s), at = 0;
    while (at < n) {
        size_t w = tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, (const uint8_t *)s + at, n - at);
        at += w;
        if (tinyusb_cdcacm_write_flush(TINYUSB_CDC_ACM_0, pdMS_TO_TICKS(200)) != ESP_OK && w == 0) {
            return;   /* nobody reading: drop it */
        }
    }
}

static void ctl_task(void *arg)
{
    static char data[2600];
    static char out[2700];
    for (;;) {
        char *line;
        if (xQueueReceive(s_lines, &line, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        ctl_req_t r;
        ctl_parse(line, strlen(line), &r);
        free(line);
        const char *err = r.error;
        const char *payload = NULL;
        switch (r.cmd) {
        case CTL_STATUS:
            if (api_status_json(data, sizeof(data))) {
                payload = data;
            } else {
                err = "too_long";
            }
            break;
        case CTL_SCAN:
            if (!wifi_link_scan_json(data, sizeof(data))) {
                /* cut short: close what's there */
                size_t l = strlen(data);
                while (l > 1 && data[l - 1] != '}') {
                    data[--l] = 0;
                }
                if (data[0] != '[') {
                    strcpy(data, "[");
                }
                strlcat(data, "]", sizeof(data));
            }
            payload = data;
            break;
        case CTL_SAVED:
            if (!wifi_link_saved_json(data, sizeof(data))) {
                strcpy(data, "[]");
            }
            payload = data;
            break;
        case CTL_JOIN:
            err = api_join(r.ssid, r.has_password ? r.password : NULL);
            break;
        case CTL_FORGET:
            err = api_forget(r.has_ssid && r.ssid[0] ? r.ssid : NULL);
            break;
        default:
            break;
        }
        memset(r.password, 0, sizeof(r.password));
        if (ctl_answer(out, sizeof(out), r.id, err, payload)) {
            send_line(out);
        }
    }
}

esp_err_t ctl_start(void)
{
    s_lines = xQueueCreate(4, sizeof(char *));
    ESP_RETURN_ON_FALSE(s_lines, ESP_ERR_NO_MEM, TAG, "queue");
    tinyusb_config_cdcacm_t acm = {
        .cdc_port = TINYUSB_CDC_ACM_0,
        .callback_rx = on_rx,
    };
    ESP_RETURN_ON_ERROR(tinyusb_cdcacm_init(&acm), TAG, "CDC-ACM");
    BaseType_t ok = xTaskCreate(ctl_task, "ctl", 6144, NULL, 4, NULL);
    ESP_RETURN_ON_FALSE(ok == pdPASS, ESP_ERR_NO_MEM, TAG, "task");
    ESP_LOGI(TAG, "control channel on the USB serial port");
    return ESP_OK;
}
