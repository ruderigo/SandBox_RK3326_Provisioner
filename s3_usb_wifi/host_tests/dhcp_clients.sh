#!/usr/bin/env bash
# The DHCP core against real Linux DHCP clients (dhclient, dhcpcd, busybox
# udhcpc), over a veth pair into a network namespace: the "handheld" in the
# namespace must get 10.77.0.2/24, a route to the S3's Wi-Fi via 10.77.0.1
# (option 121), no default route and no DNS from us; and when the S3 moves to
# another network, the route must follow within a lease renewal.
#
# Needs root (ip netns). Runs whichever of the clients are installed.
#   sudo bash host_tests/dhcp_clients.sh
set -uo pipefail
cd "$(dirname "$0")" || exit 1
work=$(mktemp -d)
NS=s3usbwifi_test
fails=0
pass() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; fails=$((fails + 1)); }

cleanup() {
    [ -n "${hpid:-}" ] && kill "$hpid" 2>/dev/null
    ip netns pids "$NS" 2>/dev/null | xargs -r kill 2>/dev/null
    ip netns del "$NS" 2>/dev/null
    ip link del s3h0 2>/dev/null
    rm -rf "$work"
}
trap cleanup EXIT

cc -std=c11 -Wall -Wextra -Werror -I../main -o "$work/harness" dhcp_harness.c ../main/dhcp_core.c || exit 1

ip netns del "$NS" 2>/dev/null; ip link del s3h0 2>/dev/null
ip netns add "$NS"
ip link add s3h0 type veth peer name usb0
ip link set usb0 netns "$NS"
ip addr add 10.77.0.1/24 dev s3h0
ip link set s3h0 up
ip -n "$NS" link set lo up
ip -n "$NS" link set usb0 up
# a stand-in for the handheld's own Wi-Fi default route
ip -n "$NS" link add wlan0 type veth peer name wlan0p
ip -n "$NS" link set wlan0p up
ip -n "$NS" addr add 192.168.1.50/24 dev wlan0
ip -n "$NS" link set wlan0 up
ip -n "$NS" route add default via 192.168.1.1 dev wlan0

"$work/harness" s3h0 > "$work/harness.log" 2>&1 &
hpid=$!
sleep 0.3

in_ns() { ip netns exec "$NS" "$@" 2> >(grep -v "Peer netns reference" >&2); }
routes() { in_ns ip -4 route show; }

# waits up to $1 s for "$2" (a grep -E pattern) to be in (or, with !, out of) the routes
wait_route() {
    local t=$1 pat=$2 neg=${3:-}
    for _ in $(seq $((t * 2))); do
        if [ -z "$neg" ] && routes | grep -Eq "$pat"; then return 0; fi
        if [ -n "$neg" ] && ! routes | grep -Eq "$pat"; then return 0; fi
        sleep 0.5
    done
    return 1
}

check_client() {
    local name=$1
    echo "== $name"
    if in_ns ip -4 addr show usb0 | grep -q "10.77.0.2/24"; then pass "10.77.0.2/24 on usb0"; else fail "no 10.77.0.2/24"; in_ns ip -4 addr show usb0; fi
    if wait_route 5 "^192\.168\.4\.0/24 via 10\.77\.0\.1 dev usb0"; then pass "192.168.4.0/24 via 10.77.0.1 (option 121)"; else fail "no route to the S3's Wi-Fi"; routes; fi
    if [ "$(routes | grep -c '^default')" = 1 ] && routes | grep -q "^default via 192.168.1.1 dev wlan0"; then pass "the default route is still only wlan0's"; else fail "default route changed"; routes; fi
    if ! grep -q "10.77" "$work/resolv.conf" 2>/dev/null; then pass "no DNS from the S3"; else fail "a DNS from the S3"; fi

    kill -USR2 "$hpid"   # the S3 moves to 192.168.50.0/24
    if wait_route 50 "^192\.168\.50\.0/24 via 10\.77\.0\.1 dev usb0" && wait_route 5 "^192\.168\.4\.0/24" not; then
        pass "after a network change: 192.168.50.0/24 via 10.77.0.1, the old route gone"
    else
        fail "the route didn't follow the network change"; routes
    fi
    kill -HUP "$hpid"    # the S3 has no Wi-Fi
    if wait_route 50 "^192\.168\.50\.0/24" not; then pass "Wi-Fi lost: its route gone"; else fail "the route stayed"; routes; fi
    if in_ns ip -4 addr show usb0 | grep -q "10.77.0.2/24"; then pass "still 10.77.0.2/24 (status.json stays reachable)"; else fail "lost 10.77.0.2"; fi
}

