/*
 * FireFly S3 USB Wi-Fi: an ESP32-S3 (Freenove WROOM CAM) as the Wi-Fi card
 * of an RK3326 handheld. On its native USB it's a CDC-NCM network card
 * bridged to the Wi-Fi it joined (the handheld is on that network itself),
 * plus a serial port the Provisioner uses to choose the network.
 *
 * SPDX-License-Identifier: MIT
 */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "adapter.h"

static const char *TAG = "s3_usb_wifi";

#define BOOT_GPIO        GPIO_NUM_0
#define BUTTON_WINDOW_MS 4000
#define BUTTON_HOLD_MS   1000

/* BOOT held for a second within the first seconds after power-up (holding it
 * *at* power-up starts the ROM's download mode instead). */
static bool boot_button_held(void)
{
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << BOOT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&io);
    int held = 0;
    for (int t = 0; t < BUTTON_WINDOW_MS; t += 20) {
        held = gpio_get_level(BOOT_GPIO) == 0 ? held + 20 : 0;
        if (held >= BUTTON_HOLD_MS) {
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    return false;
}

void app_main(void)
{
    esp_err_t r = nvs_flash_init();
    if (r == ESP_ERR_NVS_NO_FREE_PAGES || r == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        r = nvs_flash_init();
    }
    ESP_ERROR_CHECK(r);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_netif_t *ap = wifi_link_init(false);
    ESP_ERROR_CHECK(usb_net_start());     /* the network card (link down until joined) */
    ESP_ERROR_CHECK(ctl_start());         /* and its control port */
    ESP_ERROR_CHECK(netsvc_start(ap));
    ESP_ERROR_CHECK(web_start());
    wifi_link_start();

    if (boot_button_held()) {
        ESP_LOGI(TAG, "BOOT held: opening the setup AP");
        wifi_link_request_setup();
    }
}
