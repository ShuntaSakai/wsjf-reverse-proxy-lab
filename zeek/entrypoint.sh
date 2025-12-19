#!/bin/sh
set -eu

# 全転送パケットを許可
iptables -P FORWARD ACCEPT || true

exec "$@"
