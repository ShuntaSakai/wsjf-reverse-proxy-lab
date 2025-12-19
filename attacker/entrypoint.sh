#!/bin/sh
set -eu

# front側：reverse_proxy への行きを Zeek 経由にする
ip route replace 192.168.10.30 via 192.168.10.2

exec "$@"
