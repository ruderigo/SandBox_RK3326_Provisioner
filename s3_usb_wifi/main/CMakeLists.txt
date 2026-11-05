idf_component_register(
    SRCS "app_main.c" "usb_net.c" "ctl.c" "api.c" "netsvc.c" "wifi_link.c" "web.c"
         "dhcp_core.c" "util_core.c" "ctl_core.c"
    INCLUDE_DIRS "."
    EMBED_TXTFILES "setup.html"
    PRIV_REQUIRES esp_tinyusb esp_netif esp_wifi esp_event esp_http_server
                  nvs_flash esp_driver_gpio esp_timer lwip esp_app_format
)
