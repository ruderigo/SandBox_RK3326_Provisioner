idf_component_register(
    SRCS "app_main.c" "usb_net.c" "netsvc.c" "wifi_link.c" "web.c"
         "dhcp_core.c" "util_core.c"
    INCLUDE_DIRS "."
    EMBED_TXTFILES "setup.html"
    PRIV_REQUIRES esp_tinyusb esp_netif esp_wifi esp_event esp_http_server
                  esp_http_client nvs_flash esp_driver_gpio esp_timer lwip esp_app_format
)

# Our input filter, built into lwIP (see lwip_hooks.h)
idf_component_get_property(lwip lwip COMPONENT_LIB)
target_compile_options(${lwip} PRIVATE "-I${CMAKE_CURRENT_LIST_DIR}")
target_compile_definitions(${lwip} PRIVATE "-DESP_IDF_LWIP_HOOK_FILENAME=\"lwip_hooks.h\"")
