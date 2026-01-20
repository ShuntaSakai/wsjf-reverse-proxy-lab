#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
mkdir -p out

COUNT_F=100
COUNT_S=60

PAD_LIST=(1000 2000 3000 4000 5000 6000 6500 7000 7500 7750 7875 8000)

RESULTS_CSV="out/df_sweep_$(date +%Y%m%d_%H%M%S).csv"

# ---- log capture helpers (HARD FIX) ----
# IMPORTANT:
# - Do NOT use command substitution to capture PID (it hangs).
# - Instead, set a global variable CAPTURE_PID.
CAPTURE_PID=""

start_log_capture() {
  local out_file="$1"

  # Run pipeline in a new session (own process group)
  # Redirect stdout/stderr to avoid spamming terminal; tee still writes to file.
  setsid bash -c "
    docker compose logs -f --tail=0 --timestamps reverse_proxy \
      | egrep --line-buffered '\\[Enqueue\\]|\\[Scheduler\\]|\\[proxy\\]|\\[backnet\\]' \
      | tee -a '$out_file' >/dev/null
  " >/dev/null 2>&1 &

  CAPTURE_PID=$!
}

stop_log_capture() {
  local pid="$1"
  # Kill whole process group of the session leader
  kill -- -"$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

# ---- wait until reverse_proxy drains queue (by observing Scheduler count) ----
wait_drain_by_scheduler_count() {
  local log="$1"
  local expected="$2"
  local timeout="${3:-180}"
  local start
  start="$(date +%s)"

  local last=-1
  local stable=0

  while true; do
    local cur
    cur="$(grep -c '\[Scheduler\]' "$log" 2>/dev/null || true)"
    cur="${cur:-0}"

    if [ "$cur" -ge "$expected" ]; then
      if [ "$cur" -eq "$last" ]; then
        stable=$((stable + 1))
      else
        stable=0
      fi
      if [ "$stable" -ge 2 ]; then
        echo "[drain] ok: Scheduler=$cur expected=$expected"
        return 0
      fi
    fi

    last="$cur"

    if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
      echo "[drain][WARN] timeout: Scheduler=$cur expected=$expected (log=$log)" >&2
      return 1
    fi

    sleep 0.5
  done
}

docker compose up -d --build reverse_proxy seq-server >/dev/null

# ---- baseline (once) ----
BASELINE_LOG="out/baseline_experiment_raw.log"
: > "$BASELINE_LOG"

echo "[baseline] start log capture -> $BASELINE_LOG"
start_log_capture "$BASELINE_LOG"
BASE_PID="$CAPTURE_PID"
sleep 0.5

stty -tostop 2>/dev/null || true
docker compose run --rm -T -e CID=F -e MODE=fast -e COUNT="$COUNT_F" seq-client \
  python numbered_client.py </dev/null

# IMPORTANT: wait until reverse_proxy actually flushes all Scheduler logs
wait_drain_by_scheduler_count "$BASELINE_LOG" "$COUNT_F" 180 || true

stop_log_capture "$BASE_PID"
echo "[baseline] done"

# header
echo "pad,S_effort_bps,DF,lost_F_bps,F_base_bps,F_attack_bps,atk_F_cnt_in_T,atk_S_enq_cnt_in_T" > "$RESULTS_CSV"

# ---- sweep ----
for PAD in "${PAD_LIST[@]}"; do
  echo
  echo "==============================="
  echo "[sweep] PAD=$PAD"
  echo "==============================="

  docker compose restart reverse_proxy >/dev/null
  sleep 1

  EXP_LOG="out/experiment_pad_${PAD}.log"
  : > "$EXP_LOG"

  echo "[sweep] start log capture -> $EXP_LOG"
  start_log_capture "$EXP_LOG"
  EXP_PID="$CAPTURE_PID"
  sleep 0.5

  stty -tostop 2>/dev/null || true

  docker compose run --rm -T -e CID=F -e MODE=fast -e COUNT="$COUNT_F" seq-client \
    python numbered_client.py </dev/null &
  F_PID=$!

  docker compose run --rm -T -e CID=S -e MODE=slow -e COUNT="$COUNT_S" -e PAD="$PAD" seq-client \
    python numbered_client.py </dev/null

  wait "$F_PID"

  # IMPORTANT: wait until reverse_proxy flushes all Scheduler logs for BOTH clients
  EXPECTED=$((COUNT_F + COUNT_S))
  wait_drain_by_scheduler_count "$EXP_LOG" "$EXPECTED" 300 || true

  stop_log_capture "$EXP_PID"

  OUT="$(python3 tools/seq_payload/log_analyzer_df.py "$EXP_LOG" "$BASELINE_LOG" 2>&1 || true)"

  S_EFF="$(echo "$OUT" | awk '/S_effort_bps/{print $3}' | tail -n 1)"
  DF="$(echo "$OUT" | awk '/^DF[[:space:]]*:/{print $3}' | tail -n 1)"
  LOST="$(echo "$OUT" | awk '/lost_F_bps/{print $3}' | tail -n 1)"
  FBASE="$(echo "$OUT" | awk '/F_base_bps/{print $3}' | tail -n 1)"
  FATK="$(echo "$OUT" | awk '/F_attack_bps/{print $3}' | tail -n 1)"

  SANITY_LINE="$(echo "$OUT" | grep -E '^\[sanity\].*atk_F_cnt_in_T=' | tail -n 1 || true)"
  AF="$(echo "$SANITY_LINE" | awk -F'[=,]' '{print $4}' | awk '{print $1}' | tail -n 1)"
  AS="$(echo "$SANITY_LINE" | awk -F'[=,]' '{print $6}' | awk '{print $1}' | tail -n 1)"

  echo "[sweep] parsed: S_effort_bps=${S_EFF:-} DF=${DF:-} lost=${LOST:-} atkF=${AF:-} atkS=${AS:-}"

  echo "$PAD,${S_EFF:-},${DF:-},${LOST:-},${FBASE:-},${FATK:-},${AF:-},${AS:-}" >> "$RESULTS_CSV"
done

echo
echo "[done] results: $RESULTS_CSV"
echo "Next: python3 tools/seq_payload/plot_df_vs_effort.py $RESULTS_CSV"
