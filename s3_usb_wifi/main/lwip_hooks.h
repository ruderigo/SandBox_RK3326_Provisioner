/*
 * Our lwIP hook (built into lwIP via ESP_IDF_LWIP_HOOK_FILENAME): every
 * IPv4 packet passes s3_ip4_input_filter() before lwIP looks at it.
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
struct pbuf;
struct netif;
int s3_ip4_input_filter(struct pbuf *p, struct netif *inp);
#define LWIP_HOOK_IP4_INPUT(p, inp) s3_ip4_input_filter((p), (inp))
