#!/usr/bin/env python3
import os, sys, re
from collections import deque
from datetime import datetime

# GUIが無い環境でも必ず保存できるようにする
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

TS_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)\s+(.*)$")
SCHED_RE = re.compile(r"\[Scheduler\].*cid=([A-Za-z0-9\?]).*qsize=(\d+)")
ENQ_RE   = re.compile(r"\[Enqueue\].*cid=([A-Za-z0-9\?])")

def parse_ts(s: str):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

MAX_N = 20000
tq = deque(maxlen=MAX_N)
qsize = deque(maxlen=MAX_N)
WIN = 500
send_cid = deque(maxlen=WIN)

out_path = os.getenv("OUT", "").strip()
if not out_path:
    os.makedirs("out", exist_ok=True)
    out_path = f"out/wsjf_plot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
else:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

fig, ax = plt.subplots()
ax.set_title("reverse_proxy scheduler qsize (and recent send mix)")
ax.set_xlabel("time")
ax.set_ylabel("queue size")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
line_q, = ax.plot([], [])
text = ax.text(0.02, 0.95, "", transform=ax.transAxes, va="top")

def redraw(final=False):
    if len(tq) < 2:
        return
    line_q.set_data(list(tq), list(qsize))
    ax.relim()
    ax.autoscale_view()

    if send_cid:
        f = sum(1 for c in send_cid if c == "F")
        s = sum(1 for c in send_cid if c == "S")
        total = len(send_cid)
        text.set_text(f"recent sends (last {total}): F={f}  S={s}")

    if final:
        fig.tight_layout()
        fig.savefig(out_path, dpi=150)
        print(f"[log_plot] saved: {out_path}", file=sys.stderr)

try:
    for raw in sys.stdin:
        raw = raw.rstrip("\n")
        m = TS_RE.match(raw)
        if not m:
            continue
        ts_s, msg = m.group(1), m.group(2)
        try:
            ts = parse_ts(ts_s)
        except Exception:
            continue

        ms = SCHED_RE.search(msg)
        if ms:
            cid = ms.group(1)
            qs = int(ms.group(2))
            tq.append(ts)
            qsize.append(qs)
            send_cid.append(cid)
            continue

        # enqueue を使って別指標にしたいならここで処理
        if ENQ_RE.search(msg):
            pass

except KeyboardInterrupt:
    pass
finally:
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"[log_plot] saved: {out_path}", file=sys.stderr)