reset_ns() {
    in_ns ip addr flush dev usb0
    in_ns ip route flush dev usb0 2>/dev/null
    kill -USR1 "$hpid"   # the S3 is on 192.168.4.0/24
    sleep 0.2
}

ran=0
if command -v dhclient >/dev/null; then
    ran=1; reset_ns
    cat > "$work/dhclient.conf" <<'EOF'
option rfc3442-classless-static-routes code 121 = array of unsigned integer 8;
request subnet-mask, broadcast-address, routers, domain-name-servers, rfc3442-classless-static-routes;
EOF
    # dhclient-script writes DNS to /etc/resolv.conf: give it a copy to write
    touch "$work/resolv.conf"
    # only the option 121 hook: others (systemd-resolved's) can end the hook chain early
    mkdir -p "$work/exit-hooks" "$work/enter-hooks"
    cp /etc/dhcp/dhclient-exit-hooks.d/rfc3442-classless-routes "$work/exit-hooks/" 2>/dev/null
    in_ns unshare -m sh -c "mount --bind '$work/resolv.conf' /etc/resolv.conf && \
        mount --bind '$work/exit-hooks' /etc/dhcp/dhclient-exit-hooks.d && \
        mount --bind '$work/enter-hooks' /etc/dhcp/dhclient-enter-hooks.d && \
        dhclient -4 -v -cf '$work/dhclient.conf' -pf '$work/dhclient.pid' -lf '$work/dhclient.leases' usb0" \
        > "$work/dhclient.log" 2>&1 &
    sleep 4
    f0=$fails
    check_client "dhclient (ISC)"
    if [ "$fails" != "$f0" ]; then
        echo "  -- dhclient's log and lease:"; sed 's/^/     /' "$work/dhclient.log" "$work/dhclient.leases" 2>/dev/null | tail -n 40
    fi
    [ -f "$work/dhclient.pid" ] && kill "$(cat "$work/dhclient.pid")" 2>/dev/null
    sleep 0.5
fi

if command -v dhcpcd >/dev/null; then
    ran=1; reset_ns; : > "$work/resolv.conf"
    cat > "$work/dhcpcd.conf" <<'EOF'
option classless_static_routes, domain_name_servers, routers
nohook resolv.conf
ipv4only
noarp
EOF
    in_ns dhcpcd -B -4 -f "$work/dhcpcd.conf" usb0 > "$work/dhcpcd.log" 2>&1 &
    dpid=$!
    sleep 4
    check_client "dhcpcd"
    kill "$dpid" 2>/dev/null
    sleep 0.5
fi

if command -v busybox >/dev/null && busybox --list | grep -qx udhcpc; then
    ran=1; reset_ns; : > "$work/resolv.conf"
    # busybox's own example script, reduced: address, then $staticroutes
    cat > "$work/udhcpc.sh" <<'EOF'
#!/bin/sh
case "$1" in
  deconfig) ip -4 addr flush dev "$interface"; ip -4 route flush dev "$interface" 2>/dev/null ;;
  bound|renew)
    ip -4 route flush dev "$interface" 2>/dev/null
    ip -4 addr flush dev "$interface"
    ip -4 addr add "$ip/$mask" dev "$interface"
    [ -n "$router" ] && ip route add default via "$router" dev "$interface"
    set -- $staticroutes
    while [ $# -ge 2 ]; do ip route add "$1" via "$2" dev "$interface"; shift 2; done
    [ -n "$dns" ] && echo "nameserver $dns" >> "$RESOLV" ;;
esac
EOF
    chmod +x "$work/udhcpc.sh"
    in_ns env RESOLV="$work/resolv.conf" busybox udhcpc -f -i usb0 -s "$work/udhcpc.sh" -O staticroutes \
        > "$work/udhcpc.log" 2>&1 &
    upid=$!
    sleep 4
    check_client "udhcpc (busybox)"
    kill "$upid" 2>/dev/null
fi

echo "== the server's side"
sed 's/^/  /' "$work/harness.log" | tail -n 40
[ "$ran" = 1 ] || { echo "no DHCP client installed"; exit 1; }
echo "$fails failed"
[ "$fails" = 0 ]
