# Vendored components

Built with the ESP-IDF component manager off (`IDF_COMPONENT_MANAGER=0`),
so the build needs nothing but ESP-IDF v5.3 and this folder.

| Component | Version | From | Licence |
|---|---|---|---|
| `esp_tinyusb/` | 3.0.0 | [espressif/esp-usb](https://github.com/espressif/esp-usb) `device/esp_tinyusb`, commit `6a577e5c946edefdcefc45af94ded4e5f2f5ed0f` | Apache-2.0 (`esp_tinyusb/LICENSE`) |
| `esp_tinyusb/tinyusb/` | (submodule) | [hathach/tinyusb](https://github.com/hathach/tinyusb) via Espressif's fork, commit `894ea01409e0407a7dbe0ee29b2d58a4691f9046` | MIT (`esp_tinyusb/tinyusb/LICENSE`) |

Unchanged except for files left out (as esp-usb's own `idf_component.yml`
leaves them out of its published package): esp_tinyusb's `test_apps/`, and
TinyUSB's docs, tools, tests, examples, board files, `lib/` except
`networking/`, and its build files for other systems.
