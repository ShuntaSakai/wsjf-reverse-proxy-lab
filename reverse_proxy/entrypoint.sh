#!/bin/sh
set -eu

# front側：attackerへの返りをZeek経由
ip route replace 192.168.10.10 via 192.168.10.2 || true

# back側：victimへの行きをZeek経由
ip route replace 192.168.20.20 via 192.168.20.2 || true

exec "$@"
