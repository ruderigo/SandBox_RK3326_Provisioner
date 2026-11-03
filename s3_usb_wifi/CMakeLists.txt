# FireFly S3 USB Wi-Fi: ESP-IDF v5.3 project (target esp32s3).
cmake_minimum_required(VERSION 3.16)
set(PROJECT_VER "0.2.0")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# Reproducible across machines: ESP-IDF maps its own and the project's paths;
# also map where its tools live, which ends up in the debug info (and so in
# the ELF's SHA-256 inside the image).
if(DEFINED ENV{IDF_TOOLS_PATH})
    set(tools_path "$ENV{IDF_TOOLS_PATH}")
else()
    set(tools_path "$ENV{HOME}/.espressif")
endif()
get_filename_component(tools_real "${tools_path}" REALPATH)
idf_build_set_property(COMPILE_OPTIONS "-fdebug-prefix-map=${tools_real}=/IDF_TOOLS" APPEND)
if(NOT tools_real STREQUAL tools_path)
    idf_build_set_property(COMPILE_OPTIONS "-fdebug-prefix-map=${tools_path}=/IDF_TOOLS" APPEND)
endif()
project(s3_usb_wifi)
