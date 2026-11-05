#!/usr/bin/env bash
# The firmware's DHCP core against real Linux DHCP clients (dhclient, dhcpcd,
# busybox udhcpc), over a veth pair into a network namespace, as the setup
# AP serves the phones that join it: an address in 10.77.1.0/24, the S3
# (10.77.1.1) as router and DNS (that's what makes phones show the setup
# page), and renewals that change nothing (a short lease here, to see a few).
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
ip addr add 10.77.1.1/24 dev s3h0
ip link set s3h0 up
ip -n "$NS" link set lo up
ip -n "$NS" link set usb0 up

"$work/harness" s3h0 12 > "$work/harness.log" 2>&1 &
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

# the DNS it took: from resolv.conf, or (dhcpcd, whose hooks may hand it to
# resolvconf or systemd-resolved instead) from its lease
dns_is() {
    grep -q "^nameserver $1\$" "$work/resolv.conf" 2>/dev/null && return 0
    [ "${client:-}" = dhcpcd ] && in_ns dhcpcd -4 -U usb0 2>/dev/null | grep -q "^domain_name_servers='\?$1'\?\$"
}

wait_dns() {
    for _ in $(seq $(($1 * 2))); do dns_is "$2" && return 0; sleep 0.5; done
    return 1
}

renewals() { grep -c "(renewing) -> ACK" "$work/harness.log"; }

check_client() {
    local name=$1
    echo "== $name"
    if in_ns ip -4 addr show usb0 | grep -q "10.77.1.2/24"; then pass "10.77.1.2/24 on usb0"; else fail "no 10.77.1.2/24"; in_ns ip -4 addr show usb0; fi
    if wait_route 5 "^default via 10\.77\.1\.1 dev usb0"; then pass "default route via 10.77.1.1"; else fail "no default route via the S3"; routes; fi
    if wait_dns 5 10.77.1.1; then pass "DNS 10.77.1.1"; else fail "not 10.77.1.1 as DNS"; cat "$work/resolv.conf"; fi
    # renewals (12 s leases: one every ~6 s) are ACKed and change nothing
    local r0 t
    r0=$(renewals)
    for t in $(seq 40); do [ "$(renewals)" -ge $((r0 + 2)) ] && break; sleep 0.5; done
    if [ "$(renewals)" -ge $((r0 + 2)) ]; then pass "renewals ACKed ($(( $(renewals) - r0 )) in ${t}x0.5 s)"; else fail "no renewals seen"; fi
    if in_ns ip -4 addr show usb0 | grep -q "10.77.1.2/24" && routes | grep -q "^default via 10\.77\.1\.1 dev usb0" && dns_is 10.77.1.1; then
        pass "after them: the same address, default route and DNS"
    else
        fail "something changed on a renewal"; routes
    fi
}

reset_ns() {
    in_ns ip addr flush dev usb0
    in_ns ip route flush dev usb0 2>/dev/null
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
ipv4only
noarp
EOF
    in_ns unshare -m sh -c "mount --bind '$work/resolv.conf' /etc/resolv.conf && \
        exec dhcpcd -B -4 -f '$work/dhcpcd.conf' usb0" > "$work/dhcpcd.log" 2>&1 &
    dpid=$!
    sleep 4
    client=dhcpcd check_client "dhcpcd"
    kill "$dpid" 2>/dev/null
    sleep 0.5
fi

if command -v busybox >/dev/null && busybox --list | grep -qx udhcpc; then
    ran=1; reset_ns; : > "$work/resolv.conf"
    # busybox's own example script, reduced: address, then $staticroutes
    cat > "$work/udhcpc.sh" <<'EOF'
#!/bin/sh
case "$1" in
  deconfig) ip -4 addr flush dev "$interface"; ip -4 route flush dev "$interface" 2>/dev/null; : > "$RESOLV" ;;
  bound|renew)
    ip -4 route flush dev "$interface" 2>/dev/null
    ip -4 addr flush dev "$interface"
    ip -4 addr add "$ip/$mask" dev "$interface"
    [ -n "$router" ] && ip route add default via "$router" dev "$interface"
    set -- $staticroutes
    while [ $# -ge 2 ]; do ip route replace "$1" via "$2" dev "$interface"; shift 2; done
    : > "$RESOLV"; for d in $dns; do echo "nameserver $d" >> "$RESOLV"; done ;;
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
sed 's/^/  /' "$work/harness.log" | tail -n 60
[ "$ran" = 1 ] || { echo "no DHCP client installed"; exit 1; }
echo "$fails failed"
[ "$fails" = 0 ]
