#!/bin/sh
set -eu

# back側：reverse_proxy への返りを Zeek 経由にする
ip route replace 192.168.20.30 via 192.168.20.2 || true

exec "$@"
