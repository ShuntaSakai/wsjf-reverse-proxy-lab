#!/usr/bin/env bash
set -euo pipefail

stty -tostop 2>/dev/null || true
mkdir -p out

FILTER='\[Enqueue\]|\[Scheduler\]|\[proxy\]|\[backnet\]'

# 今から出るログだけ拾うための since（UTC, RFC3339）
now_utc() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

capture_logs() {
  local outfile="$1"
  local since="$2"

  : > "$outfile"
  # ファイルには生ログ、画面には色付き（欲しければ）
  (
    docker compose logs -f --tail=0 --timestamps --since "$since" reverse_proxy \
    | egrep --line-buffered "$FILTER" \
    | tee -a "$outfile" \
    | stdbuf -oL perl -pe 'if(/\[Enqueue\]/){$_="\e[32m".$_}elsif(/\[Scheduler\]/){$_="\e[31m".$_}
      s/(cid=F)/\e[34m$1\e[39m/g;s/(cid=S)/\e[33m$1\e[39m/g;s/\n/\e[0m\n/;'
  ) &
  echo $!
}

stop_capture() {
  local pid="$1"
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

echo "=== BASELINE (F only) ==="
SINCE=$(now_utc)
LOGPID=$(capture_logs out/baseline_experiment_raw.log "$SINCE")

docker compose run --rm -T -e CID=F -e MODE=fast -e COUNT=600 seq-client \
  python numbered_client.py </dev/null

sleep 0.2
stop_capture "$LOGPID"
echo "baseline log -> out/baseline_experiment_raw.log"

echo
echo "=== EXPERIMENT (F + S) ==="
SINCE=$(now_utc)
LOGPID=$(capture_logs out/experiment_raw.log "$SINCE")

docker compose run --rm -T -e CID=F -e MODE=fast -e COUNT=600 seq-client \
  python numbered_client.py </dev/null \
&

docker compose run --rm -T -e CID=S -e MODE=slow -e COUNT=60 seq-client \
  python numbered_client.py </dev/null

wait

sleep 0.2
stop_capture "$LOGPID"
echo "experiment log -> out/experiment_raw.log"

echo "done"
