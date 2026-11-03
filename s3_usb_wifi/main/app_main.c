/*
 * FireFly S3 USB Wi-Fi: an ESP32-S3 (Freenove WROOM CAM) as a USB network
 * card for RK3326 handhelds. On its native USB it's a CDC-NCM device at
 * 10.77.0.1/24 handing out 10.77.0.2 (no default route, no DNS: only the
 * Wi-Fi it joined, as option 121), and NATs that to the Wi-Fi it joined.
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

    /* USB first: the handheld gets its address while Wi-Fi is still joining */
    esp_netif_t *usb = usb_net_start();
    esp_netif_t *ap = wifi_link_init(false);
    ESP_ERROR_CHECK(netsvc_start(usb, ap));
    ESP_ERROR_CHECK(esp_netif_napt_enable(usb));   /* USB -> the joined Wi-Fi */
    ESP_ERROR_CHECK(web_start());
    wifi_link_start();

    if (boot_button_held()) {
        ESP_LOGI(TAG, "BOOT held: opening the setup AP");
        wifi_link_request_setup();
    }
}
